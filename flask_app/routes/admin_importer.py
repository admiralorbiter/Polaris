"""
Admin-facing importer routes for initiating runs and monitoring status.
"""

from __future__ import annotations

import json
import os
import re
from collections import deque
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from config.monitoring import ImporterMonitoring
from config.survivorship import load_profile
from flask_app.importer import get_adapter_readiness
from flask_app.importer.celery_app import DEFAULT_QUEUE_NAME, get_celery_app
from flask_app.importer.mapping import MappingLoadError, get_active_salesforce_mapping
from flask_app.importer.pipeline.dq_service import (
    DataQualityViolationService,
    RemediationConflict,
    RemediationNotFound,
    RemediationValidationError,
)
from flask_app.importer.pipeline.fuzzy_candidates import scan_existing_volunteers_for_duplicates
from flask_app.importer.pipeline.merge_service import MergeService
from flask_app.importer.pipeline.run_service import ImportRunService
from flask_app.importer.registry import get_adapter_registry
from flask_app.importer.utils import allowed_file, cleanup_upload, persist_upload, resolve_upload_directory
from flask_app.models import AdminLog, db
from flask_app.models.importer.schema import (
    DataQualitySeverity,
    DataQualityStatus,
    DedupeDecision,
    ImporterWatermark,
    ImportRun,
    ImportRunStatus,
    ImportSkip,
    ImportSkipType,
)
from flask_app.utils.importer import is_importer_enabled
from flask_app.utils.permissions import permission_required

admin_importer_blueprint = Blueprint("admin_importer", __name__, url_prefix="/admin/imports")
_run_service = ImportRunService()
_dq_service = DataQualityViolationService()
_merge_service = MergeService()


@admin_importer_blueprint.get("/mappings/salesforce.yaml")
@login_required
@permission_required("manage_imports", org_context=False)
def download_salesforce_mapping():
    try:
        spec = get_active_salesforce_mapping()
    except MappingLoadError as exc:
        current_app.logger.error("Failed to load Salesforce mapping: %s", exc)
        return jsonify({"error": "Salesforce mapping unavailable"}), HTTPStatus.INTERNAL_SERVER_ERROR

    return send_file(
        spec.path,
        mimetype="text/yaml",
        as_attachment=True,
        download_name=spec.path.name,
    )


_STATUS_LABELS = {
    "ready": "Ready",
    "missing-deps": "Missing dependencies",
    "missing-env": "Needs configuration",
    "auth-error": "Authentication error",
    "disabled": "Disabled",
}

_STATUS_BADGES = {
    "ready": "bg-success",
    "missing-deps": "bg-danger",
    "missing-env": "bg-warning text-dark",
    "auth-error": "bg-danger",
    "disabled": "bg-secondary",
}

_FOCUS_ADAPTERS = ("csv", "salesforce")
_SALESFORCE_RECORD_LIMIT_MAX = 1_000_000


_ADAPTER_READINESS_CACHE: dict[str, object] = {"expires": None, "value": None}
_SALESFORCE_TRIGGER_HISTORY: dict[int, deque[datetime]] = {}
_SALESFORCE_RATE_LIMIT = 1
_SALESFORCE_RATE_WINDOW = timedelta(minutes=1)
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


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


def _resolve_docs_url(adapter_name: str) -> str:
    if adapter_name == "salesforce":
        return current_app.config.get(
            "IMPORTER_SALESFORCE_DOC_URL",
            "https://docs.polaris.example/importer/salesforce",
        )
    if adapter_name == "csv":
        return current_app.config.get(
            "IMPORTER_CSV_DOC_URL",
            "https://docs.polaris.example/importer/csv",
        )
    return current_app.config.get(
        "IMPORTER_ADAPTER_DOC_URL",
        "https://docs.polaris.example/importer",
    )


