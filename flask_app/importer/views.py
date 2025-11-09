"""
Importer blueprint endpoints for health, runs dashboard APIs, and related helpers.
"""

from __future__ import annotations

import time
from http import HTTPStatus

from celery.exceptions import TimeoutError as CeleryTimeoutError
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user
from sqlalchemy.exc import NoResultFound

from config.monitoring import ImporterMonitoring
from flask_app.importer.pipeline.run_service import ImportRunService, RunFilters
from flask_app.utils.importer import is_importer_enabled
from flask_app.utils.permissions import has_permission

from .celery_app import DEFAULT_QUEUE_NAME, get_celery_app
from .registry import AdapterDescriptor

importer_blueprint = Blueprint("importer", __name__, url_prefix="/importer")


def _serialize_adapter(adapter: AdapterDescriptor) -> dict:
    return {
        "name": adapter.name,
        "title": adapter.title,
        "summary": adapter.summary,
        "optional_dependencies": list(adapter.optional_dependencies),
    }


@importer_blueprint.get("/health")
def importer_healthcheck():
    """
    Lightweight health endpoint proving the importer blueprint mounted correctly.
    """
    importer_state = current_app.extensions.get("importer", {})
    adapters = importer_state.get("active_adapters", ())
    return (
        jsonify(
            {
                "status": "ok",
                "enabled": importer_state.get("enabled", False),
                "adapters": [_serialize_adapter(adapter) for adapter in adapters],
            }
        ),
        200,
    )


@importer_blueprint.get("/worker_health")
def importer_worker_health():
    """
    Validate importer worker availability via the heartbeat task.
    """
    importer_state = current_app.extensions.get("importer", {})
    enabled = importer_state.get("enabled", False)
    worker_enabled = importer_state.get("worker_enabled", False)
    timeout_seconds = float(request.args.get("timeout", 5))

    payload = {
        "importer_enabled": enabled,
        "worker_enabled": worker_enabled,
        "queue": DEFAULT_QUEUE_NAME,
        "timeout_seconds": timeout_seconds,
    }

    if not enabled:
        payload["status"] = "disabled"
        return jsonify(payload), 200

    if not worker_enabled:
        payload["status"] = "disabled"
        payload["message"] = "Worker flag disabled; start the worker or set IMPORTER_WORKER_ENABLED=true."
        return jsonify(payload), 200

    celery_app = get_celery_app(current_app)
    if celery_app is None:
        payload["status"] = "error"
        payload["error"] = "celery_app_unavailable"
        return jsonify(payload), 500

    task = celery_app.tasks.get("importer.healthcheck")
    if task is None:
        payload["status"] = "error"
        payload["error"] = "heartbeat_task_missing"
        return jsonify(payload), 500

    result = task.apply_async()
    try:
        payload["status"] = "ok"
        payload["heartbeat"] = result.get(timeout=timeout_seconds)
        return jsonify(payload), 200
    except CeleryTimeoutError:
        payload["status"] = "timeout"
        return jsonify(payload), 504
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("Importer worker health check failed.", exc_info=exc)
        payload["status"] = "error"
        payload["error"] = str(exc)
        return jsonify(payload), 500


_run_service = ImportRunService()


def _json_error(message: str, status: HTTPStatus):
    return jsonify({"error": message}), status


def _ensure_importer_enabled_api():
    if not is_importer_enabled(current_app):
        return _json_error("Importer is disabled.", HTTPStatus.NOT_FOUND)
    return None


def _ensure_authenticated_api():
    if not current_user.is_authenticated:
        return _json_error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    return None


def _ensure_manage_imports_permission():
    if not has_permission(current_user, "manage_imports"):
        return _json_error("Missing manage_imports permission.", HTTPStatus.FORBIDDEN)
    return None


