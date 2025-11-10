from flask_app.importer.pipeline.clean import promote_clean_volunteers
from flask_app.importer.pipeline.load_core import load_core_volunteers
from flask_app.models import (
    ChangeLogEntry,
    CleanVolunteer,
    ContactEmail,
    ContactPhone,
    EmailType,
    ExternalIdMap,
    ImportRun,
    ImportRunStatus,
    StagingRecordStatus,
    StagingVolunteer,
    Volunteer,
    db,
)


def _make_run() -> ImportRun:
    run = ImportRun(source="csv", adapter="csv", status=ImportRunStatus.PENDING, dry_run=False)
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _make_validated_row(
    run: ImportRun,
    *,
    seq: int,
    email: str,
    phone: str | None = None,
    external_id: str | None = None,
) -> StagingVolunteer:
    row = StagingVolunteer(
        run_id=run.id,
        sequence_number=seq,
        source_record_id=f"row-{seq}",
        external_system="csv",
        external_id=external_id or f"ext-{seq}",
        payload_json={
            "first_name": "Test",
            "last_name": f"User{seq}",
            "email": email,
            "phone": phone or "",
        },
        normalized_json={
            "first_name": "Test",
            "last_name": f"User{seq}",
            "email": email,
            "phone": phone or "",
        },
        checksum=f"checksum-{seq}",
        status=StagingRecordStatus.VALIDATED,
    )
    db.session.add(row)
    db.session.commit()
    return db.session.get(StagingVolunteer, row.id)


def test_load_core_volunteers_inserts_contacts(app):
    run = _make_run()
    row = _make_validated_row(run, seq=1, email="core-insert@example.org", phone="+14155550111")

    promote_clean_volunteers(run, dry_run=False)
    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()

    volunteer = Volunteer.query.filter_by(first_name="Test", last_name="User1").one()
    email = (
        db.session.query(ContactEmail)
        .filter(ContactEmail.contact_id == volunteer.id)
        .filter(ContactEmail.email == "core-insert@example.org")
        .one()
    )
    phone = (
        db.session.query(ContactPhone)
        .filter(ContactPhone.contact_id == volunteer.id)
        .filter(ContactPhone.phone_number == "+14155550111")
        .one()
    )

    assert summary.rows_created == 1
    assert summary.rows_skipped_duplicates == 0
    assert row.status == StagingRecordStatus.LOADED
    assert email.is_primary is True
    assert phone.is_primary is True

    counts = run.counts_json["core"]["volunteers"]
    assert counts["rows_created"] == 1
    assert counts["rows_updated"] == 0
    assert counts["rows_skipped_duplicates"] == 0
    assert counts["rows_skipped_no_change"] == 0
    metrics = run.metrics_json["core"]["volunteers"]
    assert metrics["rows_created"] == 1
    assert metrics["rows_updated"] == 0


def test_load_core_volunteers_skips_duplicates(app):
    run = _make_run()
    _make_validated_row(run, seq=1, email="duplicate@example.org", phone=None)
    promote_clean_volunteers(run, dry_run=False)

    existing = Volunteer(first_name="Existing", last_name="Person")
    db.session.add(existing)
    db.session.flush()
    db.session.add(
        ContactEmail(
            contact_id=existing.id,
            email="duplicate@example.org",
            email_type=EmailType.PERSONAL,
            is_primary=True,
            is_verified=True,
        )
    )
    db.session.commit()

    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()

    assert summary.rows_created == 0
    assert summary.rows_skipped_duplicates == 1
    clean_row = CleanVolunteer.query.filter_by(run_id=run.id).one()
    assert clean_row.load_action == "skipped_duplicate"
    assert StagingVolunteer.query.filter_by(run_id=run.id).one().status == StagingRecordStatus.LOADED
    counts = run.counts_json["core"]["volunteers"]
    assert counts["rows_created"] == 0
    assert counts["rows_updated"] == 0
    assert counts["rows_skipped_duplicates"] == 1


def test_load_core_volunteers_dry_run(app):
    run = _make_run()
    _make_validated_row(run, seq=1, email="dry-run@example.org", phone=None)
    clean_summary = promote_clean_volunteers(run, dry_run=True)

    summary = load_core_volunteers(
        run,
        dry_run=True,
        clean_candidates=clean_summary.candidates,
    )
    db.session.commit()

    assert summary.rows_processed == 1
    assert summary.rows_created == 0
    assert summary.rows_updated == 0
    assert Volunteer.query.count() == 0
    counts = run.counts_json["core"]["volunteers"]
    assert counts["rows_created"] == 0
    assert counts["rows_updated"] == 0
    assert counts["dry_run"] is True
    metrics_core = run.metrics_json["core"]["volunteers"]
    assert metrics_core["rows_created"] == 1
    assert metrics_core["rows_updated"] == 0


