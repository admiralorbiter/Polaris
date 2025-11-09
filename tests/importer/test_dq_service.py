from __future__ import annotations

import csv
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from flask_app.importer.pipeline.dq_service import (
    DataQualityViolationService,
    RemediationValidationError,
    ViolationFilters,
)
from flask_app.models import AdminLog, ContactEmail, ContactPhone, User, Volunteer, db
from flask_app.models.importer.schema import (
    CleanVolunteer,
    DataQualitySeverity,
    DataQualityStatus,
    ImportRun,
    ImportRunStatus,
    DataQualityViolation,
    StagingVolunteer,
)


def test_violation_list_filters(importer_app, violation_factory):
    violation_factory(rule_code="VOL_EMAIL_INVALID", severity=DataQualitySeverity.ERROR, status=DataQualityStatus.OPEN)
    violation_factory(rule_code="VOL_PHONE_INVALID", severity=DataQualitySeverity.WARNING, status=DataQualityStatus.OPEN)

    service = DataQualityViolationService()
    filters = ViolationFilters.coerce(rule_codes=["VOL_EMAIL_INVALID"])
    result = service.list_violations(filters)

    assert result.total == 1
    assert result.items[0].rule_code == "VOL_EMAIL_INVALID"


def test_violation_stats(importer_app, violation_factory):
    violation_factory(rule_code="VOL_EMAIL_INVALID", severity=DataQualitySeverity.ERROR)
    violation_factory(rule_code="VOL_EMAIL_INVALID", severity=DataQualitySeverity.ERROR)
    violation_factory(rule_code="VOL_PHONE_INVALID", severity=DataQualitySeverity.WARNING)

    service = DataQualityViolationService()
    filters = ViolationFilters.coerce()
    stats = service.get_stats(filters)

    assert stats.total == 3
    assert stats.by_rule_code["VOL_EMAIL_INVALID"] == 2
    assert stats.by_severity[DataQualitySeverity.ERROR.value] == 2


def test_violation_export_sanitizes_csv(importer_app, violation_factory):
    violation = violation_factory()
    violation.staging_row.payload_json = {
        **violation.staging_row.payload_json,
        "email": '=HYPERLINK("http://evil")',
    }
    violation.details_json = {"formula": "+SUM(1,2)"}
    db.session.commit()
    service = DataQualityViolationService()
    filters = ViolationFilters.coerce()

    filename, csv_content = service.export_csv(filters, limit=10)
    assert filename.startswith("dq_violations_export_")
    assert "\n" in csv_content
    assert "'=HYPERLINK" in csv_content
    assert "'+SUM" in csv_content


