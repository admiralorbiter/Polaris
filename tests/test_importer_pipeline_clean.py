from flask_app.importer.pipeline.clean import promote_clean_volunteers
from flask_app.models import CleanVolunteer, ImportRun, ImportRunStatus, StagingRecordStatus, StagingVolunteer, db


def _make_import_run() -> ImportRun:
    run = ImportRun(source="csv", adapter="csv", status=ImportRunStatus.PENDING, dry_run=False)
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _make_staging_row(
    run: ImportRun,
    *,
    status: StagingRecordStatus,
    email: str | None,
    sequence_number: int = 1,
) -> StagingVolunteer:
    row = StagingVolunteer(
        run_id=run.id,
        sequence_number=sequence_number,
        source_record_id=f"row-{sequence_number}",
        external_system="csv",
        external_id=f"ext-{sequence_number}",
        payload_json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": email or "",
            "phone": "+14155550101",
        },
        normalized_json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": email or "",
            "phone": "+14155550101",
        },
        checksum="hash-1",
        status=status,
    )
    db.session.add(row)
    db.session.commit()
    return db.session.get(StagingVolunteer, row.id)


def test_promote_clean_volunteers_creates_records(app):
    run = _make_import_run()
    _make_staging_row(run, status=StagingRecordStatus.VALIDATED, email="ada@example.org", sequence_number=1)
    _make_staging_row(
        run,
        status=StagingRecordStatus.QUARANTINED,
        email="quarantine@example.org",
        sequence_number=2,
    )

    summary = promote_clean_volunteers(run, dry_run=False)
    db.session.commit()

    clean_rows = CleanVolunteer.query.filter_by(run_id=run.id).all()
    assert summary.rows_considered == 1
    assert summary.rows_promoted == 1
    assert summary.rows_skipped == 0
    assert len(clean_rows) == 1
    assert clean_rows[0].email == "ada@example.org"

    counts = run.counts_json["clean"]["volunteers"]
    assert counts["rows_promoted"] == 1
    metrics = run.metrics_json["clean"]["volunteers"]
    assert metrics["rows_promoted"] == 1


def test_promote_clean_volunteers_dry_run(app):
    run = _make_import_run()
    _make_staging_row(run, status=StagingRecordStatus.VALIDATED, email="ada@example.org")

    summary = promote_clean_volunteers(run, dry_run=True)
    db.session.commit()

    assert CleanVolunteer.query.count() == 0
    assert summary.rows_promoted == 0
    assert summary.rows_considered == 1
    assert summary.dry_run is True
    assert len(summary.candidates) == 1
    counts = run.counts_json["clean"]["volunteers"]
    assert counts["rows_promoted"] == 0
    assert counts["dry_run"] is True
    metrics = run.metrics_json["clean"]["volunteers"]
    assert metrics["rows_promoted"] == 0