def test_load_core_volunteers_updates_existing_contact(app):
    run_initial = _make_run()
    shared_external_id = "shared-ext-1"
    _make_validated_row(run_initial, seq=1, email="initial@example.org", phone=None, external_id=shared_external_id)
    promote_clean_volunteers(run_initial, dry_run=False)
    load_core_volunteers(run_initial, dry_run=False)
    db.session.commit()

    volunteer = Volunteer.query.filter_by(last_name="User1").one()
    id_map = ExternalIdMap.query.filter_by(external_id=shared_external_id).one()
    assert id_map.entity_id == volunteer.id

    run_update = _make_run()
    _make_validated_row(
        run_update,
        seq=2,
        email="updated@example.org",
        phone="+14155550199",
        external_id=shared_external_id,
    )
    promote_clean_volunteers(run_update, dry_run=False)
    summary = load_core_volunteers(run_update, dry_run=False)
    db.session.commit()
    db.session.refresh(run_update)

    primary_email = ContactEmail.query.filter_by(contact_id=volunteer.id, is_primary=True).one()
    primary_phone = ContactPhone.query.filter_by(contact_id=volunteer.id, is_primary=True).one()
    clean_row = CleanVolunteer.query.filter_by(run_id=run_update.id).one()
    counts_update = run_update.counts_json["core"]["volunteers"]
    metrics_update = run_update.metrics_json["core"]["volunteers"]

    assert summary.rows_updated == 1
    assert summary.rows_created == 0
    assert summary.rows_skipped_no_change == 0
    assert clean_row.load_action == "updated"
    assert primary_email.email == "updated@example.org"
    assert primary_phone.phone_number == "+14155550199"
    assert counts_update["rows_updated"] == 1
    assert counts_update["rows_created"] == 0
    assert metrics_update["rows_updated"] == 1

    change_entries = ChangeLogEntry.query.filter_by(run_id=run_update.id).all()
    changed_fields = {entry.field_name for entry in change_entries}
    assert "email" in changed_fields
    assert "phone_e164" in changed_fields


def test_load_core_volunteers_reactivates_soft_deleted_mapping(app):
    run_initial = _make_run()
    shared_external_id = "shared-ext-2"
    _make_validated_row(run_initial, seq=1, email="reactivate@example.org", phone=None, external_id=shared_external_id)
    promote_clean_volunteers(run_initial, dry_run=False)
    load_core_volunteers(run_initial, dry_run=False)
    db.session.commit()

    id_map = ExternalIdMap.query.filter_by(external_id=shared_external_id).one()
    id_map.soft_delete(reason="Removed upstream")
    db.session.commit()

    assert not id_map.is_active
    assert id_map.deactivated_at is not None

    run_reactivate = _make_run()
    _make_validated_row(
        run_reactivate,
        seq=2,
        email="reactivate@example.org",
        phone=None,
        external_id=shared_external_id,
    )
    promote_clean_volunteers(run_reactivate, dry_run=False)
    summary = load_core_volunteers(run_reactivate, dry_run=False)
    db.session.commit()
    db.session.refresh(run_reactivate)

    refreshed_map = ExternalIdMap.query.filter_by(external_id=shared_external_id).one()
    clean_row = CleanVolunteer.query.filter_by(run_id=run_reactivate.id).one()
    counts_reactivate = run_reactivate.counts_json["core"]["volunteers"]

    assert summary.rows_reactivated == 1
    assert summary.rows_skipped_no_change >= 0
    assert refreshed_map.is_active
    assert refreshed_map.deactivated_at is None
    assert refreshed_map.upstream_deleted_reason is None
    assert clean_row.load_action == "reactivated"
    assert counts_reactivate["rows_reactivated"] == 1


def test_load_core_volunteers_flags_missing_external_id(app):
    run = _make_run()
    row = _make_validated_row(run, seq=1, email="no-ext@example.org", phone=None, external_id=None)
    # Null out external_id after creation to simulate missing identifier.
    row.external_id = None
    db.session.commit()

    promote_clean_volunteers(run, dry_run=False)
    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()

    clean_row = CleanVolunteer.query.filter_by(run_id=run.id).one()
    staging_row = StagingVolunteer.query.filter_by(run_id=run.id).one()

    assert summary.rows_missing_external_id == 1
    assert clean_row.load_action == "error_missing_external_id"
    assert staging_row.status == StagingRecordStatus.QUARANTINED
    assert "external_id" in (staging_row.last_error or "").lower()