def test_remediate_violation_success(importer_app, violation_factory):
    violation = violation_factory(rule_code="VOL_EMAIL_INVALID")
    service = DataQualityViolationService()
    user = User(
        username="remediator",
        email="remediator@example.com",
        password_hash=generate_password_hash("changeme"),
        first_name="Remy",
        last_name="Datafix",
    )
    db.session.add(user)
    db.session.commit()

    edited_payload = dict(violation.staging_row.payload_json or {})
    edited_payload["email"] = "fixed@example.org"
    edited_payload["phone_e164"] = "+15555550123"

    result = service.remediate_violation(
        violation.id,
        edited_payload=edited_payload,
        notes="Adjusted email casing",
        user_id=user.id,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    updated_violation = db.session.get(type(violation), violation.id)
    assert result.status == DataQualityStatus.FIXED
    assert updated_violation.status == DataQualityStatus.FIXED
    assert updated_violation.edited_payload_json["email"] == "fixed@example.org"
    events = updated_violation.remediation_audit_json.get("events", [])
    assert events and events[-1]["outcome"] == "succeeded"

    remediation_run = db.session.get(ImportRun, result.remediation_run_id)
    assert remediation_run is not None
    assert remediation_run.status == ImportRunStatus.SUCCEEDED
    assert remediation_run.metrics_json["remediation"]["outcome"] == "succeeded"

    clean_row = CleanVolunteer.query.filter_by(run_id=remediation_run.id).one()
    assert clean_row.email == "fixed@example.org"
    assert clean_row.core_volunteer_id is not None

    admin_log = AdminLog.query.order_by(AdminLog.id.desc()).first()
    assert admin_log and admin_log.action == "IMPORT_VIOLATION_REMEDIATED"

    # Cleanup inserted records to avoid cross-test contamination
    volunteer = db.session.get(Volunteer, clean_row.core_volunteer_id)
    if volunteer:
        ContactEmail.query.filter_by(contact_id=volunteer.id).delete()
        ContactPhone.query.filter_by(contact_id=volunteer.id).delete()
        db.session.delete(volunteer)
    db.session.delete(clean_row)
    db.session.delete(remediation_run)
    db.session.delete(admin_log)
    db.session.delete(user)
    db.session.commit()


def test_remediate_violation_validation_failure(importer_app, violation_factory):
    violation = violation_factory(rule_code="VOL_EMAIL_INVALID")
    service = DataQualityViolationService()
    user = User(
        username="invalid_fix",
        email="invalid_fix@example.com",
        password_hash=generate_password_hash("changeme"),
        first_name="Frank",
        last_name="Validator",
    )
    db.session.add(user)
    db.session.commit()

    edited_payload = dict(violation.staging_row.payload_json or {})
    edited_payload["email"] = "not-an-email"
    edited_payload.pop("phone", None)
    edited_payload.pop("phone_e164", None)

    with pytest.raises(RemediationValidationError) as excinfo:
        service.remediate_violation(
            violation.id,
            edited_payload=edited_payload,
            notes="Attempted invalid update",
            user_id=user.id,
            ip_address="127.0.0.1",
            user_agent="pytest",
        )
    assert excinfo.value.errors

    updated_violation = db.session.get(type(violation), violation.id)
    assert updated_violation.status == DataQualityStatus.OPEN
    assert updated_violation.edited_payload_json["email"] == "not-an-email"
    audit_events = updated_violation.remediation_audit_json.get("events", [])
    assert audit_events and audit_events[-1]["outcome"] == "validation_failed"

    db.session.delete(user)
    db.session.commit()


def test_remediation_stats_tracks_outcomes(importer_app, violation_factory):
    service = DataQualityViolationService()
    user = User(
        username="stat_user",
        email="stat@example.com",
        password_hash=generate_password_hash("changeme"),
        first_name="Stat",
        last_name="Tracker",
    )
    db.session.add(user)
    db.session.commit()

    success_violation = violation_factory(rule_code="VOL_EMAIL_INVALID")
    success_payload = dict(success_violation.staging_row.payload_json or {})
    success_payload["email"] = "stats@example.org"
    success_payload["phone_e164"] = "+15555550123"
    success_result = service.remediate_violation(
        success_violation.id,
        edited_payload=success_payload,
        notes="Tracking success",
        user_id=user.id,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    failure_violation = violation_factory(rule_code="VOL_EMAIL_INVALID")
    failure_payload = dict(failure_violation.staging_row.payload_json or {})
    failure_payload["email"] = "bad"
    failure_payload.pop("phone", None)
    failure_payload.pop("phone_e164", None)
    with pytest.raises(RemediationValidationError):
        service.remediate_violation(
            failure_violation.id,
            edited_payload=failure_payload,
            notes="Tracking failure",
            user_id=user.id,
            ip_address="127.0.0.1",
            user_agent="pytest",
        )

    stats = service.get_remediation_stats(days=1)
    assert stats.attempts == 2
    assert stats.successes == 1
    assert stats.failures == 1
    assert "email" in stats.field_counts
    assert "VOL_EMAIL_INVALID" in stats.rule_counts

    remediation_run = db.session.get(ImportRun, success_result.remediation_run_id)
    clean_row = CleanVolunteer.query.filter_by(run_id=remediation_run.id).one()
    volunteer = db.session.get(Volunteer, clean_row.core_volunteer_id)
    ContactEmail.query.filter_by(contact_id=volunteer.id).delete()
    ContactPhone.query.filter_by(contact_id=volunteer.id).delete()
    db.session.delete(volunteer)
    db.session.delete(clean_row)
    db.session.delete(remediation_run)
    db.session.delete(user)
    AdminLog.query.delete()
    db.session.commit()


def test_remediate_violation_with_golden_dataset(importer_app, run_factory):
    dataset_path = Path("ops/testdata/importer_golden_dataset_v0/volunteers_invalid.csv")
    with dataset_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        target_row = None
        for row in reader:
            if row["external_id"] == "vol-bad-002":
                target_row = row
                break
    assert target_row is not None

    run = run_factory()
    staging = StagingVolunteer(
        run_id=run.id,
        external_system=target_row["external_system"],
        external_id=target_row["external_id"],
        payload_json=target_row,
        normalized_json={
            "first_name": target_row["first_name"],
            "last_name": target_row["last_name"],
            "email": target_row["email"],
            "phone_e164": target_row["phone"] or "",
        },
    )
    db.session.add(staging)
    db.session.commit()

    violation = DataQualityViolation(
        run_id=run.id,
        staging_volunteer_id=staging.id,
        rule_code="VOL_EMAIL_FORMAT",
        severity=DataQualitySeverity.ERROR,
        status=DataQualityStatus.OPEN,
        message="Email is not in a valid format.",
        details_json={"value": target_row["email"]},
    )
    db.session.add(violation)
    db.session.commit()

    user = User(
        username="golden_tester",
        email="golden@example.com",
        password_hash=generate_password_hash("changeme"),
        first_name="Golden",
        last_name="Tester",
    )
    db.session.add(user)
    db.session.commit()

    service = DataQualityViolationService()
    edited_payload = {
        "first_name": target_row["first_name"],
        "last_name": target_row["last_name"],
        "email": "lucy@example.com",
        "phone": "+15555550100",
        "phone_e164": "+15555550100",
    }
    result = service.remediate_violation(
        violation.id,
        edited_payload=edited_payload,
        notes="Corrected email from golden dataset",
        user_id=user.id,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    assert result.status == DataQualityStatus.FIXED

    remediation_run = db.session.get(ImportRun, result.remediation_run_id)
    clean_row = CleanVolunteer.query.filter_by(run_id=result.remediation_run_id).one()
    volunteer = db.session.get(Volunteer, clean_row.core_volunteer_id)
    ContactEmail.query.filter_by(contact_id=volunteer.id).delete()
    ContactPhone.query.filter_by(contact_id=volunteer.id).delete()
    db.session.delete(volunteer)
    db.session.delete(clean_row)
    db.session.delete(remediation_run)
    db.session.delete(user)
    db.session.delete(violation)
    db.session.delete(staging)
    db.session.delete(run)
    AdminLog.query.filter(AdminLog.action == "IMPORT_VIOLATION_REMEDIATED").delete()
    db.session.commit()