def _build_adapter_cards() -> list[dict[str, object]]:
    state = current_app.extensions.get("importer", {})
    configured_adapters = tuple(state.get("configured_adapters", ()))
    readiness_map = get_adapter_readiness(current_app)
    descriptor_map = get_adapter_registry()

    cards: list[dict[str, object]] = []
    for adapter_name in _FOCUS_ADAPTERS:
        descriptor = descriptor_map.get(adapter_name)
        if descriptor is None:
            continue

        readiness = readiness_map.get(adapter_name) or {}
        is_configured = adapter_name in configured_adapters
        status = readiness.get("status") or ("disabled" if not is_configured else "ready")
        messages = list(readiness.get("messages") or ())
        dependency_errors = readiness.get("dependency_errors") or ()
        if dependency_errors:
            messages.extend(str(error) for error in dependency_errors if str(error) not in messages)

        if not is_configured and adapter_name != "csv":
            messages.append(
                "Adapter is disabled. Update IMPORTER_ADAPTERS and redeploy the importer workers to enable it."
            )

        mapping_info: dict[str, object] | None = None
        latest_run_summary: dict[str, object] | None = None
        if adapter_name == "salesforce":
            try:
                mapping_spec = get_active_salesforce_mapping()
                mapping_info = {
                    "version": mapping_spec.version,
                    "checksum": mapping_spec.checksum,
                    "download_url": url_for("admin_importer.download_salesforce_mapping"),
                }
            except MappingLoadError as exc:
                messages.append(f"Salesforce mapping failed to load: {exc}")
            latest_run = ImportRun.query.filter_by(adapter="salesforce").order_by(ImportRun.created_at.desc()).first()
            if latest_run:
                status_value = (
                    latest_run.status.value if hasattr(latest_run.status, "value") else str(latest_run.status)
                )
                latest_run_summary = {
                    "id": latest_run.id,
                    "status_value": status_value,
                    "status_label": status_value.replace("_", " ").title(),
                }
                if latest_run.metrics_json:
                    sf_metrics = latest_run.metrics_json.get("salesforce") or {}
                    unmapped = sf_metrics.get("unmapped_fields") or {}
                    if unmapped:
                        messages.append(
                            "Unmapped Salesforce fields detected in the last run: "
                            + ", ".join(f"{field}×{count}" for field, count in unmapped.items())
                        )
                    errors = sf_metrics.get("transform_errors") or []
                    if errors:
                        messages.append("Recent mapping errors: " + "; ".join(errors[:3]))
                    core_counts = (
                        (latest_run.counts_json or {}).get("core", {}).get("volunteers", {}).get("salesforce", {})
                    )
                    if core_counts:
                        messages.append(
                            "Last run counters — "
                            f"created {core_counts.get('created', 0)}, "
                            f"updated {core_counts.get('updated', 0)}, "
                            f"deleted {core_counts.get('deleted', 0)}, "
                            f"unchanged {core_counts.get('unchanged', 0)}."
                        )

        cards.append(
            {
                "name": adapter_name,
                "title": descriptor.title,
                "status": status,
                "status_label": _STATUS_LABELS.get(status, status.replace("-", " ").title()),
                "badge_class": _STATUS_BADGES.get(status, "bg-secondary"),
                "is_configured": is_configured,
                "messages": messages,
                "docs_url": _resolve_docs_url(adapter_name),
                "toggle_disabled": True,
                "toggle_disabled_reason": "Manage adapter enablement via environment configuration.",
                "mapping": mapping_info,
                "latest_run": latest_run_summary,
            }
        )
    return cards


def _get_adapter_readiness_snapshot(force_refresh: bool = False) -> dict[str, object]:
    cached_value = _ADAPTER_READINESS_CACHE.get("value")
    cached_expiry = _ADAPTER_READINESS_CACHE.get("expires")
    now = datetime.now(timezone.utc)

    if not force_refresh and cached_value is not None and isinstance(cached_expiry, datetime) and cached_expiry > now:
        return cached_value  # type: ignore[return-value]

    snapshot = get_adapter_readiness(current_app)
    _ADAPTER_READINESS_CACHE["value"] = snapshot
    _ADAPTER_READINESS_CACHE["expires"] = now + timedelta(seconds=30)
    return snapshot


def _reset_salesforce_watermark(*, notes: str | None = None) -> None:
    """
    Reset the Salesforce importer watermark so the next run reprocesses everything.
    """

    object_name = (current_app.config.get("IMPORTER_SALESFORCE_OBJECTS") or ("contacts",))[0]
    watermark = db.session.query(ImporterWatermark).filter_by(adapter="salesforce", object_name=object_name).first()
    if watermark is not None:
        db.session.delete(watermark)
        db.session.commit()
    AdminLog.log_action(
        admin_user_id=current_user.id,
        action="IMPORT_SALESFORCE_WATERMARK_RESET",
        details=json.dumps(
            {
                "adapter": "salesforce",
                "object_name": object_name,
                "notes": notes or "",
            }
        ),
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )


def _get_salesforce_adapter_state() -> tuple[bool, bool, list[str]]:
    state = current_app.extensions.get("importer", {})
    configured_adapters = tuple(state.get("configured_adapters", ()))
    is_enabled = "salesforce" in configured_adapters

    readiness_snapshot = _get_adapter_readiness_snapshot()
    readiness = readiness_snapshot.get("salesforce") or {}
    status = readiness.get("status")
    is_ready = status == "ready"
    messages = list(readiness.get("messages") or ())
    dependency_errors = readiness.get("dependency_errors") or ()
    messages.extend(str(error) for error in dependency_errors if str(error) not in messages)
    return is_enabled, is_ready, messages


def _is_salesforce_rate_limited(user_id: int) -> bool:
    history = _SALESFORCE_TRIGGER_HISTORY.setdefault(user_id, deque())
    now = datetime.now(timezone.utc)
    window_start = now - _SALESFORCE_RATE_WINDOW
    while history and history[0] < window_start:
        history.popleft()
    return len(history) >= _SALESFORCE_RATE_LIMIT


def _record_salesforce_trigger(user_id: int) -> None:
    history = _SALESFORCE_TRIGGER_HISTORY.setdefault(user_id, deque())
    history.append(datetime.now(timezone.utc))


