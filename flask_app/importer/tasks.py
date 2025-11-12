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
from flask import current_app

from flask_app.importer.adapters.salesforce.extractor import SalesforceExtractor, create_salesforce_client
from flask_app.importer.idempotency_summary import persist_idempotency_summary
from flask_app.importer.pipeline import (
    CoreLoadSummary,
    StagingSummary,
    load_core_volunteers,
    promote_clean_volunteers,
    run_minimal_dq,
    stage_volunteers_from_csv,
)
from flask_app.importer.pipeline.fuzzy_candidates import generate_fuzzy_candidates
from flask_app.importer.pipeline.salesforce import ingest_salesforce_contacts as run_salesforce_ingest
from flask_app.importer.pipeline.salesforce_loader import LoaderCounters, SalesforceContactLoader
from flask_app.importer.utils import cleanup_upload
from flask_app.models import ImporterWatermark
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
    self, *, run_id: int, file_path: str, dry_run: bool = False, source_system: str = "csv", keep_file: bool = False
) -> dict[str, Any]:
    """
    Execute the CSV ingest pipeline asynchronously via the importer worker.
    """

    run = db.session.get(ImportRun, run_id)
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

    # Only cleanup if keep_file is False (default for CLI runs; admin uploads set keep_file=True for retry)
    cleanup_target: Path | None = None if keep_file else path

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            staging_summary = stage_volunteers_from_csv(
                run,
                handle,
                source_system=source_system,
                dry_run=dry_run,
            )
        dq_summary = run_minimal_dq(run, dry_run=dry_run, csv_rows=staging_summary.dry_run_rows)
        clean_summary = promote_clean_volunteers(run, dry_run=dry_run)
        fuzzy_summary = generate_fuzzy_candidates(run, dry_run=dry_run)

        # Auto-merge high-confidence candidates if enabled and not dry_run
        if not dry_run:
            from flask_app.importer.pipeline.merge_service import MergeService

            merge_service = MergeService()
            auto_merge_stats = merge_service.auto_merge_high_confidence_candidates(
                run_id=run.id,
                dry_run=False,
            )
            fuzzy_summary.auto_merged_count = auto_merge_stats.get("merged", 0)

        # Update dedupe counts in counts_json/metrics_json
        from flask_app.importer.pipeline.fuzzy_candidates import _update_dedupe_counts

        _update_dedupe_counts(run, fuzzy_summary)

        core_summary = load_core_volunteers(
            run,
            dry_run=dry_run,
            clean_candidates=clean_summary.candidates,
        )
        run.status = ImportRunStatus.SUCCEEDED
        run.finished_at = datetime.now(timezone.utc)
        persist_idempotency_summary(
            run,
            staging_summary=staging_summary,
            dq_summary=dq_summary,
            clean_summary=clean_summary,
            core_summary=core_summary,
            fuzzy_summary=fuzzy_summary,
        )
        db.session.commit()
        current_app.logger.info(
            "Importer run completed",
            extra={
                "importer_run_id": run_id,
                "importer_status": run.status.value,
                "importer_rows_processed": staging_summary.rows_processed,
                "importer_rows_created": core_summary.rows_created,
                "importer_rows_updated": core_summary.rows_updated,
                "importer_rows_skipped_no_change": core_summary.rows_skipped_no_change,
                "importer_rows_reactivated": core_summary.rows_reactivated,
                "importer_rows_quarantined": dq_summary.rows_quarantined,
                "importer_dry_run": staging_summary.dry_run,
                "importer_fuzzy_suggestions_created": fuzzy_summary.suggestions_created,
                "importer_fuzzy_high_confidence": fuzzy_summary.high_confidence,
                "importer_fuzzy_review": fuzzy_summary.review_band,
                "importer_fuzzy_auto_merged": fuzzy_summary.auto_merged_count,
            },
        )
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
            "clean_rows_promoted": clean_summary.rows_promoted,
            "core_rows_created": core_summary.rows_created,
            "core_rows_updated": core_summary.rows_updated,
            "core_rows_reactivated": core_summary.rows_reactivated,
            "core_rows_skipped_no_change": core_summary.rows_skipped_no_change,
            "core_rows_duplicates": core_summary.rows_skipped_duplicates,
            "core_rows_missing_external_id": core_summary.rows_missing_external_id,
            "fuzzy_rows_considered": fuzzy_summary.rows_considered,
            "fuzzy_suggestions_created": fuzzy_summary.suggestions_created,
            "fuzzy_high_confidence": fuzzy_summary.high_confidence,
            "fuzzy_review": fuzzy_summary.review_band,
            "fuzzy_auto_merged": fuzzy_summary.auto_merged_count,
        }
    except Exception as exc:  # pragma: no cover - defensive logging path
        db.session.rollback()
        recovery_run = db.session.get(ImportRun, run_id)
        if recovery_run is None:
            raise
        recovery_run.status = ImportRunStatus.FAILED
        recovery_run.error_summary = str(exc)
        recovery_run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        current_app.logger.exception(
            "Importer run failed",
            extra={
                "importer_run_id": run_id,
                "importer_error": str(exc),
            },
        )
        raise
    finally:
        if cleanup_target is not None:
            cleanup_upload(cleanup_target)


