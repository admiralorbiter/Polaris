"""
Admin-facing importer routes for initiating runs and monitoring status.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from flask_login import current_user, login_required

from flask_app.importer.celery_app import DEFAULT_QUEUE_NAME, get_celery_app
from flask_app.importer.pipeline.dq_service import (
    DataQualityViolationService,
    RemediationConflict,
    RemediationNotFound,
    RemediationValidationError,
)
from flask_app.importer.pipeline.run_service import ImportRunService
from flask_app.importer.utils import allowed_file, cleanup_upload, persist_upload, resolve_upload_directory
from flask_app.models import AdminLog, db
from flask_app.models.importer.schema import (
    DataQualitySeverity,
    DataQualityStatus,
    ImportRun,
    ImportRunStatus,
)
from flask_app.utils.importer import is_importer_enabled
from flask_app.utils.permissions import permission_required


admin_importer_blueprint = Blueprint("admin_importer", __name__, url_prefix="/admin/imports")
_run_service = ImportRunService()
_dq_service = DataQualityViolationService()


def _ensure_importer_enabled():
    if not is_importer_enabled(current_app):
        return False
    return True


def _max_upload_bytes() -> int:
    mb_limit = current_app.config.get("IMPORTER_MAX_UPLOAD_MB", 25)
    try:
        return int(mb_limit) * 1024 * 1024
    except (TypeError, ValueError):
        return 25 * 1024 * 1024


def _validate_upload(file_storage) -> None:
    if file_storage is None or file_storage.filename == "":
        raise ValueError("No file uploaded.")
    if not allowed_file(file_storage.filename):
        raise ValueError("Unsupported file type; only CSV is allowed.")

    max_bytes = _max_upload_bytes()
    content_length = getattr(file_storage, "content_length", None) or request.content_length
    if content_length and content_length > max_bytes:
        raise OverflowError("Upload exceeds maximum size limit.")

    # Fall back to checking the actual stream size if we do not have a header.
    if not content_length:
        position = file_storage.stream.tell()
        file_storage.stream.seek(0, 2)  # move to end
        size_bytes = file_storage.stream.tell()
        file_storage.stream.seek(position)
        if size_bytes > max_bytes:
            raise OverflowError("Upload exceeds maximum size limit.")


@admin_importer_blueprint.get("/")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dashboard():
    if not _ensure_importer_enabled():
        return render_template("errors/404.html"), HTTPStatus.NOT_FOUND
    recent_runs_raw = (
        ImportRun.query.order_by(ImportRun.created_at.desc()).limit(25).all()
        if current_app.config.get("IMPORTER_SHOW_RECENT_RUNS", True)
        else []
    )
    # Normalize status values for template rendering (enum.value -> string)
    recent_runs = []
    for run in recent_runs_raw:
        status_value = run.status.value if hasattr(run.status, "value") else str(run.status)
        badge_class = (
            "bg-success"
            if status_value == "succeeded"
            else "bg-danger"
            if status_value in ("failed", "partially_failed")
            else "bg-info"
            if status_value == "running"
            else "bg-secondary"
        )
        # Determine if retry is available: must have stored params and file must exist
        can_retry = False
        if run.ingest_params_json:
            file_path = run.ingest_params_json.get("file_path")
            if file_path:
                from pathlib import Path
                can_retry = Path(file_path).exists()
        recent_runs.append(
            {
                "id": run.id,
                "source": run.source,
                "status_value": status_value,
                "badge_class": badge_class,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "notes": run.notes,
                "can_retry": can_retry,
            }
        )
    return render_template(
        "admin/importer.html",
        recent_runs=recent_runs,
        max_upload_mb=current_app.config.get("IMPORTER_MAX_UPLOAD_MB", 25),
        default_queue=DEFAULT_QUEUE_NAME,
    )


@admin_importer_blueprint.get("/runs/dashboard")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_runs_dashboard_page():
    if not _ensure_importer_enabled():
        return render_template("errors/404.html"), HTTPStatus.NOT_FOUND

    status_options = [status.value for status in ImportRunStatus]
    status_badges = {
        "pending": "warning",
        "running": "info",
        "succeeded": "success",
        "failed": "danger",
        "partially_failed": "secondary",
        "cancelled": "secondary",
    }
    default_page_size = current_app.config.get("IMPORTER_RUNS_PAGE_SIZE_DEFAULT", 25)
    allowed_page_sizes = list(current_app.config.get("IMPORTER_RUNS_PAGE_SIZES", (25, 50, 100)))
    auto_refresh_seconds = current_app.config.get("IMPORTER_RUNS_AUTO_REFRESH_SECONDS", 30)
    sources = _run_service.list_sources()
    if not sources:
        sources = sorted({adapter.name for adapter in current_app.extensions.get("importer", {}).get("active_adapters", ())})

    current_app.logger.info(
        "Importer runs dashboard page rendered",
        extra={
            "user_id": current_user.id,
            "importer_status_options": status_options,
            "importer_allowed_page_sizes": allowed_page_sizes,
        },
    )

    return render_template(
        "importer/runs.html",
        status_options=status_options,
        status_badges=status_badges,
        default_page_size=default_page_size,
        allowed_page_sizes=allowed_page_sizes,
        auto_refresh_seconds=auto_refresh_seconds,
        source_options=sources,
    )


@admin_importer_blueprint.get("/violations")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dq_inbox_page():
    if not _ensure_importer_enabled():
        return render_template("errors/404.html"), HTTPStatus.NOT_FOUND

    severity_options = [severity.value for severity in DataQualitySeverity]
    status_options = [status.value for status in DataQualityStatus]
    rule_code_options = _dq_service.list_rule_codes()

    current_app.logger.info(
        "Importer DQ inbox page rendered",
        extra={
            "user_id": current_user.id,
            "dq_rule_codes_available": len(rule_code_options),
        },
    )

    return render_template(
        "importer/violations.html",
        severity_options=severity_options,
        status_options=status_options,
        rule_code_options=rule_code_options,
    )


@admin_importer_blueprint.post("/violations/<int:violation_id>/remediate")
@login_required
@permission_required("remediate_imports", org_context=False)
def importer_remediate_violation(violation_id: int):
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    payload = request.get_json(silent=True) or {}
    edited_payload = payload.get("payload")
    notes = payload.get("notes")

    if edited_payload is None:
        return jsonify({"error": "Request body must include 'payload'."}), HTTPStatus.BAD_REQUEST

    try:
        result = _dq_service.remediate_violation(
            violation_id,
            edited_payload=edited_payload,
            notes=notes,
            user_id=current_user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
    except RemediationValidationError as exc:
        return (
            jsonify(
                {
                    "status": "validation_failed",
                    "violation_id": violation_id,
                    "errors": exc.errors,
                }
            ),
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    except RemediationConflict as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    except RemediationNotFound:
        return jsonify({"error": f"Violation {violation_id} not found."}), HTTPStatus.NOT_FOUND
    except Exception as exc:  # pragma: no cover - defensive logging path
        current_app.logger.exception(
            "Importer remediation failed",
            extra={"violation_id": violation_id, "user_id": current_user.id},
            exc_info=exc,
        )
        return (
            jsonify({"error": "Unexpected error during remediation; please retry later."}),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    status_value = result.status.value if hasattr(result.status, "value") else str(result.status)
    response = {
        "violation_id": result.violation_id,
        "status": status_value,
        "remediation_run_id": result.remediation_run_id,
        "edited_payload": dict(result.edited_payload),
        "diff": dict(result.diff),
        "clean_contact_id": result.clean_contact_id,
        "clean_volunteer_id": result.clean_volunteer_id,
    }

    return jsonify(response), HTTPStatus.OK


@admin_importer_blueprint.get("/remediation/stats")
@login_required
@permission_required("remediate_imports", org_context=False)
def importer_remediation_stats():
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    days_raw = request.args.get("days", "30")
    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Query parameter 'days' must be an integer."}), HTTPStatus.BAD_REQUEST

    stats = _dq_service.get_remediation_stats(days=days)
    success_rate = (stats.successes / stats.attempts) if stats.attempts else 0.0

    top_fields = sorted(stats.field_counts.items(), key=lambda item: item[1], reverse=True)[:10]
    top_rules = sorted(stats.rule_counts.items(), key=lambda item: item[1], reverse=True)[:10]

    response = {
        "since": stats.since.isoformat(),
        "days": max(1, days),
        "attempts": stats.attempts,
        "successes": stats.successes,
        "failures": stats.failures,
        "success_rate": round(success_rate, 4),
        "top_fields": [{"field": field, "count": count} for field, count in top_fields],
        "top_rules": [{"rule_code": rule, "count": count} for rule, count in top_rules],
    }
    return jsonify(response)


@admin_importer_blueprint.post("/upload")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_upload():
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    file_storage = request.files.get("file")
    try:
        _validate_upload(file_storage)
    except OverflowError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    source = (request.form.get("source") or "csv").lower()
    if source != "csv":
        return (
            jsonify({"error": "Only the CSV adapter is available at this time."}),
            HTTPStatus.BAD_REQUEST,
        )

    stored_path: Path | None = None
    run: ImportRun | None = None
    try:
        stored_path = persist_upload(file_storage, current_app, suffix="csv")

        run = ImportRun(
            source=source,
            adapter=source,
            dry_run=False,
            status=ImportRunStatus.PENDING,
            notes=f"Admin upload by user {current_user.id} ({file_storage.filename})",
            triggered_by_user_id=current_user.id,
            counts_json={},
            metrics_json={},
            ingest_params_json={
                "file_path": str(stored_path),
                "source_system": source,
                "dry_run": False,
                "keep_file": True,  # Retain uploads for retry capability
            },
        )
        db.session.add(run)
        db.session.commit()

        celery_app = get_celery_app(current_app)
        if celery_app is None:
            raise RuntimeError("Importer worker is not configured.")

        async_result = celery_app.send_task(
            "importer.pipeline.ingest_csv",
            kwargs={
                "run_id": run.id,
                "file_path": str(stored_path),
                "dry_run": False,
                "source_system": source,
                "keep_file": True,
            },
        )

        AdminLog.log_action(
            admin_user_id=current_user.id,
            action="IMPORT_RUN_ENQUEUED",
            details=json.dumps(
                {
                    "run_id": run.id,
                    "task_id": async_result.id,
                    "filename": file_storage.filename,
                    "source": source,
                }
            ),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        current_app.logger.info(
            "Admin importer run enqueued",
            extra={
                "importer_run_id": run.id,
                "importer_task_id": async_result.id,
                "importer_source": source,
                "triggered_by_user_id": current_user.id,
            },
        )

        return (
            jsonify(
                {
                    "run_id": run.id,
                    "task_id": async_result.id,
                    "status": "queued",
                    "queue": DEFAULT_QUEUE_NAME,
                }
            ),
            HTTPStatus.ACCEPTED,
        )
    except Exception as exc:
        current_app.logger.exception("Failed to enqueue importer run from admin UI.", exc_info=exc)
        if run is not None:
            db.session.refresh(run)
            run.status = ImportRunStatus.FAILED
            run.error_summary = str(exc)
            db.session.commit()
        if stored_path is not None:
            cleanup_upload(stored_path)
        return (
            jsonify(
                {
                    "error": "Failed to enqueue importer run; please contact an administrator.",
                }
            ),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


@admin_importer_blueprint.get("/<int:run_id>/status")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_run_status(run_id: int):
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND
    run = db.session.get(ImportRun, run_id)
    if run is None:
        return jsonify({"error": f"Import run {run_id} not found."}), HTTPStatus.NOT_FOUND

    payload = {
        "run_id": run.id,
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "source": run.source,
        "dry_run": run.dry_run,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "counts": run.counts_json or {},
        "metrics": run.metrics_json or {},
        "error_summary": run.error_summary,
    }
    return jsonify(payload)


def _retry_import_run_admin(run: ImportRun) -> tuple[str, str]:
    """
    Retry an import run by re-enqueueing it with stored parameters (admin UI helper).

    Returns:
        tuple[str, str]: (task_id, status_message)
    """
    params = run.ingest_params_json
    if not params:
        raise ValueError(
            f"Import run {run.id} cannot be retried: ingest parameters not stored. "
            "This run was created before retry support was added."
        )

    file_path = params.get("file_path")
    if not file_path:
        raise ValueError(f"Import run {run.id} cannot be retried: file_path missing from stored parameters.")

    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        raise ValueError(
            f"Import run {run.id} cannot be retried: file not found at {file_path}. "
            "The upload may have been cleaned up."
        )

    source_system = params.get("source_system", "csv")
    dry_run = params.get("dry_run", False)
    keep_file = params.get("keep_file", True)

    # Reset run state for retry
    run.status = ImportRunStatus.PENDING
    run.started_at = None
    run.finished_at = None
    run.error_summary = None
    run.counts_json = {}
    run.metrics_json = {}
    db.session.commit()

    celery_app = get_celery_app(current_app)
    if celery_app is None:
        raise RuntimeError("Importer worker is not configured; cannot enqueue retry.")

    async_result = celery_app.send_task(
        "importer.pipeline.ingest_csv",
        kwargs={
            "run_id": run.id,
            "file_path": str(path),
            "dry_run": dry_run,
            "source_system": source_system,
            "keep_file": keep_file,
        },
    )

    AdminLog.log_action(
        admin_user_id=current_user.id,
        action="IMPORT_RUN_RETRIED",
        details=json.dumps(
            {
                "run_id": run.id,
                "task_id": async_result.id,
                "source": source_system,
            }
        ),
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )

    current_app.logger.info(
        "Admin importer run retried",
        extra={
            "importer_run_id": run.id,
            "importer_task_id": async_result.id,
            "importer_source": source_system,
            "triggered_by_user_id": current_user.id,
        },
    )

    return async_result.id, "queued"


@admin_importer_blueprint.post("/<int:run_id>/retry")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_run_retry(run_id: int):
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND
    run = db.session.get(ImportRun, run_id)
    if run is None:
        return jsonify({"error": f"Import run {run_id} not found."}), HTTPStatus.NOT_FOUND

    try:
        task_id, status = _retry_import_run_admin(run)
        return (
            jsonify(
                {
                    "run_id": run_id,
                    "task_id": task_id,
                    "status": status,
                    "queue": DEFAULT_QUEUE_NAME,
                }
            ),
            HTTPStatus.ACCEPTED,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.SERVICE_UNAVAILABLE
    except Exception as exc:
        current_app.logger.exception("Failed to retry importer run from admin UI.", exc_info=exc)
        return (
            jsonify(
                {
                    "error": "Failed to retry importer run; please contact an administrator.",
                }
            ),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


@admin_importer_blueprint.get("/<int:run_id>/download")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_run_download(run_id: int):
    if not _ensure_importer_enabled():
        return render_template("errors/404.html"), HTTPStatus.NOT_FOUND

    run = db.session.get(ImportRun, run_id)
    if run is None or not run.ingest_params_json:
        return jsonify({"error": f"Import run {run_id} not found or missing ingest metadata."}), HTTPStatus.NOT_FOUND

    params = run.ingest_params_json
    file_path = params.get("file_path")
    keep_file = params.get("keep_file", False)
    if not keep_file or not file_path:
        return jsonify({"error": f"Import run {run_id} has no retained upload for download."}), HTTPStatus.NOT_FOUND

    path = Path(file_path)
    upload_root = resolve_upload_directory(current_app)
    try:
        resolved_path = path.resolve(strict=False)
        root_resolved = upload_root.resolve(strict=False)
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.warning("Failed to resolve importer download path for run %s: %s", run_id, exc)
        return jsonify({"error": "Unable to locate upload on disk."}), HTTPStatus.NOT_FOUND

    if not resolved_path.exists():
        return jsonify({"error": "Upload file no longer exists on disk."}), HTTPStatus.NOT_FOUND

    try:
        if root_resolved not in resolved_path.parents and resolved_path != root_resolved:
            raise PermissionError("Path escapes upload directory.")
    except PermissionError:
        current_app.logger.error(
            "Importer download path validation failed for run %s: %s not under %s",
            run_id,
            resolved_path,
            root_resolved,
        )
        return jsonify({"error": "Upload file location invalid."}), HTTPStatus.NOT_FOUND

    download_name = f"import_run_{run_id}{resolved_path.suffix or '.csv'}"
    current_app.logger.info(
        "Importer upload download served",
        extra={"importer_run_id": run_id, "download_path": str(resolved_path), "user_id": current_user.id},
    )
    return send_file(resolved_path, as_attachment=True, download_name=download_name)


def register_importer_admin_routes(app):
    """
    Register importer admin routes when the importer feature flag is enabled.
    """

    if not is_importer_enabled(app):
        return

    if admin_importer_blueprint.name in app.blueprints:
        return

    app.register_blueprint(admin_importer_blueprint)