@admin_importer_blueprint.post("/salesforce/trigger")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_salesforce_trigger():
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    if _is_salesforce_rate_limited(current_user.id):
        return (
            jsonify({"error": "Too many Salesforce imports triggered. Please wait before retrying."}),
            HTTPStatus.TOO_MANY_REQUESTS,
        )

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), HTTPStatus.BAD_REQUEST

    dry_run = bool(payload.get("dry_run", False))
    record_limit_raw = payload.get("record_limit")
    reset_watermark = bool(payload.get("reset_watermark", False))
    notes = payload.get("notes")
    entity_type = payload.get("entity_type", "contacts")  # Default to contacts for backward compatibility

    record_limit: int | None = None
    if record_limit_raw is not None:
        try:
            record_limit = int(record_limit_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "record_limit must be an integer."}), HTTPStatus.BAD_REQUEST
        if record_limit <= 0:
            return jsonify({"error": "record_limit must be greater than zero."}), HTTPStatus.BAD_REQUEST
        if record_limit > _SALESFORCE_RECORD_LIMIT_MAX:
            return (
                jsonify({"error": f"record_limit must be less than or equal to {_SALESFORCE_RECORD_LIMIT_MAX:,}."}),
                HTTPStatus.BAD_REQUEST,
            )

    if notes is not None and not isinstance(notes, str):
        return jsonify({"error": "notes must be a string."}), HTTPStatus.BAD_REQUEST

    is_enabled, is_ready, readiness_messages = _get_salesforce_adapter_state()
    if not is_enabled:
        return (
            jsonify(
                {
                    "error": "Salesforce adapter is not enabled. Update IMPORTER_ADAPTERS to include 'salesforce'.",
                    "messages": readiness_messages,
                }
            ),
            HTTPStatus.BAD_REQUEST,
        )
    if not is_ready:
        return (
            jsonify(
                {
                    "error": "Salesforce adapter is not ready. Resolve readiness issues before triggering imports.",
                    "messages": readiness_messages,
                }
            ),
            HTTPStatus.BAD_REQUEST,
        )

    if reset_watermark:
        _reset_salesforce_watermark(notes=notes)

    adapter_snapshot = _get_adapter_readiness_snapshot(force_refresh=True)

    run_notes = notes.strip() if isinstance(notes, str) else ""
    if len(run_notes) > 500:
        return jsonify({"error": "notes must be 500 characters or fewer."}), HTTPStatus.BAD_REQUEST
    if not run_notes:
        run_notes = f"Salesforce import triggered by user {current_user.id}"
    run_notes = _CONTROL_CHAR_PATTERN.sub(" ", run_notes)

    # Validate entity_type
    if entity_type not in ("contacts", "organizations", "affiliations", "events"):
        return (
            jsonify({"error": "entity_type must be 'contacts', 'organizations', 'affiliations', or 'events'."}),
            HTTPStatus.BAD_REQUEST,
        )

    ingest_params: dict[str, object] = {
        "source_system": "salesforce",
        "dry_run": dry_run,
        "reset_watermark": reset_watermark,
        "entity_type": entity_type,
    }
    if record_limit is not None:
        ingest_params["record_limit"] = record_limit

    run = ImportRun(
        source="salesforce",
        adapter="salesforce",
        status=ImportRunStatus.PENDING,
        dry_run=dry_run,
        notes=run_notes,
        triggered_by_user_id=current_user.id,
        counts_json={},
        metrics_json={},
        adapter_health_json=adapter_snapshot,
        ingest_params_json=ingest_params,
    )
    db.session.add(run)
    db.session.commit()

    celery_app = get_celery_app(current_app)
    if celery_app is None:
        run.status = ImportRunStatus.FAILED
        run.error_summary = "Importer worker is not configured."
        db.session.commit()
        return (
            jsonify({"error": "Importer worker is not configured; cannot queue Salesforce import."}),
            HTTPStatus.SERVICE_UNAVAILABLE,
        )

    task_kwargs: dict[str, object] = {
        "run_id": run.id,
        "dry_run": dry_run,
    }
    if record_limit is not None:
        task_kwargs["record_limit"] = record_limit

    # Select task based on entity_type
    if entity_type == "contacts":
        task_name = "importer.pipeline.ingest_salesforce_contacts"
    elif entity_type == "organizations":
        task_name = "importer.pipeline.ingest_salesforce_accounts"
    elif entity_type == "affiliations":
        task_name = "importer.pipeline.ingest_salesforce_affiliations"
    elif entity_type == "events":
        task_name = "importer.pipeline.ingest_salesforce_sessions"
    else:
        task_name = "importer.pipeline.ingest_salesforce_contacts"  # Default fallback

    try:
        async_result = celery_app.send_task(
            task_name,
            kwargs=task_kwargs,
        )
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.exception(
            "Failed to enqueue Salesforce importer run",
            extra={"importer_run_id": run.id, "triggered_by_user_id": current_user.id},
            exc_info=exc,
        )
        db.session.refresh(run)
        run.status = ImportRunStatus.FAILED
        run.error_summary = str(exc)
        db.session.commit()
        return (
            jsonify({"error": "Failed to enqueue Salesforce import; please retry later."}),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    AdminLog.log_action(
        admin_user_id=current_user.id,
        action="IMPORT_RUN_ENQUEUED",
        details=json.dumps(
            {
                "run_id": run.id,
                "task_id": async_result.id,
                "source": "salesforce",
                "entity_type": entity_type,
                "dry_run": dry_run,
                "record_limit": record_limit,
                "reset_watermark": reset_watermark,
            }
        ),
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )

    current_app.logger.info(
        "Salesforce importer run enqueued",
        extra={
            "importer_run_id": run.id,
            "importer_task_id": async_result.id,
            "importer_source": "salesforce",
            "triggered_by_user_id": current_user.id,
            "importer_dry_run": dry_run,
            "salesforce_entity_type": entity_type,
            "salesforce_record_limit": record_limit,
            "salesforce_reset_watermark": reset_watermark,
        },
    )

    ImporterMonitoring.record_run_enqueued(user_id=current_user.id, dry_run=dry_run)
    _record_salesforce_trigger(current_user.id)

    return (
        jsonify(
            {
                "run_id": run.id,
                "task_id": getattr(async_result, "id", async_result),
                "status": "queued",
                "queue": DEFAULT_QUEUE_NAME,
            }
        ),
        HTTPStatus.ACCEPTED,
    )


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
                "dry_run": bool(run.dry_run),
            }
        )
    adapter_cards = _build_adapter_cards()
    salesforce_adapter_enabled, salesforce_adapter_ready, salesforce_adapter_messages = _get_salesforce_adapter_state()
    salesforce_last_run = None
    for card in adapter_cards:
        if card.get("name") == "salesforce":
            salesforce_last_run = card.get("latest_run")
            break
    return render_template(
        "admin/importer.html",
        recent_runs=recent_runs,
        max_upload_mb=current_app.config.get("IMPORTER_MAX_UPLOAD_MB", 25),
        default_queue=DEFAULT_QUEUE_NAME,
        adapter_cards=adapter_cards,
        salesforce_adapter_enabled=salesforce_adapter_enabled,
        salesforce_adapter_ready=salesforce_adapter_ready,
        salesforce_adapter_messages=salesforce_adapter_messages,
        salesforce_last_run=salesforce_last_run,
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
        sources = sorted(
            {adapter.name for adapter in current_app.extensions.get("importer", {}).get("active_adapters", ())}
        )

    profile = load_profile(dict(os.environ))
    survivorship_profile = {
        "key": profile.key,
        "label": profile.label,
        "description": profile.description,
        "field_groups": [
            {
                "name": group.name,
                "display_name": group.display_name,
                "fields": [rule.field_name for rule in group.fields],
            }
            for group in profile.field_groups
        ],
    }

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
        survivorship_profile=survivorship_profile,
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
    dry_run_form = request.form.get("dry_run")
    dry_run = str(dry_run_form).lower() in ("1", "true", "on", "yes")
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
            dry_run=dry_run,
            status=ImportRunStatus.PENDING,
            notes=f"Admin upload by user {current_user.id} ({file_storage.filename})",
            triggered_by_user_id=current_user.id,
            counts_json={},
            metrics_json={},
            adapter_health_json=get_adapter_readiness(current_app),
            ingest_params_json={
                "file_path": str(stored_path),
                "source_system": source,
                "dry_run": dry_run,
                "keep_file": True,  # Retain uploads for retry capability
            },
        )
        db.session.add(run)
        db.session.commit()

        celery_app = get_celery_app(current_app)
        if celery_app is None:
            raise RuntimeError("Importer worker is not configured.")

        task_kwargs = {
            "run_id": run.id,
            "file_path": str(stored_path),
            "dry_run": dry_run,
            "source_system": source,
            "keep_file": True,
        }

        async_result = celery_app.send_task(
            "importer.pipeline.ingest_csv",
            kwargs=task_kwargs,
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
                    "dry_run": dry_run,
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
                "importer_dry_run": dry_run,
            },
        )

        ImporterMonitoring.record_run_enqueued(user_id=current_user.id, dry_run=dry_run)

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
    run.dry_run = bool(dry_run)
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
                "dry_run": dry_run,
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
            "importer_dry_run": dry_run,
        },
    )

    ImporterMonitoring.record_run_enqueued(user_id=current_user.id, dry_run=dry_run)

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


