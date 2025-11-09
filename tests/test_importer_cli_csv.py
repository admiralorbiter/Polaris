from pathlib import Path

from flask_app.importer import init_importer
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus, StagingVolunteer


def _write_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "volunteers.csv"
    csv_file.write_text(
        "first_name,last_name,email\n" "Ada,Lovelace,ada@example.org\n" "Grace,Hopper,grace@example.org\n",
        encoding="utf-8",
    )
    return csv_file


def _ensure_importer(app):
    app.config.update(
        IMPORTER_ENABLED=True,
        IMPORTER_ADAPTERS=("csv",),
        IMPORTER_WORKER_ENABLED=False,
        CELERY_CONFIG={"task_always_eager": True, "task_eager_propagates": True},
    )
    if "importer" not in app.blueprints:
        init_importer(app)


def test_importer_run_cli_stages_data_inline(app, runner, tmp_path):
    _ensure_importer(app)
    csv_path = _write_csv(tmp_path)

    result = runner.invoke(
        args=[
            "importer",
            "run",
            "--source",
            "csv",
            "--file",
            str(csv_path),
        ],
    )

    assert result.exit_code == 0, result.output

    run = db.session.query(ImportRun).order_by(ImportRun.id.desc()).first()
    assert run is not None
    assert run.status == ImportRunStatus.SUCCEEDED
    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_staged"] == 2

    staged_rows = db.session.query(StagingVolunteer).all()
    assert len(staged_rows) == 2


def test_importer_run_cli_dry_run_skips_writes(app, runner, tmp_path):
    _ensure_importer(app)
    csv_path = _write_csv(tmp_path)

    result = runner.invoke(
        args=[
            "importer",
            "run",
            "--source",
            "csv",
            "--file",
            str(csv_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output

    run = db.session.query(ImportRun).order_by(ImportRun.id.desc()).first()
    assert run is not None
    assert run.status == ImportRunStatus.SUCCEEDED
    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_staged"] == 0
    assert db.session.query(StagingVolunteer).count() == 0
