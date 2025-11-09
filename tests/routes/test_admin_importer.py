from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from flask_app.importer import init_importer
from flask_app.models import AdminLog, db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus
from flask_app.routes.admin_importer import register_importer_admin_routes


def _enable_importer(app, upload_dir: Path) -> None:
    app.config.update(
        IMPORTER_ENABLED=True,
        IMPORTER_ADAPTERS=("csv",),
        IMPORTER_WORKER_ENABLED=True,
        IMPORTER_UPLOAD_DIR=str(upload_dir),
        CELERY_CONFIG={"task_always_eager": True, "task_eager_propagates": True},
    )
    init_importer(app)
    register_importer_admin_routes(app)


def test_importer_admin_page_requires_auth(client):
    response = client.get("/admin/imports/")
    # Route may be unregistered (404) when importer disabled or redirect to login.
    assert response.status_code in {302, 401, 403, 404}


def test_importer_admin_page_renders(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")

    response = client.get("/admin/imports/")
    assert response.status_code == 200
    assert b"Start a New Import Run" in response.data


def test_importer_admin_page_renders_with_runs(logged_in_admin, app, tmp_path):
    """Verify the dashboard renders correctly with import runs present."""
    client, admin_user = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")

    # Create sample runs with different statuses
    from datetime import datetime, timezone

    run1 = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.SUCCEEDED,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        notes="Test run 1",
        triggered_by_user_id=admin_user.id,
    )
    run2 = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        notes="Test run 2",
        triggered_by_user_id=admin_user.id,
    )
    run3 = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.FAILED,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        error_summary="Test error",
        triggered_by_user_id=admin_user.id,
    )
    db.session.add_all([run1, run2, run3])
    db.session.commit()

    response = client.get("/admin/imports/")
    assert response.status_code == 200
    assert b"Start a New Import Run" in response.data
    # Verify status badges are rendered (no template errors)
    assert b"Succeeded" in response.data or b"succeeded" in response.data
    assert b"Running" in response.data or b"running" in response.data
    assert b"Failed" in response.data or b"failed" in response.data
    # Verify run IDs are present
    assert str(run1.id).encode() in response.data
    assert str(run2.id).encode() in response.data
    assert str(run3.id).encode() in response.data