@admin_importer_blueprint.get("/dedupe/review")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dedupe_review_page():
    """Render the dedupe review queue page."""
    if not _ensure_importer_enabled():
        return render_template("errors/404.html"), HTTPStatus.NOT_FOUND

    return render_template("importer/review.html")


@admin_importer_blueprint.get("/dedupe/review/api")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dedupe_review_queue():
    """Get list of dedupe candidates for review (API endpoint)."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    status = request.args.get("status")
    match_type = request.args.get("match_type")
    run_id_raw = request.args.get("run_id")
    limit_raw = request.args.get("limit", "100")
    offset_raw = request.args.get("offset", "0")

    run_id: int | None = None
    if run_id_raw:
        try:
            run_id = int(run_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "run_id must be an integer."}), HTTPStatus.BAD_REQUEST

    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "limit and offset must be integers."}), HTTPStatus.BAD_REQUEST

    if limit < 1 or limit > 500:
        return jsonify({"error": "limit must be between 1 and 500."}), HTTPStatus.BAD_REQUEST
    if offset < 0:
        return jsonify({"error": "offset must be non-negative."}), HTTPStatus.BAD_REQUEST

    try:
        candidates, total = _merge_service.get_review_queue(
            status=status,
            match_type=match_type,
            run_id=run_id,
            limit=limit,
            offset=offset,
        )

        candidates_list = []
        for c in candidates:
            try:
                primary_name = None
                if c.primary_contact:
                    primary_name = (
                        f"{c.primary_contact.first_name or ''} {c.primary_contact.last_name or ''}".strip() or None
                    )

                candidate_name = None
                if c.candidate_contact:
                    candidate_name = (
                        f"{c.candidate_contact.first_name or ''} {c.candidate_contact.last_name or ''}".strip() or None
                    )
                elif c.staging_row and c.staging_row.normalized_json:
                    staging_json = c.staging_row.normalized_json
                    first_name = staging_json.get("first_name", "") or ""
                    last_name = staging_json.get("last_name", "") or ""
                    candidate_name = f"{first_name} {last_name}".strip() or None
                elif c.staging_row:
                    # Fallback: try to get name from staging row even if normalized_json is missing
                    # This handles edge cases where staging row exists but normalized_json is None
                    candidate_name = f"Staging Row {c.staging_row.id}" if c.staging_row else None

                created_at = None
                if c.import_run and c.import_run.created_at:
                    created_at = c.import_run.created_at.isoformat()

                # Find merge_log_id for auto-merged items (for undo functionality)
                merge_log_id = None
                decided_at = None
                if c.decision == DedupeDecision.AUTO_MERGED and c.primary_contact_id:
                    from flask_app.models.importer.schema import MergeLog

                    # Find MergeLog entry by matching primary_contact_id and checking undo_payload
                    merge_logs = (
                        db.session.query(MergeLog)
                        .filter_by(
                            primary_contact_id=c.primary_contact_id,
                            decision_type="auto",
                        )
                        .all()
                    )
                    # Check undo_payload for suggestion_id match
                    for ml in merge_logs:
                        if ml.undo_payload and ml.undo_payload.get("suggestion_id") == c.id:
                            merge_log_id = ml.id
                            break
                    if c.decided_at:
                        decided_at = c.decided_at.isoformat()
                elif c.decided_at:
                    decided_at = c.decided_at.isoformat()

                candidates_list.append(
                    {
                        "id": c.id,
                        "run_id": c.run_id,
                        "score": float(c.score) if c.score else None,
                        "match_type": c.match_type,
                        "features_json": c.features_json or {},
                        "primary_contact_id": c.primary_contact_id,
                        "candidate_contact_id": c.candidate_contact_id,
                        "staging_volunteer_id": c.staging_volunteer_id,
                        "decision": c.decision.value if isinstance(c.decision, DedupeDecision) else str(c.decision),
                        "primary_name": primary_name,
                        "candidate_name": candidate_name,
                        "created_at": created_at,
                        "decided_at": decided_at,
                        "merge_log_id": merge_log_id,
                    }
                )
            except Exception as e:
                current_app.logger.warning(f"Error serializing candidate {c.id}: {e}", exc_info=True)
                # Skip this candidate but continue processing others
                continue

        result = {
            "candidates": candidates_list,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        return jsonify(result), HTTPStatus.OK
    except Exception as exc:
        current_app.logger.exception("Failed to fetch dedupe review queue", exc_info=exc)
        return jsonify({"error": "Failed to fetch review queue."}), HTTPStatus.INTERNAL_SERVER_ERROR


@admin_importer_blueprint.get("/dedupe/candidates/<int:candidate_id>")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dedupe_candidate_details(candidate_id: int):
    """Get detailed information about a dedupe candidate."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    try:
        details = _merge_service.get_candidate_details(candidate_id)
        result = {
            "suggestion_id": details.suggestion_id,
            "score": details.score,
            "match_type": details.match_type,
            "features_json": details.features_json or {},
            "primary_contact": details.primary_contact,
            "candidate_contact": details.candidate_contact,
            "staging_data": details.staging_data,
            "survivorship_preview": details.survivorship_preview,
            "run_id": details.run_id,
            "created_at": details.created_at.isoformat(),
        }
        return jsonify(result), HTTPStatus.OK
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except Exception as exc:
        current_app.logger.exception("Failed to fetch candidate details", exc_info=exc)
        return jsonify({"error": "Failed to fetch candidate details."}), HTTPStatus.INTERNAL_SERVER_ERROR


