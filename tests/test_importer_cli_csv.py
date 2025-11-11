import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from flask_app.importer import init_importer
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus, StagingVolunteer


def _write_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "volunteers.csv"
    csv_file.write_text(
        "external_id,first_name,last_name,email\n"
        "vol-1,Ada,Lovelace,ada@example.org\n"
        "vol-2,Grace,Hopper,grace@example.org\n",
        encoding="utf-8",
    )
    return csv_file


def _ensure_importer(app, **overrides):
    config = {
        "IMPORTER_ENABLED": True,
        "IMPORTER_ADAPTERS": ("csv",),
        "IMPORTER_WORKER_ENABLED": True,
        "CELERY_CONFIG": {"task_always_eager": True, "task_eager_propagates": True},
    }
    config.update(overrides)
    app.config.update(config)
    if "importer" not in app.blueprints:
        init_importer(app)


def test_importer_run_cli_queues_by_default(app, runner, tmp_path):
    _ensure_importer(app)
    csv_path = _write_csv(tmp_path)

    async_result = Mock()
    async_result.id = "celery-task-123"
    celery_app = Mock()
    celery_app.send_task.return_value = async_result

    with patch("flask_app.importer.cli._resolve_celery", return_value=celery_app):
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
    payload = json.loads(result.output.strip())
    assert payload["status"] == "queued"
    assert payload["task_id"] == async_result.id

    run = db.session.get(ImportRun, payload["run_id"])
    assert run is not None
    assert run.status == ImportRunStatus.PENDING
    assert run.dry_run is False
    assert run.adapter_health_json is not None
    assert "csv" in run.adapter_health_json


def test_importer_run_cli_summary_json_requires_inline(app, runner, tmp_path):
    _ensure_importer(app)
    csv_path = _write_csv(tmp_path)

    with patch("flask_app.importer.cli._resolve_celery") as mock_resolve:
        # ensure we don't attempt to resolve Celery when validation fails
        result = runner.invoke(
            args=[
                "importer",
                "run",
                "--source",
                "csv",
                "--file",
                str(csv_path),
                "--summary-json",
            ],
        )

    assert result.exit_code != 0
    assert "--summary-json is only available for --inline runs" in result.output
    mock_resolve.assert_not_called()


def test_importer_run_cli_enqueues_failure_marks_run_failed(app, runner, tmp_path):
    _ensure_importer(app)
    csv_path = _write_csv(tmp_path)

    celery_app = Mock()
    celery_app.send_task.side_effect = RuntimeError("celery unavailable")

    with patch("flask_app.importer.cli._resolve_celery", return_value=celery_app):
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

    assert result.exit_code != 0
    assert "Failed to enqueue importer run" in result.output

    run = db.session.query(ImportRun).order_by(ImportRun.id.desc()).first()
    assert run is not None
    assert run.status == ImportRunStatus.FAILED
    assert "celery unavailable" in (run.error_summary or "")
    assert run.finished_at is not None


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
            "--inline",
        ],
    )

    assert result.exit_code == 0, result.output

    run = db.session.query(ImportRun).order_by(ImportRun.id.desc()).first()
    assert run is not None
    assert run.status == ImportRunStatus.SUCCEEDED
    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_staged"] == 2
    dq_counts = run.counts_json["dq"]["volunteers"]
    assert dq_counts["rows_validated"] == 2
    assert dq_counts["rows_quarantined"] == 0
    assert dq_counts["rule_counts"] == {}
    clean_counts = run.counts_json["clean"]["volunteers"]
    assert clean_counts["rows_promoted"] == 2
    core_counts = run.counts_json["core"]["volunteers"]
    assert core_counts["rows_created"] == 2
    assert core_counts["rows_updated"] == 0
    assert core_counts["rows_skipped_duplicates"] == 0

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
            "--inline",
        ],
    )

    assert result.exit_code == 0, result.output

    run = db.session.query(ImportRun).order_by(ImportRun.id.desc()).first()
    assert run is not None
    assert run.status == ImportRunStatus.SUCCEEDED
    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_staged"] == 0
    dq_counts = run.counts_json["dq"]["volunteers"]
    assert dq_counts["rows_validated"] == 0
    assert dq_counts["rows_quarantined"] == 0
    assert dq_counts["dry_run"] is True
    dq_metrics = run.metrics_json["dq"]["volunteers"]
    assert dq_metrics["rows_validated"] == 2
    clean_counts = run.counts_json["clean"]["volunteers"]
    assert clean_counts["rows_promoted"] == 0
    assert clean_counts["dry_run"] is True
    core_counts = run.counts_json["core"]["volunteers"]
    assert core_counts["rows_created"] == 0
    assert core_counts["rows_updated"] == 0
    assert core_counts["dry_run"] is True
    assert db.session.query(StagingVolunteer).count() == 0


