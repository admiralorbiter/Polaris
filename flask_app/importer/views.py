"""
Importer blueprint endpoints for health, runs dashboard APIs, and related helpers.
"""

from __future__ import annotations

import time
from http import HTTPStatus

from celery.exceptions import TimeoutError as CeleryTimeoutError
from flask import Blueprint, current_app, jsonify, make_response, request
from flask_login import current_user
from sqlalchemy.exc import NoResultFound

from config.monitoring import ImporterMonitoring
from flask_app.importer.pipeline.dq_service import DataQualityViolationService, ViolationFilters
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
_dq_service = DataQualityViolationService()


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


def _ensure_imports_view_permission():
    if has_permission(current_user, "manage_imports") or has_permission(current_user, "view_imports"):
        return None
    return _json_error("Missing importer view permission.", HTTPStatus.FORBIDDEN)


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
        "rows_created": summary.rows_created,
        "rows_updated": summary.rows_updated,
        "rows_reactivated": summary.rows_reactivated,
        "rows_changed": summary.rows_changed,
        "rows_skipped_duplicates": summary.rows_skipped_duplicates,
        "rows_deduped_auto": summary.rows_deduped_auto,
        "rows_dedupe_auto": summary.rows_dedupe_auto,
        "rows_dedupe_manual_review": summary.rows_dedupe_manual_review,
        "rows_skipped_no_change": summary.rows_skipped_no_change,
        "rows_missing_external_id": summary.rows_missing_external_id,
        "rows_soft_deleted": summary.rows_soft_deleted,
        "triggered_by": summary.triggered_by,
        "can_retry": summary.can_retry,
        "counts_digest": summary.counts_digest,
        "survivorship": summary.survivorship,
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
        "survivorship": summary.survivorship,
        "error_summary": run.error_summary,
        "rows_deduped_auto": summary.rows_deduped_auto,
        "rows_dedupe_auto": summary.rows_dedupe_auto,
        "rows_dedupe_manual_review": summary.rows_dedupe_manual_review,
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
        ImporterMonitoring.record_runs_list(
            duration_seconds=time.perf_counter() - start_time, status="error", result_count=0
        )
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
        "by_dry_run": stats.dry_runs,
    }

    return jsonify(response_payload), HTTPStatus.OK


# ---------------------------------------------------------------------------
# DQ violations APIs
# ---------------------------------------------------------------------------