@admin_importer_blueprint.post("/dedupe/candidates/<int:candidate_id>/merge")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dedupe_merge_candidate(candidate_id: int):
    """Execute a merge operation for a dedupe candidate."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), HTTPStatus.BAD_REQUEST

    field_overrides = payload.get("field_overrides")
    if field_overrides is not None and not isinstance(field_overrides, dict):
        return jsonify({"error": "field_overrides must be a dictionary."}), HTTPStatus.BAD_REQUEST

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        return jsonify({"error": "notes must be a string."}), HTTPStatus.BAD_REQUEST

    try:
        merge_log = _merge_service.execute_merge(
            candidate_id,
            user_id=current_user.id,
            field_overrides=field_overrides,
            notes=notes,
        )
        db.session.commit()

        result = {
            "merge_log_id": merge_log.id,
            "primary_contact_id": merge_log.primary_contact_id,
            "merged_contact_id": merge_log.merged_contact_id,
            "decision_type": merge_log.decision_type,
        }
        return jsonify(result), HTTPStatus.OK
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to execute merge", exc_info=exc)
        return jsonify({"error": "Failed to execute merge."}), HTTPStatus.INTERNAL_SERVER_ERROR


@admin_importer_blueprint.post("/dedupe/candidates/<int:candidate_id>/reject")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dedupe_reject_candidate(candidate_id: int):
    """Mark a candidate as rejected (not a duplicate)."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), HTTPStatus.BAD_REQUEST

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        return jsonify({"error": "notes must be a string."}), HTTPStatus.BAD_REQUEST

    try:
        suggestion = _merge_service.reject_candidate(
            candidate_id,
            user_id=current_user.id,
            notes=notes,
        )
        db.session.commit()

        result = {
            "suggestion_id": suggestion.id,
            "decision": suggestion.decision.value
            if hasattr(suggestion.decision, "value")
            else str(suggestion.decision),
            "decided_at": suggestion.decided_at.isoformat() if suggestion.decided_at else None,
        }
        return jsonify(result), HTTPStatus.OK
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to reject candidate", exc_info=exc)
        return jsonify({"error": "Failed to reject candidate."}), HTTPStatus.INTERNAL_SERVER_ERROR