def test_importer_run_cli_summary_json(app, runner, tmp_path):
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
            "--inline",
            "--summary-json",
        ],
    )

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    json_start = next(i for i, line in enumerate(lines) if line.strip().startswith("{"))
    summary_payload = json.loads("\n".join(lines[json_start:]))
    assert summary_payload["core"]["rows_created"] == 2
    assert summary_payload["core"]["rows_updated"] == 0
    assert summary_payload["core"]["rows_skipped_duplicates"] == 0


def test_importer_cleanup_uploads_removes_stale_files(app, runner, tmp_path):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stale_file = uploads_dir / "stale.csv"
    stale_file.write_text("stale-data", encoding="utf-8")
    # Make file appear old
    old_timestamp = 0
    os.utime(stale_file, (old_timestamp, old_timestamp))

    _ensure_importer(app, IMPORTER_UPLOAD_DIR=str(uploads_dir))

    result = runner.invoke(
        args=[
            "importer",
            "cleanup-uploads",
            "--max-age-hours",
            "1",
        ]
    )

    assert result.exit_code == 0, result.output
    assert not stale_file.exists()


def test_importer_retry_cli_success(app, runner, tmp_path):
    _ensure_importer(app)
    csv_path = _write_csv(tmp_path)

    # Create initial run
    async_result = Mock()
    async_result.id = "celery-task-retry-123"
    celery_app = Mock()
    celery_app.send_task.return_value = async_result

    with patch("flask_app.importer.cli._resolve_celery", return_value=celery_app):
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

    assert result.exit_code == 0
    initial_payload = json.loads(result.output.strip())
    run_id = initial_payload["run_id"]

    # Mark run as failed
    run = db.session.get(ImportRun, run_id)
    run.status = ImportRunStatus.FAILED
    run.error_summary = "Test failure"
    db.session.commit()

    # Retry the run
    with patch("flask_app.importer.cli.get_celery_app", return_value=celery_app):
        result = runner.invoke(
            args=[
                "importer",
                "retry",
                "--run-id",
                str(run_id),
            ],
        )

    assert result.exit_code == 0, result.output
    retry_payload = json.loads(result.output.strip())
    assert retry_payload["run_id"] == run_id
    assert retry_payload["status"] == "queued"
    assert retry_payload["task_id"] == async_result.id

    # Verify run was reset
    run = db.session.get(ImportRun, run_id)
    assert run.status == ImportRunStatus.PENDING
    assert run.error_summary is None
    assert run.started_at is None
    assert run.finished_at is None


def test_importer_retry_cli_missing_params(app, runner, tmp_path):
    _ensure_importer(app)

    # Create run without ingest_params_json (old format)
    run = ImportRun(
        source="csv",
        adapter="csv",
        dry_run=False,
        status=ImportRunStatus.FAILED,
        notes="Old format run",
        counts_json={},
        metrics_json={},
        ingest_params_json=None,  # Missing params
    )
    db.session.add(run)
    db.session.commit()

    result = runner.invoke(
        args=[
            "importer",
            "retry",
            "--run-id",
            str(run.id),
        ],
    )

    assert result.exit_code != 0
    assert "cannot be retried" in result.output
    assert "ingest parameters not stored" in result.output


def test_importer_retry_cli_file_not_found(app, runner, tmp_path):
    _ensure_importer(app)

    # Create run with non-existent file path
    run = ImportRun(
        source="csv",
        adapter="csv",
        dry_run=False,
        status=ImportRunStatus.FAILED,
        notes="Missing file run",
        counts_json={},
        metrics_json={},
        ingest_params_json={
            "file_path": str(tmp_path / "nonexistent.csv"),
            "source_system": "csv",
            "dry_run": False,
            "keep_file": False,
        },
    )
    db.session.add(run)
    db.session.commit()

    result = runner.invoke(
        args=[
            "importer",
            "retry",
            "--run-id",
            str(run.id),
        ],
    )

    assert result.exit_code != 0
    assert "cannot be retried" in result.output
    assert "file not found" in result.output