def test_importer_admin_upload_enqueues(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    upload_dir = tmp_path / "uploads"
    _enable_importer(app, upload_dir)

    async_result = Mock()
    async_result.id = "celery-task-789"
    celery_app = Mock()
    celery_app.send_task.return_value = async_result

    payload = BytesIO(b"first_name,last_name,email\nAda,Lovelace,ada@example.org\n")
    with patch("flask_app.routes.admin_importer.get_celery_app", return_value=celery_app):
        response = client.post(
            "/admin/imports/upload",
            data={
                "file": (payload, "volunteers.csv"),
                "source": "csv",
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 202
    data = response.get_json()
    assert data["status"] == "queued"
    assert data["task_id"] == async_result.id
    celery_app.send_task.assert_called_once()

    run = db.session.get(ImportRun, data["run_id"])
    assert run is not None
    assert run.status == ImportRunStatus.PENDING
    assert run.triggered_by_user_id == admin_user.id
    assert run.notes and "volunteers.csv" in run.notes

    # Admin log entry captured
    log_entry = AdminLog.query.order_by(AdminLog.id.desc()).first()
    assert log_entry is not None
    assert log_entry.action == "IMPORT_RUN_ENQUEUED"

    stored_files = list(upload_dir.iterdir())
    assert stored_files, "Upload file should be persisted locally for worker access."


def test_importer_admin_upload_handles_enqueue_failure(logged_in_admin, app, tmp_path):
    client, _ = logged_in_admin
    upload_dir = tmp_path / "uploads"
    _enable_importer(app, upload_dir)

    celery_app = Mock()
    celery_app.send_task.side_effect = RuntimeError("worker unavailable")

    payload = BytesIO(b"first_name,last_name,email\nAda,Lovelace,ada@example.org\n")
    with patch("flask_app.routes.admin_importer.get_celery_app", return_value=celery_app):
        response = client.post(
            "/admin/imports/upload",
            data={"file": (payload, "volunteers.csv"), "source": "csv"},
            content_type="multipart/form-data",
        )

    assert response.status_code == 500
    error_payload = response.get_json()
    assert error_payload["error"]
    run = ImportRun.query.order_by(ImportRun.id.desc()).first()
    assert run is not None
    assert run.status == ImportRunStatus.FAILED
    assert "worker unavailable" in (run.error_summary or "")

    # Upload cleaned up on failure
    assert not any(upload_dir.iterdir())


def test_importer_admin_upload_rejects_non_csv(logged_in_admin, app, tmp_path):
    client, _ = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")

    payload = BytesIO(b"{}")
    response = client.post(
        "/admin/imports/upload",
        data={"file": (payload, "volunteers.json"), "source": "csv"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Unsupported file type; only CSV is allowed."


def test_importer_status_endpoint_returns_payload(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")

    run = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.RUNNING,
        dry_run=False,
        triggered_by_user_id=admin_user.id,
        counts_json={"staging": {"volunteers": {"rows_staged": 2}}},
        metrics_json={"staging": {"volunteers": {"rows_processed": 2}}},
        error_summary=None,
    )
    db.session.add(run)
    db.session.commit()

    response = client.get(f"/admin/imports/{run.id}/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["run_id"] == run.id
    assert payload["status"] == run.status.value
    assert payload["counts"]["staging"]["volunteers"]["rows_staged"] == 2


def test_importer_status_endpoint_requires_valid_run(logged_in_admin, app, tmp_path):
    client, _ = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")

    response = client.get("/admin/imports/999/status")
    assert response.status_code == 404
    assert response.get_json()["error"].startswith("Import run 999")


def test_importer_admin_retry_enqueues(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    upload_dir = tmp_path / "uploads"
    _enable_importer(app, upload_dir)

    # Create a failed run with stored params
    upload_dir.mkdir(parents=True, exist_ok=True)
    csv_file = upload_dir / "test.csv"
    csv_file.write_text("first_name,last_name,email\nAda,Lovelace,ada@example.org\n", encoding="utf-8")

    run = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.FAILED,
        dry_run=False,
        triggered_by_user_id=admin_user.id,
        error_summary="Test failure",
        counts_json={"staging": {"volunteers": {"rows_staged": 0}}},
        metrics_json={},
        ingest_params_json={
            "file_path": str(csv_file),
            "source_system": "csv",
            "dry_run": False,
            "keep_file": True,
        },
    )
    db.session.add(run)
    db.session.commit()

    async_result = Mock()
    async_result.id = "celery-task-retry-456"
    celery_app = Mock()
    celery_app.send_task.return_value = async_result

    with patch("flask_app.routes.admin_importer.get_celery_app", return_value=celery_app):
        response = client.post(f"/admin/imports/{run.id}/retry")

    assert response.status_code == 202
    data = response.get_json()
    assert data["status"] == "queued"
    assert data["task_id"] == async_result.id
    celery_app.send_task.assert_called_once()

    # Verify run was reset
    run = db.session.get(ImportRun, run.id)
    assert run.status == ImportRunStatus.PENDING
    assert run.error_summary is None

    # Admin log entry captured
    log_entry = AdminLog.query.order_by(AdminLog.id.desc()).first()
    assert log_entry is not None
    assert log_entry.action == "IMPORT_RUN_RETRIED"


def test_importer_admin_retry_missing_params(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")

    # Create run without ingest_params_json
    run = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.FAILED,
        dry_run=False,
        triggered_by_user_id=admin_user.id,
        ingest_params_json=None,
    )
    db.session.add(run)
    db.session.commit()

    response = client.post(f"/admin/imports/{run.id}/retry")
    assert response.status_code == 400
    assert "cannot be retried" in response.get_json()["error"]


def test_importer_admin_retry_file_not_found(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")

    # Create run with non-existent file
    run = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.FAILED,
        dry_run=False,
        triggered_by_user_id=admin_user.id,
        ingest_params_json={
            "file_path": str(tmp_path / "nonexistent.csv"),
            "source_system": "csv",
            "dry_run": False,
            "keep_file": True,
        },
    )
    db.session.add(run)
    db.session.commit()

    response = client.post(f"/admin/imports/{run.id}/retry")
    assert response.status_code == 400
    assert "file not found" in response.get_json()["error"]

