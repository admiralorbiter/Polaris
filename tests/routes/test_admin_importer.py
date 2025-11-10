from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from flask_app.importer import init_importer
from flask_app.models import AdminLog, ContactEmail, ContactPhone, Volunteer, db
from flask_app.models.importer.schema import (
    CleanVolunteer,
    DataQualitySeverity,
    DataQualityStatus,
    DataQualityViolation,
    ImportRun,
    ImportRunStatus,
    StagingVolunteer,
)
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


def test_importer_admin_upload_dry_run(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    upload_dir = tmp_path / "uploads"
    _enable_importer(app, upload_dir)

    async_result = Mock()
    async_result.id = "celery-task-dry-run"
    celery_app = Mock()
    celery_app.send_task.return_value = async_result

    payload = BytesIO(b"first_name,last_name,email\nAda,Lovelace,ada@example.org\n")
    with patch("flask_app.routes.admin_importer.get_celery_app", return_value=celery_app), patch(
        "flask_app.routes.admin_importer.ImporterMonitoring.record_run_enqueued"
    ) as record_metric:
        response = client.post(
            "/admin/imports/upload",
            data={"file": (payload, "volunteers.csv"), "source": "csv", "dry_run": "1"},
            content_type="multipart/form-data",
        )

    assert response.status_code == 202
    data = response.get_json()
    run = db.session.get(ImportRun, data["run_id"])
    assert run is not None and run.dry_run is True
    assert run.ingest_params_json["dry_run"] is True
    celery_app.send_task.assert_called_once()
    sent_kwargs = celery_app.send_task.call_args.kwargs["kwargs"]
    assert sent_kwargs["dry_run"] is True

    log_entry = AdminLog.query.order_by(AdminLog.id.desc()).first()
    details = json.loads(log_entry.details)
    assert details["dry_run"] is True
    record_metric.assert_called_once_with(user_id=admin_user.id, dry_run=True)


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


def test_importer_admin_retry_preserves_dry_run(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    upload_dir = tmp_path / "uploads"
    _enable_importer(app, upload_dir)

    upload_dir.mkdir(parents=True, exist_ok=True)
    csv_file = upload_dir / "dry_test.csv"
    csv_file.write_text("first_name,last_name,email\nAda,Lovelace,ada@example.org\n", encoding="utf-8")

    run = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.FAILED,
        dry_run=False,
        triggered_by_user_id=admin_user.id,
        counts_json={},
        metrics_json={},
        ingest_params_json={
            "file_path": str(csv_file),
            "source_system": "csv",
            "dry_run": True,
            "keep_file": True,
        },
    )
    db.session.add(run)
    db.session.commit()

    async_result = Mock()
    async_result.id = "celery-task-retry-dry-run"
    celery_app = Mock()
    celery_app.send_task.return_value = async_result

    with patch("flask_app.routes.admin_importer.get_celery_app", return_value=celery_app), patch(
        "flask_app.routes.admin_importer.ImporterMonitoring.record_run_enqueued"
    ) as record_metric:
        response = client.post(f"/admin/imports/{run.id}/retry")

    assert response.status_code == 202
    db.session.refresh(run)
    assert run.dry_run is True
    celery_app.send_task.assert_called_once()
    sent_kwargs = celery_app.send_task.call_args.kwargs["kwargs"]
    assert sent_kwargs["dry_run"] is True

    log_entry = AdminLog.query.order_by(AdminLog.id.desc()).first()
    details = json.loads(log_entry.details)
    assert details["dry_run"] is True
    record_metric.assert_called_once_with(user_id=admin_user.id, dry_run=True)


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


def _create_open_violation(admin_user):
    run = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.FAILED,
        triggered_by_user_id=admin_user.id,
        notes="Original failed import",
    )
    db.session.add(run)
    db.session.commit()

    external_id = f"route-ext-{run.id}"
    staging = StagingVolunteer(
        run_id=run.id,
        sequence_number=1,
        source_record_id="row-1",
        external_system="csv",
        external_id=external_id,
        payload_json={
            "first_name": "Alice",
            "last_name": "Example",
            "email": "alice@example.org",
            "phone": "+15555550123",
            "external_id": external_id,
        },
        normalized_json={
            "first_name": "Alice",
            "last_name": "Example",
            "email": "alice@example.org",
            "phone_e164": "+15555550123",
            "external_id": external_id,
        },
    )
    db.session.add(staging)
    db.session.commit()

    violation = DataQualityViolation(
        run_id=run.id,
        staging_volunteer_id=staging.id,
        rule_code="VOL_EMAIL_INVALID",
        severity=DataQualitySeverity.ERROR,
        status=DataQualityStatus.OPEN,
        message="Email invalid",
        details_json={"field": "email"},
    )
    db.session.add(violation)
    db.session.commit()
    return run, staging, violation


