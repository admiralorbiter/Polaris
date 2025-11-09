from flask_app.importer.pipeline import run_minimal_dq
from flask_app.models.base import db
from flask_app.models.importer.schema import (
    DataQualityViolation,
    ImportRun,
    ImportRunStatus,
    StagingRecordStatus,
    StagingVolunteer,
)


def _create_import_run(*, dry_run: bool = False) -> ImportRun:
    run = ImportRun(
        source="csv",
        adapter="csv",
        dry_run=dry_run,
        status=ImportRunStatus.PENDING,
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _create_staging_row(
    run: ImportRun,
    *,
    payload: dict,
    normalized: dict | None = None,
) -> StagingVolunteer:
    row = StagingVolunteer(
        run_id=run.id,
        sequence_number=1,
        source_record_id="row-1",
        external_system="csv",
        payload_json=payload,
        normalized_json=normalized,
        status=StagingRecordStatus.LANDED,
    )
    db.session.add(row)
    db.session.commit()
    return db.session.get(StagingVolunteer, row.id)


def test_run_minimal_dq_validates_clean_rows(app):
    run = _create_import_run()
    row = _create_staging_row(
        run,
        payload={"first_name": "Ada", "email": "ada@example.org"},
        normalized={"first_name": "Ada", "email": "ada@example.org"},
    )

    summary = run_minimal_dq(run, dry_run=False)
    db.session.commit()

    refreshed_row = db.session.get(StagingVolunteer, row.id)
    assert refreshed_row.status == StagingRecordStatus.VALIDATED
    assert summary.rows_evaluated == 1
    assert summary.rows_validated == 1
    assert summary.rows_quarantined == 0
    assert not summary.rule_counts

    refreshed_run = db.session.get(ImportRun, run.id)
    dq_counts = refreshed_run.counts_json["dq"]["volunteers"]
    assert dq_counts["rows_validated"] == 1
    assert dq_counts["rows_quarantined"] == 0
    assert dq_counts["dry_run"] is False
    dq_metrics = refreshed_run.metrics_json["dq"]["volunteers"]
    assert dq_metrics["rows_validated"] == 1


def test_run_minimal_dq_quarantines_and_logs_violations(app):
    run = _create_import_run()
    row = _create_staging_row(
        run,
        payload={"first_name": "Grace", "last_name": "Hopper"},
        normalized={"first_name": "Grace", "last_name": "Hopper"},
    )

    summary = run_minimal_dq(run, dry_run=False)
    db.session.commit()

    refreshed_row = db.session.get(StagingVolunteer, row.id)
    assert refreshed_row.status == StagingRecordStatus.QUARANTINED
    assert summary.rows_quarantined == 1
    assert summary.rule_counts["VOL_CONTACT_REQUIRED"] == 1

    violations = DataQualityViolation.query.filter_by(run_id=run.id).all()
    assert len(violations) == 1
    assert violations[0].rule_code == "VOL_CONTACT_REQUIRED"
    assert violations[0].severity.name == "ERROR"
    assert violations[0].details_json["fields"] == ["email", "phone"]

    refreshed_run = db.session.get(ImportRun, run.id)
    dq_counts = refreshed_run.counts_json["dq"]["volunteers"]
    assert dq_counts["rows_quarantined"] == 1
    assert dq_counts["rule_counts"]["VOL_CONTACT_REQUIRED"] == 1


def test_run_minimal_dq_dry_run_skips_persistence(app):
    run = _create_import_run(dry_run=True)
    row = _create_staging_row(
        run,
        payload={"first_name": "Alan", "last_name": "Turing"},
        normalized={"first_name": "Alan", "last_name": "Turing"},
    )

    summary = run_minimal_dq(run, dry_run=True)
    db.session.commit()

    refreshed_row = db.session.get(StagingVolunteer, row.id)
    assert refreshed_row.status == StagingRecordStatus.LANDED
    assert DataQualityViolation.query.count() == 0
    assert summary.rows_quarantined == 1
    assert summary.dry_run is True

    refreshed_run = db.session.get(ImportRun, run.id)
    dq_counts = refreshed_run.counts_json["dq"]["volunteers"]
    assert dq_counts["rows_quarantined"] == 0
    assert dq_counts["dry_run"] is True
    dq_metrics = refreshed_run.metrics_json["dq"]["volunteers"]
    assert dq_metrics["rows_quarantined"] == 1

