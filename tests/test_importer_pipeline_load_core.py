from flask_app.importer.pipeline.clean import promote_clean_volunteers
from flask_app.importer.pipeline.load_core import load_core_volunteers
from flask_app.models import (
    CleanVolunteer,
    ContactEmail,
    ContactPhone,
    EmailType,
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


def _make_validated_row(run: ImportRun, *, seq: int, email: str, phone: str | None = None) -> StagingVolunteer:
    row = StagingVolunteer(
        run_id=run.id,
        sequence_number=seq,
        source_record_id=f"row-{seq}",
        external_system="csv",
        external_id=f"ext-{seq}",
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

    assert summary.rows_inserted == 1
    assert summary.rows_skipped_duplicates == 0
    assert row.status == StagingRecordStatus.LOADED
    assert email.is_primary is True
    assert phone.is_primary is True

    counts = run.counts_json["core"]["volunteers"]
    assert counts["rows_inserted"] == 1
    metrics = run.metrics_json["core"]["volunteers"]
    assert metrics["rows_inserted"] == 1


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

    assert summary.rows_inserted == 0
    assert summary.rows_skipped_duplicates == 1
    clean_row = CleanVolunteer.query.filter_by(run_id=run.id).one()
    assert clean_row.load_action == "skipped_duplicate"
    assert StagingVolunteer.query.filter_by(run_id=run.id).one().status == StagingRecordStatus.LOADED
    counts = run.counts_json["core"]["volunteers"]
    assert counts["rows_inserted"] == 0
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
    assert summary.rows_inserted == 0
    assert Volunteer.query.count() == 0
    counts = run.counts_json["core"]["volunteers"]
    assert counts["rows_inserted"] == 0
    assert counts["dry_run"] is True