@admin_importer_blueprint.post("/dedupe/candidates/<int:candidate_id>/defer")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dedupe_defer_candidate(candidate_id: int):
    """Defer a candidate decision for later review."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), HTTPStatus.BAD_REQUEST

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        return jsonify({"error": "notes must be a string."}), HTTPStatus.BAD_REQUEST

    try:
        suggestion = _merge_service.defer_candidate(
            candidate_id,
            user_id=current_user.id,
            notes=notes,
        )
        db.session.commit()

        result = {
            "suggestion_id": suggestion.id,
            "decision": suggestion.decision.value
            if hasattr(suggestion.decision, "value")
            else str(suggestion.decision),
            "decided_at": suggestion.decided_at.isoformat() if suggestion.decided_at else None,
        }
        return jsonify(result), HTTPStatus.OK
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to defer candidate", exc_info=exc)
        return jsonify({"error": "Failed to defer candidate."}), HTTPStatus.INTERNAL_SERVER_ERROR


@admin_importer_blueprint.post("/dedupe/undo/<int:merge_log_id>")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dedupe_undo_merge(merge_log_id: int):
    """Undo a merge operation."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    try:
        undo_log = _merge_service.undo_merge(merge_log_id, user_id=current_user.id)
        db.session.commit()

        result = {
            "undo_merge_log_id": undo_log.id,
            "original_merge_log_id": merge_log_id,
            "primary_contact_id": undo_log.primary_contact_id,
            "merged_contact_id": undo_log.merged_contact_id,
        }
        return jsonify(result), HTTPStatus.OK
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to undo merge", exc_info=exc)
        return jsonify({"error": "Failed to undo merge."}), HTTPStatus.INTERNAL_SERVER_ERROR


