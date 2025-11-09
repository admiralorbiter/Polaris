"""
Importer Celery tasks.

These tasks are intentionally lightweight placeholders; future IMP tickets will
extend them with real pipeline orchestration. They provide the scaffolding
needed for worker health checks and integration tests today.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from celery import shared_task

from flask_app.importer.pipeline import run_minimal_dq, stage_volunteers_from_csv
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus


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


@shared_task(name="importer.pipeline.ingest_csv", bind=True)
def ingest_csv(
    self, *, run_id: int, file_path: str, dry_run: bool = False, source_system: str = "csv"
) -> dict[str, Any]:
    """
    Execute the CSV ingest pipeline asynchronously via the importer worker.
    """

    run = ImportRun.query.get(run_id)
    if run is None:
        raise ValueError(f"Import run {run_id} not found.")

    run.status = ImportRunStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    db.session.commit()

    path = Path(file_path)
    if not path.exists():
        run.status = ImportRunStatus.FAILED
        run.error_summary = f"CSV file not found: {file_path}"
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            staging_summary = stage_volunteers_from_csv(
                run,
                handle,
                source_system=source_system,
                dry_run=dry_run,
            )
        dq_summary = run_minimal_dq(run, dry_run=dry_run, csv_rows=staging_summary.dry_run_rows)
        run.status = ImportRunStatus.SUCCEEDED
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        return {
            "run_id": run_id,
            "rows_processed": staging_summary.rows_processed,
            "rows_staged": staging_summary.rows_staged,
            "rows_skipped_blank": staging_summary.rows_skipped_blank,
            "dry_run": staging_summary.dry_run,
            "dq_rows_evaluated": dq_summary.rows_evaluated,
            "dq_rows_validated": dq_summary.rows_validated,
            "dq_rows_quarantined": dq_summary.rows_quarantined,
            "dq_rule_counts": dict(dq_summary.rule_counts),
        }
    except Exception as exc:  # pragma: no cover - defensive logging path
        db.session.rollback()
        recovery_run = ImportRun.query.get(run_id)
        if recovery_run is None:
            raise
        recovery_run.status = ImportRunStatus.FAILED
        recovery_run.error_summary = str(exc)
        recovery_run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        raise