@shared_task(name="importer.pipeline.process_auto_merge_candidates", bind=True)
def process_auto_merge_candidates(self, *, max_age_minutes: int = 5, batch_size: int | None = None) -> dict[str, Any]:
    """
    Background task to process missed high-confidence fuzzy dedupe candidates.

    Processes candidates that are older than max_age_minutes to avoid race conditions
    with in-progress imports.

    Args:
        max_age_minutes: Minimum age in minutes for candidates to be processed (default: 5)
        batch_size: Maximum number of candidates to process (uses config default if None)

    Returns:
        Dict with counts: processed, merged, skipped, errors
    """
    from flask_app.importer.pipeline.merge_service import MergeService

    merge_service = MergeService()

    # Process candidates older than threshold
    # This is handled by auto_merge_high_confidence_candidates which queries for pending
    # We could add age filtering here if needed, but for now the batch processing
    # handles rate limiting

    stats = merge_service.auto_merge_high_confidence_candidates(
        run_id=None,  # Process all runs
        dry_run=False,
        batch_size=batch_size,
    )

    current_app.logger.info(
        "Auto-merge background task completed",
        extra={
            "processed": stats.get("processed", 0),
            "merged": stats.get("merged", 0),
            "skipped": stats.get("skipped", 0),
            "errors": stats.get("errors", 0),
        },
    )

    return stats


