import io

from flask_app.importer.pipeline import stage_volunteers_from_csv
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus, StagingVolunteer


def _make_csv_stream() -> io.StringIO:
    contents = (
        "first_name,last_name,email,phone\n" "Jane,Doe,jane@example.org,+14155550101\n" "John,Smith,john@example.org,\n"
    )
    stream = io.StringIO(contents)
    stream.seek(0)
    return stream


def _create_import_run(*, dry_run: bool = False) -> ImportRun:
    run = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.PENDING,
        dry_run=dry_run,
    )
    db.session.add(run)
    db.session.commit()
    return ImportRun.query.get(run.id)


def test_stage_volunteers_from_csv_persists_rows(app):
    run = _create_import_run()
    summary = stage_volunteers_from_csv(run, _make_csv_stream(), source_system="csv")
    db.session.commit()

    staged_rows = StagingVolunteer.query.order_by(StagingVolunteer.sequence_number).all()
    assert summary.rows_staged == 2
    assert len(staged_rows) == 2
    assert staged_rows[0].payload_json["first_name"] == "Jane"
    assert staged_rows[1].payload_json["first_name"] == "John"

    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_processed"] == 2
    assert counts["rows_staged"] == 2
    assert counts["rows_skipped_blank"] == 0

    metrics = run.metrics_json["staging"]["volunteers"]
    assert metrics["rows_processed"] == 2
    assert metrics["rows_staged"] == 2
    assert metrics["dry_run"] is False


def test_stage_volunteers_from_csv_dry_run_does_not_write(app):
    run = _create_import_run(dry_run=True)
    summary = stage_volunteers_from_csv(
        run,
        _make_csv_stream(),
        source_system="csv",
        dry_run=True,
    )
    db.session.commit()

    assert summary.rows_staged == 0
    assert StagingVolunteer.query.count() == 0

    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_processed"] == 2
    assert counts["rows_staged"] == 0
    assert counts["dry_run"] is True
