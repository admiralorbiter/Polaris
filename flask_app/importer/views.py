"""
Blueprint stubs for importer UI.
"""

from __future__ import annotations

from celery.exceptions import TimeoutError as CeleryTimeoutError
from flask import Blueprint, current_app, jsonify, request

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