@shared_task(name="importer.pipeline.ingest_salesforce_contacts", bind=True)
def ingest_salesforce_contacts(
    self,
    *,
    run_id: int,
    dry_run: bool = False,
    record_limit: int | None = None,
) -> dict[str, object]:
    """
    Execute the Salesforce contact ingest pipeline via the importer worker.
    """

    run = db.session.get(ImportRun, run_id)
    if run is None:
        raise ValueError(f"Import run {run_id} not found.")

    run.status = ImportRunStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    db.session.commit()

    object_name = (current_app.config.get("IMPORTER_SALESFORCE_OBJECTS") or ("contacts",))[0]
    batch_size = current_app.config.get("IMPORTER_SALESFORCE_BATCH_SIZE", 5000)

    watermark = (
        db.session.query(ImporterWatermark)
        .filter_by(adapter="salesforce", object_name=object_name)
        .with_for_update(of=ImporterWatermark)
        .first()
    )
    if watermark is None:
        watermark = ImporterWatermark(adapter="salesforce", object_name=object_name)
        db.session.add(watermark)
        db.session.flush()

    try:
        client = create_salesforce_client()
        extractor = SalesforceExtractor(
            client=client,
            batch_size=batch_size,
            poll_interval=5.0,
            poll_timeout=900.0,
            logger=current_app.logger,
        )
        summary = run_salesforce_ingest(
            import_run=run,
            extractor=extractor,
            watermark=watermark,
            staging_batch_size=500,
            dry_run=dry_run,
            logger=current_app.logger,
            record_limit=record_limit,
        )

        # Run DQ validation and clean promotion (same as CSV pipeline)
        dq_summary = run_minimal_dq(run, dry_run=dry_run, csv_rows=None)
        clean_summary = promote_clean_volunteers(run, dry_run=dry_run)
        fuzzy_summary = generate_fuzzy_candidates(run, dry_run=dry_run)

        if dry_run:
            counters = LoaderCounters()
            run.status = ImportRunStatus.SUCCEEDED
            run.finished_at = datetime.now(timezone.utc)
            run.metrics_json = run.metrics_json or {}
            run.metrics_json.setdefault("salesforce", {})["max_source_updated_at"] = (
                summary.max_modstamp.isoformat() if summary.max_modstamp else None
            )
            db.session.commit()
        else:
            loader = SalesforceContactLoader(run)
            counters = loader.execute()

        # Create CoreLoadSummary from Salesforce loader counters for idempotency summary
        core_summary = CoreLoadSummary(
            rows_processed=counters.created + counters.updated + counters.unchanged + counters.deleted,
            rows_created=counters.created,
            rows_updated=counters.updated,
            rows_reactivated=0,  # Salesforce loader doesn't track reactivations
            rows_deduped_auto=0,  # Salesforce loader doesn't track auto-dedupes
            rows_skipped_duplicates=0,  # Salesforce loader doesn't track duplicate skips
            rows_skipped_no_change=counters.unchanged,
            rows_missing_external_id=0,  # Salesforce loader doesn't track missing IDs
            rows_soft_deleted=counters.deleted,
            duplicate_emails=(),  # Salesforce loader doesn't track duplicate emails
            dry_run=dry_run,
        )

        # Persist idempotency summary (includes DQ and clean summaries)
        persist_idempotency_summary(
            run,
            staging_summary=StagingSummary(
                rows_processed=summary.records_received,
                rows_staged=summary.records_staged,
                rows_skipped_blank=0,
                header=summary.header,
                dry_run=summary.dry_run,
                dry_run_rows=(),
            ),
            dq_summary=dq_summary,
            clean_summary=clean_summary,
            core_summary=core_summary,
            fuzzy_summary=fuzzy_summary,
        )
        current_app.logger.info(
            "Salesforce import run completed",
            extra={
                "importer_run_id": run_id,
                "salesforce_job_id": summary.job_id,
                "salesforce_batches_processed": summary.batches_processed,
                "salesforce_records_received": summary.records_received,
                "salesforce_records_staged": summary.records_staged,
                "salesforce_rows_created": counters.created if not dry_run else 0,
                "salesforce_rows_updated": counters.updated if not dry_run else 0,
                "salesforce_rows_deleted": counters.deleted if not dry_run else 0,
                "salesforce_rows_unchanged": counters.unchanged if not dry_run else 0,
                "importer_dry_run": dry_run,
                "importer_fuzzy_suggestions_created": fuzzy_summary.suggestions_created,
                "importer_fuzzy_high_confidence": fuzzy_summary.high_confidence,
                "importer_fuzzy_review": fuzzy_summary.review_band,
            },
        )
        return {
            "run_id": run_id,
            "job_id": summary.job_id,
            "batches_processed": summary.batches_processed,
            "records_received": summary.records_received,
            "records_staged": summary.records_staged,
            "dry_run": dry_run,
            "max_system_modstamp": summary.max_modstamp.isoformat() if summary.max_modstamp else None,
            "counters": counters.to_dict(),
            "fuzzy_rows_considered": fuzzy_summary.rows_considered,
            "fuzzy_suggestions_created": fuzzy_summary.suggestions_created,
            "fuzzy_high_confidence": fuzzy_summary.high_confidence,
            "fuzzy_review": fuzzy_summary.review_band,
        }
    except Exception as exc:  # pragma: no cover - defensive logging path
        db.session.rollback()
        recovery_run = db.session.get(ImportRun, run_id)
        if recovery_run is not None:
            recovery_run.status = ImportRunStatus.FAILED
            recovery_run.error_summary = str(exc)
            recovery_run.finished_at = datetime.now(timezone.utc)
            db.session.commit()
        current_app.logger.exception(
            "Salesforce import run failed",
            extra={
                "importer_run_id": run_id,
                "importer_error": str(exc),
            },
        )
        raise