def _parse_filters():
    raw = request.args

    status_query = _split_csv(raw.get("status"))
    source_query = _split_csv(raw.get("source"))
    try:
        filters = RunFilters.coerce(
            page=raw.get("page"),
            page_size=raw.get("per_page") or raw.get("page_size"),
            sort=raw.get("sort"),
            statuses=status_query,
            sources=source_query,
            search=raw.get("search"),
            started_from=raw.get("started_from"),
            started_to=raw.get("started_to"),
            include_dry_runs=raw.get("include_dry_runs"),
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return filters


def _serialize_summary(summary):
    return {
        "id": summary.id,
        "run_id": summary.id,
        "source": summary.source,
        "adapter": summary.adapter,
        "status": summary.status,
        "dry_run": summary.dry_run,
        "started_at": summary.started_at.isoformat() if summary.started_at else None,
        "finished_at": summary.finished_at.isoformat() if summary.finished_at else None,
        "duration_seconds": summary.duration_seconds,
        "rows_staged": summary.rows_staged,
        "rows_validated": summary.rows_validated,
        "rows_quarantined": summary.rows_quarantined,
        "rows_inserted": summary.rows_inserted,
        "rows_skipped_duplicates": summary.rows_skipped_duplicates,
        "triggered_by": summary.triggered_by,
        "can_retry": summary.can_retry,
        "counts_digest": summary.counts_digest,
    }


def _serialize_detail(run, *, summary):
    return {
        "id": run.id,
        "run_id": run.id,
        "source": run.source,
        "adapter": run.adapter,
        "status": summary.status,
        "dry_run": run.dry_run,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": summary.duration_seconds,
        "counts_json": run.counts_json or {},
        "metrics_json": run.metrics_json or {},
        "counts_digest": summary.counts_digest,
        "error_summary": run.error_summary,
        "notes": run.notes,
        "anomaly_flags": run.anomaly_flags or {},
        "ingest_params": run.ingest_params_json or {},
        "triggered_by": summary.triggered_by,
        "retry_available": summary.can_retry,
        "download_available": summary.can_retry,
    }


def _split_csv(value: str | None):
    if value in (None, "", ()):
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(v for v in value if v)
    return tuple(token.strip() for token in value.split(",") if token.strip())


@importer_blueprint.get("/runs")
def importer_runs_list():
    enabled_response = _ensure_importer_enabled_api()
    if enabled_response:
        return enabled_response

    auth_response = _ensure_authenticated_api()
    if auth_response:
        return auth_response

    permission_response = _ensure_manage_imports_permission()
    if permission_response:
        return permission_response

    try:
        filters = _parse_filters()
    except ValueError as exc:
        ImporterMonitoring.record_runs_list(duration_seconds=0.0, status="invalid_request", result_count=0)
        return _json_error(str(exc), HTTPStatus.BAD_REQUEST)

    start_time = time.perf_counter()
    try:
        result = _run_service.list_runs(filters)
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("Importer runs list failed.", exc_info=exc)
        ImporterMonitoring.record_runs_list(duration_seconds=time.perf_counter() - start_time, status="error", result_count=0)
        return _json_error("Failed to load runs.", HTTPStatus.INTERNAL_SERVER_ERROR)

    duration = time.perf_counter() - start_time
    ImporterMonitoring.record_runs_list(duration_seconds=duration, status="success", result_count=len(result.items))

    _run_service.record_audit_view(
        current_user.id,
        run_id=None,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )

    response_payload = {
        "runs": [_serialize_summary(item) for item in result.items],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "total_pages": result.total_pages,
        "filters": {
            "page": filters.page,
            "page_size": filters.page_size,
            "sort": filters.sort,
            "statuses": [status.value for status in filters.statuses],
            "sources": list(filters.sources),
            "search": filters.search,
            "started_from": filters.started_from.isoformat() if filters.started_from else None,
            "started_to": filters.started_to.isoformat() if filters.started_to else None,
            "include_dry_runs": filters.include_dry_runs,
        },
    }

    current_app.logger.info(
        "Importer runs list retrieved",
        extra={
            "importer_run_count": len(result.items),
            "importer_total_runs": result.total,
            "importer_filters": response_payload["filters"],
            "importer_response_time_ms": round(duration * 1000, 2),
            "user_id": current_user.id,
        },
    )
    return jsonify(response_payload), HTTPStatus.OK


@importer_blueprint.get("/runs/<int:run_id>")
def importer_run_detail(run_id: int):
    enabled_response = _ensure_importer_enabled_api()
    if enabled_response:
        return enabled_response

    auth_response = _ensure_authenticated_api()
    if auth_response:
        return auth_response

    permission_response = _ensure_manage_imports_permission()
    if permission_response:
        return permission_response

    start_time = time.perf_counter()
    try:
        run = _run_service.get_run(run_id)
        summary = _run_service.summarize(run)
    except NoResultFound:
        ImporterMonitoring.record_runs_detail(duration_seconds=time.perf_counter() - start_time, status="not_found")
        return _json_error(f"Import run {run_id} not found.", HTTPStatus.NOT_FOUND)
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("Importer run detail failed.", exc_info=exc)
        ImporterMonitoring.record_runs_detail(duration_seconds=time.perf_counter() - start_time, status="error")
        return _json_error("Failed to load run detail.", HTTPStatus.INTERNAL_SERVER_ERROR)

    duration = time.perf_counter() - start_time
    ImporterMonitoring.record_runs_detail(duration_seconds=duration, status="success")

    _run_service.record_audit_view(
        current_user.id,
        run_id=run_id,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )

    payload = _serialize_detail(run, summary=summary)

    current_app.logger.info(
        "Importer run detail accessed",
        extra={
            "importer_run_id": run_id,
            "importer_status": payload["status"],
            "importer_source": payload["source"],
            "importer_response_time_ms": round(duration * 1000, 2),
            "user_id": current_user.id,
        },
    )
    return jsonify(payload), HTTPStatus.OK


@importer_blueprint.get("/runs/stats")
def importer_runs_stats():
    enabled_response = _ensure_importer_enabled_api()
    if enabled_response:
        return enabled_response

    auth_response = _ensure_authenticated_api()
    if auth_response:
        return auth_response

    permission_response = _ensure_manage_imports_permission()
    if permission_response:
        return permission_response

    try:
        filters = _parse_filters()
    except ValueError as exc:
        ImporterMonitoring.record_runs_stats(duration_seconds=0.0, status="invalid_request")
        return _json_error(str(exc), HTTPStatus.BAD_REQUEST)

    start_time = time.perf_counter()
    try:
        stats = _run_service.get_stats(filters)
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("Importer runs stats failed.", exc_info=exc)
        ImporterMonitoring.record_runs_stats(duration_seconds=time.perf_counter() - start_time, status="error")
        return _json_error("Failed to load run statistics.", HTTPStatus.INTERNAL_SERVER_ERROR)

    duration = time.perf_counter() - start_time
    ImporterMonitoring.record_runs_stats(duration_seconds=duration, status="success")

    response_payload = {
        "total": stats.total,
        "by_status": stats.statuses,
        "by_source": stats.sources,
    }

    return jsonify(response_payload), HTTPStatus.OK