@admin_importer_blueprint.get("/dedupe/stats")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dedupe_stats():
    """Get statistics about the review queue."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    try:
        stats = _merge_service.get_queue_stats()
        result = {
            "total_pending": stats.total_pending,
            "total_review_band": stats.total_review_band,
            "total_high_confidence": stats.total_high_confidence,
            "total_auto_merged": stats.total_auto_merged,
            "aging_buckets": stats.aging_buckets,
        }
        return jsonify(result), HTTPStatus.OK
    except Exception as exc:
        current_app.logger.exception("Failed to fetch dedupe stats", exc_info=exc)
        return jsonify({"error": "Failed to fetch queue statistics."}), HTTPStatus.INTERNAL_SERVER_ERROR


@admin_importer_blueprint.post("/dedupe/scan-existing")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_scan_existing_duplicates():
    """Trigger a scan of all existing volunteers to find duplicates."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    dry_run = request.json.get("dry_run", False) if request.is_json else False
    threshold = request.json.get("threshold", 0.80) if request.is_json else 0.80

    try:
        current_app.logger.info(
            f"User {current_user.id} triggered duplicate scan (dry_run={dry_run}, threshold={threshold})"
        )

        summary = scan_existing_volunteers_for_duplicates(
            dry_run=dry_run,
            similarity_threshold=threshold,
        )

        # Log admin action
        import json

        AdminLog.log_action(
            admin_user_id=current_user.id,
            action="IMPORTER_SCAN_DUPLICATES",
            details=json.dumps(
                {
                    "dry_run": dry_run,
                    "threshold": threshold,
                    "rows_considered": summary.rows_considered,
                    "suggestions_created": summary.suggestions_created,
                    "high_confidence": summary.high_confidence,
                    "review_band": summary.review_band,
                }
            ),
        )
        db.session.commit()

        result = {
            "success": True,
            "rows_considered": summary.rows_considered,
            "suggestions_created": summary.suggestions_created,
            "high_confidence": summary.high_confidence,
            "review_band": summary.review_band,
            "low_score": summary.low_score,
            "dry_run": dry_run,
        }
        return jsonify(result), HTTPStatus.OK
    except Exception as exc:
        current_app.logger.exception("Failed to scan for duplicates", exc_info=exc)
        db.session.rollback()
        return jsonify({"error": f"Failed to scan for duplicates: {str(exc)}"}), HTTPStatus.INTERNAL_SERVER_ERROR