def _cleanup_remediation_artifacts(run_ids):
    for run_id in run_ids:
        remediation_run = db.session.get(ImportRun, run_id)
        if remediation_run is None:
            continue
        clean_rows = CleanVolunteer.query.filter_by(run_id=run_id).all()
        for clean_row in clean_rows:
            volunteer = db.session.get(Volunteer, clean_row.core_volunteer_id)
            if volunteer:
                ContactEmail.query.filter_by(contact_id=volunteer.id).delete()
                ContactPhone.query.filter_by(contact_id=volunteer.id).delete()
                db.session.delete(volunteer)
            db.session.delete(clean_row)
        db.session.delete(remediation_run)
    AdminLog.query.filter(AdminLog.action == "IMPORT_VIOLATION_REMEDIATED").delete()
    db.session.commit()


def test_importer_admin_remediate_violation_success(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")
    original_run, staging, violation = _create_open_violation(admin_user)

    response = client.post(
        f"/admin/imports/violations/{violation.id}/remediate",
        json={
            "payload": {
                "first_name": "Alice",
                "last_name": "Example",
                "email": "routefix@example.org",
                "phone_e164": "+15555550123",
            },
            "notes": "Route-based remediation",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "fixed"
    db.session.refresh(violation)
    assert violation.status == DataQualityStatus.FIXED

    remediation_run_id = payload["remediation_run_id"]
    remediation_run = db.session.get(ImportRun, remediation_run_id)
    assert remediation_run is not None
    assert remediation_run.status == ImportRunStatus.SUCCEEDED
    clean_row = CleanVolunteer.query.filter_by(run_id=remediation_run_id).one()
    assert clean_row.email == "routefix@example.org"

    _cleanup_remediation_artifacts([remediation_run_id])
    db.session.delete(violation)
    db.session.delete(staging)
    db.session.delete(original_run)
    db.session.commit()


def test_importer_admin_remediate_violation_validation_error(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")
    original_run, staging, violation = _create_open_violation(admin_user)

    response = client.post(
        f"/admin/imports/violations/{violation.id}/remediate",
        json={
            "payload": {
                "first_name": "Alice",
                "last_name": "Example",
                "email": "invalid",
            },
            "notes": "Invalid payload",
        },
    )
    assert response.status_code == 422
    data = response.get_json()
    assert data["status"] == "validation_failed"
    assert data["errors"]
    db.session.refresh(violation)
    assert violation.status == DataQualityStatus.OPEN

    db.session.delete(violation)
    db.session.delete(staging)
    db.session.delete(original_run)
    db.session.commit()


def test_importer_admin_remediation_stats_endpoint(logged_in_admin, app, tmp_path):
    client, admin_user = logged_in_admin
    _enable_importer(app, tmp_path / "uploads")
    original_run, staging, violation = _create_open_violation(admin_user)

    success_response = client.post(
        f"/admin/imports/violations/{violation.id}/remediate",
        json={
            "payload": {
                "first_name": "Alice",
                "last_name": "Example",
                "email": "stats@example.org",
                "phone_e164": "+15555550123",
            },
            "notes": "Stats success",
        },
    )
    assert success_response.status_code == 200
    remediation_run_id = success_response.get_json()["remediation_run_id"]

    second_run, second_staging, second_violation = _create_open_violation(admin_user)
    failure_response = client.post(
        f"/admin/imports/violations/{second_violation.id}/remediate",
        json={
            "payload": {
                "first_name": "Alice",
                "last_name": "Example",
                "email": "bad",
            },
            "notes": "Stats failure",
        },
    )
    assert failure_response.status_code == 422

    stats_response = client.get("/admin/imports/remediation/stats")
    assert stats_response.status_code == 200
    stats = stats_response.get_json()
    assert stats["attempts"] >= 2
    assert stats["successes"] >= 1
    assert stats["failures"] >= 1

    _cleanup_remediation_artifacts([remediation_run_id])
    for obj in (violation, staging, original_run, second_violation, second_staging, second_run):
        db.session.delete(obj)
    db.session.commit()