def _parse_violation_filters():
    raw = request.args
    try:
        filters = ViolationFilters.coerce(
            page=raw.get("page"),
            page_size=raw.get("per_page") or raw.get("page_size"),
            sort=raw.get("sort"),
            rule_codes=_split_csv(raw.get("rule_code") or raw.get("rule_codes")),
            severities=_split_csv(raw.get("severity") or raw.get("severities")),
            statuses=_split_csv(raw.get("status") or raw.get("statuses")),
            run_ids=_split_csv(raw.get("run_id") or raw.get("run_ids")),
            created_from=raw.get("created_from"),
            created_to=raw.get("created_to"),
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return filters


def _serialize_violation_summary(summary):
    return {
        "id": summary.id,
        "run_id": summary.run_id,
        "staging_volunteer_id": summary.staging_volunteer_id,
        "rule_code": summary.rule_code,
        "severity": summary.severity,
        "status": summary.status,
        "created_at": summary.created_at.isoformat(),
        "preview": summary.preview,
        "source": summary.source,
    }


def _remediation_hint(rule_code: str) -> str:
    hints = {
        "VOL_CONTACT_REQUIRED": "Add at least one contact method before requeueing.",
        "VOL_EMAIL_INVALID": "Correct the email format or remove it if unavailable.",
        "VOL_PHONE_INVALID": "Provide a valid E.164 formatted phone number.",
    }
    return hints.get(rule_code, "Review violation details and update the payload before requeueing.")


def _serialize_violation_detail(violation):
    staging = violation.staging_row
    import_run = violation.import_run
    payload = staging.payload_json if staging else {}
    normalized = staging.normalized_json if staging else {}
    details = violation.details_json or {}
    severity = violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
    status = violation.status.value if hasattr(violation.status, "value") else str(violation.status)

    summary = _dq_service.summarize(violation)

    return {
        "id": violation.id,
        "run_id": violation.run_id,
        "staging_volunteer_id": violation.staging_volunteer_id,
        "rule_code": violation.rule_code,
        "severity": severity,
        "status": status,
        "created_at": violation.created_at.isoformat() if violation.created_at else None,
        "source": import_run.source if import_run else None,
        "preview": summary.preview,
        "staging_payload": payload,
        "normalized_payload": normalized,
        "violation_details": details,
        "remediation_hint": _remediation_hint(violation.rule_code),
        "remediation_notes": violation.remediation_notes,
        "edited_payload": violation.edited_payload_json or {},
        "edited_fields": violation.edited_fields_json or {},
        "remediation_audit": violation.remediation_audit_json or {},
    }


@importer_blueprint.get("/violations")
def importer_violations_list():
    enabled_response = _ensure_importer_enabled_api()
    if enabled_response:
        return enabled_response

    auth_response = _ensure_authenticated_api()
    if auth_response:
        return auth_response

    permission_response = _ensure_imports_view_permission()
    if permission_response:
        return permission_response

    try:
        filters = _parse_violation_filters()
    except ValueError as exc:
        ImporterMonitoring.record_dq_list(duration_seconds=0.0, status="invalid_request", result_count=0)
        return _json_error(str(exc), HTTPStatus.BAD_REQUEST)

    start_time = time.perf_counter()
    try:
        result = _dq_service.list_violations(filters)
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("Importer violations list failed.", exc_info=exc)
        ImporterMonitoring.record_dq_list(
            duration_seconds=time.perf_counter() - start_time, status="error", result_count=0
        )
        return _json_error("Failed to load violations.", HTTPStatus.INTERNAL_SERVER_ERROR)

    duration = time.perf_counter() - start_time
    ImporterMonitoring.record_dq_list(duration_seconds=duration, status="success", result_count=len(result.items))

    response_payload = {
        "violations": [_serialize_violation_summary(item) for item in result.items],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "total_pages": result.total_pages,
        "filters": {
            "page": filters.page,
            "page_size": filters.page_size,
            "sort": filters.sort,
            "rule_codes": list(filters.rule_codes),
            "severities": [severity.value for severity in filters.severities],
            "statuses": [status.value for status in filters.statuses],
            "run_ids": list(filters.run_ids),
            "created_from": filters.created_from.isoformat() if filters.created_from else None,
            "created_to": filters.created_to.isoformat() if filters.created_to else None,
        },
    }

    current_app.logger.info(
        "Importer violations list retrieved",
        extra={
            "dq_violation_count": len(result.items),
            "dq_total_violations": result.total,
            "dq_response_time_ms": round(duration * 1000, 2),
            "user_id": current_user.id,
        },
    )
    return jsonify(response_payload), HTTPStatus.OK


@importer_blueprint.get("/violations/<int:violation_id>")
def importer_violation_detail(violation_id: int):
    enabled_response = _ensure_importer_enabled_api()
    if enabled_response:
        return enabled_response

    auth_response = _ensure_authenticated_api()
    if auth_response:
        return auth_response

    permission_response = _ensure_imports_view_permission()
    if permission_response:
        return permission_response

    start_time = time.perf_counter()
    violation = _dq_service.get_violation(violation_id)
    if violation is None:
        ImporterMonitoring.record_dq_detail(duration_seconds=time.perf_counter() - start_time, status="not_found")
        return _json_error(f"Violation {violation_id} not found.", HTTPStatus.NOT_FOUND)

    duration = time.perf_counter() - start_time
    ImporterMonitoring.record_dq_detail(duration_seconds=duration, status="success")

    payload = _serialize_violation_detail(violation)
    current_app.logger.info(
        "Importer violation detail accessed",
        extra={
            "dq_violation_id": violation_id,
            "dq_rule_code": violation.rule_code,
            "user_id": current_user.id,
            "dq_response_time_ms": round(duration * 1000, 2),
        },
    )
    return jsonify(payload), HTTPStatus.OK


@importer_blueprint.get("/violations/stats")
def importer_violations_stats():
    enabled_response = _ensure_importer_enabled_api()
    if enabled_response:
        return enabled_response

    auth_response = _ensure_authenticated_api()
    if auth_response:
        return auth_response

    permission_response = _ensure_imports_view_permission()
    if permission_response:
        return permission_response

    try:
        filters = _parse_violation_filters()
    except ValueError as exc:
        ImporterMonitoring.record_dq_stats(duration_seconds=0.0, status="invalid_request")
        return _json_error(str(exc), HTTPStatus.BAD_REQUEST)

    start_time = time.perf_counter()
    try:
        stats = _dq_service.get_stats(filters)
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("Importer violations stats failed.", exc_info=exc)
        ImporterMonitoring.record_dq_stats(duration_seconds=time.perf_counter() - start_time, status="error")
        return _json_error("Failed to load violation statistics.", HTTPStatus.INTERNAL_SERVER_ERROR)

    duration = time.perf_counter() - start_time
    ImporterMonitoring.record_dq_stats(duration_seconds=duration, status="success")

    response_payload = {
        "total": stats.total,
        "by_rule_code": stats.by_rule_code,
        "by_severity": stats.by_severity,
        "by_status": stats.by_status,
    }
    return jsonify(response_payload), HTTPStatus.OK


@importer_blueprint.get("/violations/export")
def importer_violations_export():
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
        filters = _parse_violation_filters()
    except ValueError as exc:
        ImporterMonitoring.record_dq_export(duration_seconds=0.0, status="invalid_request", row_count=0)
        return _json_error(str(exc), HTTPStatus.BAD_REQUEST)

    start_time = time.perf_counter()
    try:
        filename, csv_content = _dq_service.export_csv(filters)
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("Importer violations export failed.", exc_info=exc)
        ImporterMonitoring.record_dq_export(
            duration_seconds=time.perf_counter() - start_time, status="error", row_count=0
        )
        return _json_error("Failed to export violations.", HTTPStatus.INTERNAL_SERVER_ERROR)

    duration = time.perf_counter() - start_time
    row_count = csv_content.count("\n") - 1 if csv_content else 0
    ImporterMonitoring.record_dq_export(duration_seconds=duration, status="success", row_count=max(row_count, 0))

    response = make_response(csv_content)
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@importer_blueprint.get("/violations/rule_codes")
def importer_violations_rule_codes():
    enabled_response = _ensure_importer_enabled_api()
    if enabled_response:
        return enabled_response

    auth_response = _ensure_authenticated_api()
    if auth_response:
        return auth_response

    permission_response = _ensure_imports_view_permission()
    if permission_response:
        return permission_response

    codes = _dq_service.list_rule_codes()
    return jsonify({"rule_codes": codes}), HTTPStatus.OK
