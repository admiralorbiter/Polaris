"""
Importer Celery tasks.

These tasks are intentionally lightweight placeholders; future IMP tickets will
extend them with real pipeline orchestration. They provide the scaffolding
needed for worker health checks and integration tests today.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from celery import shared_task


@shared_task(name="importer.healthcheck", bind=True)
def importer_healthcheck(self) -> dict[str, Any]:
    """
    Simple heartbeat task used by worker health checks.
    """
    now = datetime.now(timezone.utc)
    return {
        "status": "ok",
        "timestamp": now.isoformat(),
        "worker_hostname": self.request.hostname,
        "app_version": getattr(self.app, "user_options", {}).get("version"),
    }


@shared_task(name="importer.pipeline.noop_ingest", bind=True)
def noop_ingest(self, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Placeholder pipeline task. It echoes the payload so downstream steps can
    validate Celery wiring without touching databases.
    """
    payload = payload or {}
    return {
        "received": payload,
        "queue": self.request.delivery_info.get("routing_key"),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

