import io

from pathlib import Path

from flask_app.importer.pipeline import (
    load_core_volunteers,
    promote_clean_volunteers,
    run_minimal_dq,
    stage_volunteers_from_csv,
)
from flask_app.models.base import db
from flask_app.models.importer.schema import CleanVolunteer, ImportRun, ImportRunStatus, StagingVolunteer


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
    return db.session.get(ImportRun, run.id)


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


def test_full_pipeline_dry_run_with_golden_dataset(app):
    run = _create_import_run(dry_run=True)
    csv_path = Path("ops/testdata/importer_golden_dataset_v0/volunteers_valid.csv")
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        stage_summary = stage_volunteers_from_csv(run, handle, source_system="csv", dry_run=True)
    dq_summary = run_minimal_dq(run, dry_run=True)
    clean_summary = promote_clean_volunteers(run, dry_run=True)
    core_summary = load_core_volunteers(
        run,
        dry_run=True,
        clean_candidates=clean_summary.candidates,
    )
    db.session.commit()

    assert stage_summary.dry_run is True
    assert dq_summary.dry_run is True
    assert clean_summary.dry_run is True
    assert core_summary.dry_run is True
    assert core_summary.rows_inserted == 0
    assert CleanVolunteer.query.count() == 0
    metrics_core = run.metrics_json["core"]["volunteers"]
    assert metrics_core["rows_inserted"] == 0