@admin_importer_blueprint.get("/dedupe/export")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_dedupe_export():
    """Export dedupe summaries as CSV or JSON."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    format_type = request.args.get("format", "json").lower()
    run_id = request.args.get("run_id", type=int)
    status = request.args.get("status")

    if format_type not in ("csv", "json"):
        return jsonify({"error": "Format must be 'csv' or 'json'."}), HTTPStatus.BAD_REQUEST

    try:
        candidates, total = _merge_service.get_review_queue(
            status=status,
            match_type=None,
            run_id=run_id,
            limit=10000,  # Large limit for export
            offset=0,
        )

        if format_type == "json":
            result = []
            for c in candidates:
                primary_name = None
                if c.primary_contact:
                    primary_name = (
                        f"{c.primary_contact.first_name or ''} {c.primary_contact.last_name or ''}".strip() or None
                    )

                candidate_name = None
                if c.candidate_contact:
                    candidate_name = (
                        f"{c.candidate_contact.first_name or ''} {c.candidate_contact.last_name or ''}".strip() or None
                    )
                elif c.staging_row and c.staging_row.normalized_json:
                    staging_json = c.staging_row.normalized_json
                    first_name = staging_json.get("first_name", "") or ""
                    last_name = staging_json.get("last_name", "") or ""
                    candidate_name = f"{first_name} {last_name}".strip() or None

                result.append(
                    {
                        "id": c.id,
                        "run_id": c.run_id,
                        "score": float(c.score) if c.score else None,
                        "match_type": c.match_type,
                        "decision": c.decision.value if isinstance(c.decision, DedupeDecision) else str(c.decision),
                        "primary_contact_id": c.primary_contact_id,
                        "candidate_contact_id": c.candidate_contact_id,
                        "primary_name": primary_name,
                        "candidate_name": candidate_name,
                        "created_at": c.created_at.isoformat() if c.created_at else None,
                        "decided_at": c.decided_at.isoformat() if c.decided_at else None,
                    }
                )

            response = make_response(jsonify({"total": total, "candidates": result}), HTTPStatus.OK)
            response.headers[
                "Content-Disposition"
            ] = f'attachment; filename="dedupe_export_{run_id or "all"}_{status or "all"}.json"'
            return response

        else:  # CSV
            import csv
            import io

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "ID",
                    "Run ID",
                    "Score",
                    "Match Type",
                    "Decision",
                    "Primary Contact ID",
                    "Candidate Contact ID",
                    "Primary Name",
                    "Candidate Name",
                    "Created At",
                    "Decided At",
                ]
            )

            for c in candidates:
                primary_name = None
                if c.primary_contact:
                    primary_name = (
                        f"{c.primary_contact.first_name or ''} {c.primary_contact.last_name or ''}".strip() or None
                    )

                candidate_name = None
                if c.candidate_contact:
                    candidate_name = (
                        f"{c.candidate_contact.first_name or ''} {c.candidate_contact.last_name or ''}".strip() or None
                    )
                elif c.staging_row and c.staging_row.normalized_json:
                    staging_json = c.staging_row.normalized_json
                    first_name = staging_json.get("first_name", "") or ""
                    last_name = staging_json.get("last_name", "") or ""
                    candidate_name = f"{first_name} {last_name}".strip() or None

                writer.writerow(
                    [
                        c.id,
                        c.run_id,
                        float(c.score) if c.score else "",
                        c.match_type or "",
                        c.decision.value if isinstance(c.decision, DedupeDecision) else str(c.decision),
                        c.primary_contact_id or "",
                        c.candidate_contact_id or "",
                        primary_name or "",
                        candidate_name or "",
                        c.created_at.isoformat() if c.created_at else "",
                        c.decided_at.isoformat() if c.decided_at else "",
                    ]
                )

            response = make_response(output.getvalue(), HTTPStatus.OK)
            response.headers["Content-Type"] = "text/csv; charset=utf-8"
            response.headers[
                "Content-Disposition"
            ] = f'attachment; filename="dedupe_export_{run_id or "all"}_{status or "all"}.csv"'
            return response

    except Exception as exc:
        current_app.logger.exception("Failed to export dedupe summaries", exc_info=exc)
        return jsonify({"error": "Failed to export dedupe summaries."}), HTTPStatus.INTERNAL_SERVER_ERROR


@admin_importer_blueprint.get("/affiliations/quality")
@login_required
@permission_required("manage_imports", org_context=False)
def importer_affiliation_quality():
    """Display affiliation matching quality dashboard showing matched vs unmatched statistics."""
    if not _ensure_importer_enabled():
        return jsonify({"error": "Importer is disabled."}), HTTPStatus.NOT_FOUND

    try:
        # Get all affiliation import runs (runs that have staging_affiliations or clean_affiliations)
        # We identify affiliation runs by checking staging_affiliations and clean_affiliations tables directly
        from flask_app.models.importer.schema import CleanAffiliation, StagingAffiliation

        staging_run_ids = db.session.query(StagingAffiliation.run_id).distinct().all()
        clean_run_ids = db.session.query(CleanAffiliation.run_id).distinct().all()
        all_affiliation_run_ids = set([r[0] for r in staging_run_ids] + [r[0] for r in clean_run_ids])

        affiliation_runs = []
        if all_affiliation_run_ids:
            affiliation_runs = (
                db.session.query(ImportRun)
                .filter(ImportRun.id.in_(all_affiliation_run_ids))
                .order_by(ImportRun.started_at.desc())
                .limit(100)
                .all()
            )

        # Get overall statistics
        total_attempted = 0
        total_matched = 0
        total_unmatched_contact = 0
        total_unmatched_org = 0

        # Get skip records for affiliation imports
        skip_records = (
            db.session.query(ImportSkip)
            .filter(
                ImportSkip.entity_type == "affiliation",
                ImportSkip.skip_type == ImportSkipType.MISSING_REFERENCE,
            )
            .all()
        )

        # Process skip records to categorize by missing reference
        for skip in skip_records:
            details = skip.details_json or {}
            missing_ref = details.get("missing_reference", "")
            if missing_ref == "contact":
                total_unmatched_contact += 1
            elif missing_ref == "organization":
                total_unmatched_org += 1

        # Calculate totals from runs
        run_stats = []
        for run in affiliation_runs:
            # Count staging records
            staging_count = len(run.staging_affiliations) if run.staging_affiliations else 0
            clean_count = len(run.clean_affiliations) if run.clean_affiliations else 0

            # Count skips for this run
            run_skips = [s for s in skip_records if s.run_id == run.id]
            run_unmatched_contact = sum(
                1 for s in run_skips if (s.details_json or {}).get("missing_reference") == "contact"
            )
            run_unmatched_org = sum(
                1 for s in run_skips if (s.details_json or {}).get("missing_reference") == "organization"
            )
            run_unmatched_total = len(run_skips)

            # Count successfully matched (clean records that were loaded)
            run_matched = (
                sum(1 for ca in run.clean_affiliations if ca.core_contact_organization_id is not None)
                if run.clean_affiliations
                else 0
            )

            run_attempted = max(staging_count, clean_count)
            total_attempted += run_attempted
            total_matched += run_matched

            run_stats.append(
                {
                    "run_id": run.id,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "status": run.status.value,
                    "attempted": run_attempted,
                    "matched": run_matched,
                    "unmatched_contact": run_unmatched_contact,
                    "unmatched_org": run_unmatched_org,
                    "unmatched_total": run_unmatched_total,
                    "match_rate": (run_matched / run_attempted * 100) if run_attempted > 0 else 0,
                }
            )

        total_unmatched = total_unmatched_contact + total_unmatched_org
        overall_match_rate = (total_matched / total_attempted * 100) if total_attempted > 0 else 0

        return render_template(
            "admin/affiliation_quality.html",
            total_attempted=total_attempted,
            total_matched=total_matched,
            total_unmatched=total_unmatched,
            total_unmatched_contact=total_unmatched_contact,
            total_unmatched_org=total_unmatched_org,
            overall_match_rate=overall_match_rate,
            run_stats=run_stats,
            skip_records=skip_records[:100],  # Limit for display
        )

    except Exception as exc:
        current_app.logger.exception("Failed to load affiliation quality dashboard", exc_info=exc)
        flash("An error occurred while loading affiliation quality data.", "danger")
        return redirect(url_for("admin_importer.importer_dashboard"))


def register_importer_admin_routes(app):
    """
    Register importer admin routes when the importer feature flag is enabled.
    """

    if not is_importer_enabled(app):
        return

    if admin_importer_blueprint.name in app.blueprints:
        return

    app.register_blueprint(admin_importer_blueprint)
