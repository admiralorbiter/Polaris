"""
CLI scaffolding for importer commands.

Commands intentionally avoid heavy imports so they can load even when optional
dependencies are not installed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from celery import Celery
from celery.exceptions import TimeoutError as CeleryTimeoutError
from flask.cli import ScriptInfo

from flask_app.importer.celery_app import DEFAULT_QUEUE_NAME, get_celery_app
from flask_app.importer.pipeline import StagingSummary, stage_volunteers_from_csv
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
) -> StagingSummary:
    run_id = run.id
    run.status = ImportRunStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    db.session.commit()

    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            summary = stage_volunteers_from_csv(
                run,
                handle,
                source_system=source_system,
                dry_run=dry_run,
            )
        run.status = ImportRunStatus.SUCCEEDED
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        return summary
    except Exception as exc:
        db.session.rollback()
        recovery_run = ImportRun.query.get(run_id)
        if recovery_run is None:
            raise click.ClickException(f"Import run {run_id} failed and could not be recovered.") from exc
        recovery_run.status = ImportRunStatus.FAILED
        recovery_run.error_summary = str(exc)
        recovery_run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        raise click.ClickException(f"Import run {run_id} failed: {exc}") from exc


def _format_summary(run: ImportRun, summary: StagingSummary) -> str:
    header_preview = ", ".join(summary.header) if summary.header else "n/a"
    status_value = run.status.value if hasattr(run.status, "value") else str(run.status)
    return (
        f"Run {run.id} completed with status {status_value} (dry_run={summary.dry_run}).\n"
        f"  rows_processed : {summary.rows_processed}\n"
        f"  rows_staged    : {summary.rows_staged}\n"
        f"  rows_skipped   : {summary.rows_skipped_blank}\n"
        f"  headers        : {header_preview}"
    )


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
    "--queues",
    default=DEFAULT_QUEUE_NAME,
    show_default=True,
    help="Comma-separated queue list to consume.",
)
@click.pass_context
def worker_run(ctx, loglevel: str, concurrency: Optional[int], queues: str):
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

    click.echo(f"Starting importer worker (queues: {queues}, loglevel: {loglevel})")
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
@click.option("--enqueue", is_flag=True, help="Send the run to the importer worker instead of running inline.")
@click.pass_context
def importer_run(ctx, source: str, file_path: Optional[Path], dry_run: bool, enqueue: bool):
    """Execute an importer run for the provided source."""
    info = ctx.ensure_object(ScriptInfo)
    app = info.load_app()
    if not is_importer_enabled(app):
        raise click.ClickException("Importer is disabled; enable it via IMPORTER_ENABLED before running.")

    normalized_source, csv_path = _prepare_source_inputs(source, file_path)

    run = ImportRun(
        source=normalized_source,
        adapter=normalized_source,
        dry_run=dry_run,
        status=ImportRunStatus.PENDING,
        notes=f"CLI ingest from {csv_path}",
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.id

    if enqueue:
        celery_app = _resolve_celery(app)
        async_result = celery_app.send_task(
            "importer.pipeline.ingest_csv",
            kwargs={
                "run_id": run_id,
                "file_path": str(csv_path),
                "dry_run": dry_run,
                "source_system": normalized_source,
            },
        )
        click.echo(f"Queued importer run {run_id} (task id: {async_result.id})")
        return

    run = ImportRun.query.get(run_id)
    if run is None:
        raise click.ClickException(f"Import run {run_id} could not be reloaded before execution.")

    summary = _execute_csv_inline(
        run,
        csv_path,
        dry_run=dry_run,
        source_system=normalized_source,
    )
    click.echo(_format_summary(run, summary))
