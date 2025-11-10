"""
CLI scaffolding for importer commands.

Commands intentionally avoid heavy imports so they can load even when optional
dependencies are not installed.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import click
from celery import Celery
from celery.exceptions import TimeoutError as CeleryTimeoutError
from flask.cli import ScriptInfo

from flask_app.importer.celery_app import DEFAULT_QUEUE_NAME, get_celery_app
from flask_app.importer.pipeline import (
    CleanPromotionSummary,
    CoreLoadSummary,
    DQProcessingSummary,
    StagingSummary,
    load_core_volunteers,
    promote_clean_volunteers,
    run_minimal_dq,
    stage_volunteers_from_csv,
)
from flask_app.importer.utils import cleanup_upload, resolve_upload_directory
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus
from flask_app.utils.importer import get_importer_adapters, is_importer_enabled


@click.group(name="importer", invoke_without_command=True)
@click.pass_context
def importer_cli(ctx):
    """
    Importer management commands (placeholder).

    Displays configured adapters when invoked without a subcommand.
    """
    info = ctx.ensure_object(ScriptInfo)
    app = info.load_app()
    if not is_importer_enabled(app):
        raise click.ClickException(
            "Importer is disabled via IMPORTER_ENABLED=false. " "Enable it to run importer CLI commands."
        )
    if ctx.invoked_subcommand is None:
        adapters = get_importer_adapters(app)
        if not adapters:
            click.echo("No importer adapters configured.")
        else:
            click.echo("Enabled importer adapters:")
            for adapter in adapters:
                click.echo(f"  - {adapter}")


def get_disabled_importer_group() -> click.Group:
    """
    Return a minimal command group that informs the operator the importer is disabled.
    """

    @click.group(name="importer", invoke_without_command=True)
    def disabled_group():
        raise click.ClickException("Importer commands are unavailable because IMPORTER_ENABLED=false.")

    return disabled_group


def _resolve_celery(app) -> Optional[Celery]:
    """
    Retrieve the registered Celery instance, raising a helpful error if missing.
    """
    celery_app = get_celery_app(app)
    if celery_app is None:
        raise click.ClickException(
            "Importer Celery app is unavailable. Ensure IMPORTER_ENABLED=true and the "
            "importer package initialises before running worker commands."
        )
    return celery_app


def _prepare_source_inputs(source: str, file_path: Optional[Path]) -> tuple[str, Path]:
    normalized_source = source.lower()
    if normalized_source != "csv":
        raise click.ClickException(f"Source '{source}' is not supported yet. Only 'csv' is implemented for IMP-10.")
    if file_path is None:
        raise click.ClickException("CSV source requires the --file option.")
    return normalized_source, file_path.resolve()


def _execute_csv_inline(
    run: ImportRun,
    csv_path: Path,
    *,
    dry_run: bool,
    source_system: str,
) -> tuple[StagingSummary, DQProcessingSummary, CleanPromotionSummary, CoreLoadSummary]:
    run_id = run.id
    run.status = ImportRunStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    db.session.commit()

    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            staging_summary = stage_volunteers_from_csv(
                run,
                handle,
                source_system=source_system,
                dry_run=dry_run,
            )
        dq_summary = run_minimal_dq(run, dry_run=dry_run, csv_rows=staging_summary.dry_run_rows)
        clean_summary = promote_clean_volunteers(run, dry_run=dry_run)
        core_summary = load_core_volunteers(
            run,
            dry_run=dry_run,
            clean_candidates=clean_summary.candidates,
        )
        run.status = ImportRunStatus.SUCCEEDED
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        return staging_summary, dq_summary, clean_summary, core_summary
    except Exception as exc:
        db.session.rollback()
        recovery_run = db.session.get(ImportRun, run_id)
        if recovery_run is None:
            raise click.ClickException(f"Import run {run_id} failed and could not be recovered.") from exc
        recovery_run.status = ImportRunStatus.FAILED
        recovery_run.error_summary = str(exc)
        recovery_run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        raise click.ClickException(f"Import run {run_id} failed: {exc}") from exc


def _format_summary(
    run: ImportRun,
    staging_summary: StagingSummary,
    dq_summary: DQProcessingSummary,
    clean_summary: CleanPromotionSummary,
    core_summary: CoreLoadSummary,
) -> str:
    clean_promoted_value = clean_summary.rows_promoted if not clean_summary.dry_run else clean_summary.rows_considered
    header_preview = ", ".join(staging_summary.header) if staging_summary.header else "n/a"
    status_value = run.status.value if hasattr(run.status, "value") else str(run.status)
    rule_counts = dq_summary.rule_counts
    rule_counts_display = (
        ", ".join(f"{code}={count}" for code, count in sorted(rule_counts.items())) if rule_counts else "none"
    )
    return (
        f"Run {run.id} completed with status {status_value} (dry_run={staging_summary.dry_run}).\n"
        f"  rows_processed     : {staging_summary.rows_processed}\n"
        f"  rows_staged        : {staging_summary.rows_staged}\n"
        f"  rows_skipped       : {staging_summary.rows_skipped_blank}\n"
        f"  headers            : {header_preview}\n"
        f"  dq_rows_evaluated  : {dq_summary.rows_evaluated}\n"
        f"  dq_rows_validated  : {dq_summary.rows_validated}\n"
        f"  dq_rows_quarantined: {dq_summary.rows_quarantined}\n"
        f"  dq_rule_counts     : {rule_counts_display}\n"
        f"  clean_promoted     : {clean_promoted_value}\n"
        f"  clean_skipped      : {clean_summary.rows_skipped}\n"
        f"  core_created       : {core_summary.rows_created}\n"
        f"  core_updated       : {core_summary.rows_updated}\n"
        f"  core_reactivated   : {core_summary.rows_reactivated}\n"
        f"  core_no_change     : {core_summary.rows_skipped_no_change}\n"
        f"  core_duplicates    : {core_summary.rows_skipped_duplicates}\n"
        f"  core_missing_ids   : {core_summary.rows_missing_external_id}"
    )


def _build_summary_payload(
    run: ImportRun,
    staging_summary: StagingSummary,
    dq_summary: DQProcessingSummary,
    clean_summary: CleanPromotionSummary,
    core_summary: CoreLoadSummary,
) -> dict[str, object]:
    return {
        "run_id": run.id,
        "dry_run": staging_summary.dry_run,
        "staging": {
            "rows_processed": staging_summary.rows_processed,
            "rows_staged": staging_summary.rows_staged,
            "rows_skipped_blank": staging_summary.rows_skipped_blank,
            "headers": list(staging_summary.header),
            "dry_run": staging_summary.dry_run,
        },
        "dq": {
            "rows_evaluated": dq_summary.rows_evaluated,
            "rows_validated": dq_summary.rows_validated,
            "rows_quarantined": dq_summary.rows_quarantined,
            "rule_counts": dict(dq_summary.rule_counts),
            "dry_run": dq_summary.dry_run,
        },
        "clean": {
            "rows_considered": clean_summary.rows_considered,
            "rows_promoted": clean_summary.rows_promoted,
            "rows_skipped": clean_summary.rows_skipped,
            "dry_run": clean_summary.dry_run,
        },
        "core": {
            "rows_processed": core_summary.rows_processed,
            "rows_created": core_summary.rows_created,
            "rows_updated": core_summary.rows_updated,
            "rows_reactivated": core_summary.rows_reactivated,
            "rows_changed": core_summary.rows_changed,
            "rows_skipped_duplicates": core_summary.rows_skipped_duplicates,
            "rows_skipped_no_change": core_summary.rows_skipped_no_change,
            "rows_missing_external_id": core_summary.rows_missing_external_id,
            "rows_soft_deleted": core_summary.rows_soft_deleted,
            "duplicate_emails": list(core_summary.duplicate_emails),
            "dry_run": core_summary.dry_run,
        },
    }


@importer_cli.group(name="worker")
@click.pass_context
def worker_group(ctx):
    """Manage the importer background worker."""
    info = ctx.ensure_object(ScriptInfo)
    app = info.load_app()
    state = app.extensions.get("importer", {})
    if not state.get("worker_enabled") and not app.config.get("IMPORTER_WORKER_ENABLED"):
        click.echo(
            "Warning: IMPORTER_WORKER_ENABLED is false. Commands will still run, "
            "but enable the flag to surface accurate health status.",
            err=True,
        )


@worker_group.command("run")
@click.option("--loglevel", default="info", show_default=True)
@click.option("--concurrency", type=int, help="Number of worker processes/threads.")
@click.option(
    "--pool",
    type=str,
    help="Celery pool implementation (e.g., 'prefork', 'solo', 'threads').",
)
@click.option(
    "--queues",
    default=DEFAULT_QUEUE_NAME,
    show_default=True,
    help="Comma-separated queue list to consume.",
)
@click.pass_context
def worker_run(ctx, loglevel: str, concurrency: Optional[int], pool: Optional[str], queues: str):
    """
    Start the Celery worker in the current process.
    """
    info = ctx.ensure_object(ScriptInfo)
    app = info.load_app()
    celery_app = _resolve_celery(app)

    state = app.extensions.get("importer", {})
    if state is not None:
        state["worker_enabled"] = True

    argv = [
        "worker",
        "--loglevel",
        loglevel,
        "-Q",
        queues,
    ]
    if concurrency:
        argv.extend(["--concurrency", str(concurrency)])
    if pool:
        argv.extend(["--pool", pool])

    pool_msg = f", pool: {pool}" if pool else ""
    click.echo(f"Starting importer worker (queues: {queues}, loglevel: {loglevel}{pool_msg})")
    try:
        celery_app.worker_main(argv=argv)
    except KeyboardInterrupt:
        click.echo("Worker shutdown requested. Exiting...")


@worker_group.command("ping")
@click.option("--timeout", default=10.0, show_default=True, help="Seconds to wait for a response.")
@click.pass_context
def worker_ping(ctx, timeout: float):
    """
    Validate worker connectivity by executing the heartbeat task.
    """
    info = ctx.ensure_object(ScriptInfo)
    app = info.load_app()
    celery_app = _resolve_celery(app)
    task = celery_app.tasks.get("importer.healthcheck")
    if task is None:
        raise click.ClickException("Heartbeat task 'importer.healthcheck' is not registered.")

    result = task.apply_async()
    try:
        payload = result.get(timeout=timeout)
    except CeleryTimeoutError as exc:
        raise click.ClickException(f"Worker did not respond within {timeout}s") from exc
    except Exception as exc:  # pragma: no cover - surfacing unexpected errors
        raise click.ClickException(f"Worker ping failed: {exc}") from exc

    click.echo(json.dumps(payload, indent=2))


@importer_cli.command("run")
@click.option("--source", required=True, help="Logical source identifier (currently only 'csv' is supported).")
@click.option(
    "--file",
    "file_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="Path to input file (required for csv source).",
)
@click.option("--dry-run", is_flag=True, help="Execute pipeline without writing to staging tables.")
@click.option(
    "--inline/--no-inline",
    default=False,
    help="Run inline within the CLI process instead of queueing via Celery.",
)
@click.option(
    "--summary-json",
    is_flag=True,
    help="Emit a machine-readable summary payload after completion (inline runs only).",
)
@click.pass_context
def importer_run(
    ctx,
    source: str,
    file_path: Optional[Path],
    dry_run: bool,
    inline: bool,
    summary_json: bool,
):
    """Execute an importer run for the provided source."""
    info = ctx.ensure_object(ScriptInfo)
    app = info.load_app()
    if not is_importer_enabled(app):
        raise click.ClickException("Importer is disabled; enable it via IMPORTER_ENABLED before running.")

    normalized_source, csv_path = _prepare_source_inputs(source, file_path)

    if summary_json and not inline:
        raise click.ClickException("--summary-json is only available for --inline runs.")

    run = ImportRun(
        source=normalized_source,
        adapter=normalized_source,
        dry_run=dry_run,
        status=ImportRunStatus.PENDING,
        notes=f"CLI ingest from {csv_path}",
        counts_json={},
        metrics_json={},
        ingest_params_json={
            "file_path": str(csv_path),
            "source_system": normalized_source,
            "dry_run": dry_run,
            "keep_file": False,  # CLI runs typically use existing files, no need to retain
        },
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.id

    if not inline:
        celery_app = _resolve_celery(app)
        try:
            async_result = celery_app.send_task(
                "importer.pipeline.ingest_csv",
                kwargs={
                    "run_id": run_id,
                    "file_path": str(csv_path),
                    "dry_run": dry_run,
                    "source_system": normalized_source,
                    "keep_file": False,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive path
            recovery_run = db.session.get(ImportRun, run_id)
            if recovery_run is not None:
                recovery_run.status = ImportRunStatus.FAILED
                recovery_run.error_summary = str(exc)
                recovery_run.finished_at = datetime.now(timezone.utc)
                db.session.commit()
            raise click.ClickException(f"Failed to enqueue importer run {run_id}: {exc}") from exc

        payload = {
            "run_id": run_id,
            "task_id": async_result.id,
            "status": "queued",
            "dry_run": dry_run,
            "source": normalized_source,
        }
        app.logger.info(
            "Importer run queued via CLI",
            extra={
                "importer_run_id": run_id,
                "importer_task_id": async_result.id,
                "importer_source": normalized_source,
                "importer_dry_run": dry_run,
            },
        )
        click.echo(json.dumps(payload))
        return

    run = db.session.get(ImportRun, run_id)
    if run is None:
        raise click.ClickException(f"Import run {run_id} could not be reloaded before execution.")

    staging_summary, dq_summary, clean_summary, core_summary = _execute_csv_inline(
        run,
        csv_path,
        dry_run=dry_run,
        source_system=normalized_source,
    )
    click.echo(_format_summary(run, staging_summary, dq_summary, clean_summary, core_summary))
    if summary_json:
        click.echo(
            json.dumps(
                _build_summary_payload(run, staging_summary, dq_summary, clean_summary, core_summary),
                indent=2,
                sort_keys=True,
            )
        )


@importer_cli.command("cleanup-uploads")
@click.option(
    "--max-age-hours",
    default=72,
    show_default=True,
    type=int,
    help="Remove importer uploads older than the specified number of hours.",
)
@click.pass_context
def importer_cleanup_uploads(ctx, max_age_hours: int):
    """
    Delete stale importer upload files from the configured storage directory.
    """

    info = ctx.ensure_object(ScriptInfo)
    app = info.load_app()
    if not is_importer_enabled(app):
        raise click.ClickException("Importer is disabled; no uploads to clean up.")

    uploads_dir = resolve_upload_directory(app)
    if not uploads_dir.exists():
        click.echo(f"No upload directory found at {uploads_dir}. Nothing to clean.")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    removed = 0
    for path in uploads_dir.iterdir():
        if not path.is_file():
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except FileNotFoundError:  # pragma: no cover - race condition
            continue
        if modified < cutoff:
            cleanup_upload(path)
            removed += 1

    click.echo(f"Removed {removed} upload file(s) older than {max_age_hours} hours from {uploads_dir}.")


def _retry_import_run(app, run: ImportRun) -> tuple[str, str]:
    """
    Retry an import run by re-enqueueing it with stored parameters.

    Returns:
        tuple[str, str]: (task_id, status_message)
    """
    params = run.ingest_params_json
    if not params:
        raise click.ClickException(
            f"Import run {run.id} cannot be retried: ingest parameters not stored. "
            "This run was created before retry support was added."
        )

    file_path = params.get("file_path")
    if not file_path:
        raise click.ClickException(f"Import run {run.id} cannot be retried: file_path missing from stored parameters.")

    path = Path(file_path)
    if not path.exists():
        raise click.ClickException(
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

    celery_app = get_celery_app(app)
    if celery_app is None:
        raise click.ClickException("Importer worker is not configured; cannot enqueue retry.")

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

    app.logger.info(
        "Import run retried via CLI",
        extra={
            "importer_run_id": run.id,
            "importer_task_id": async_result.id,
            "importer_source": source_system,
        },
    )

    return async_result.id, "queued"


@importer_cli.command("retry")
@click.option("--run-id", required=True, type=int, help="ID of the import run to retry.")
@click.pass_context
def importer_retry(ctx, run_id: int):
    """Retry a failed or pending import run using stored parameters."""
    info = ctx.ensure_object(ScriptInfo)
    app = info.load_app()
    if not is_importer_enabled(app):
        raise click.ClickException("Importer is disabled; enable it via IMPORTER_ENABLED before retrying.")

    run = db.session.get(ImportRun, run_id)
    if run is None:
        raise click.ClickException(f"Import run {run_id} not found.")

    try:
        task_id, status = _retry_import_run(app, run)
        payload = {
            "run_id": run_id,
            "task_id": task_id,
            "status": status,
        }
        click.echo(json.dumps(payload))
    except click.ClickException:
        raise
    except Exception as exc:  # pragma: no cover - defensive path
        raise click.ClickException(f"Failed to retry import run {run_id}: {exc}") from exc
