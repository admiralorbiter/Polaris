"""
CLI scaffolding for importer commands.

Commands intentionally avoid heavy imports so they can load even when optional
dependencies are not installed.
"""

from __future__ import annotations

import json
from typing import Optional

import click
from celery import Celery
from celery.exceptions import TimeoutError as CeleryTimeoutError
from flask.cli import ScriptInfo

from flask_app.importer.celery_app import DEFAULT_QUEUE_NAME, get_celery_app
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
            "Importer is disabled via IMPORTER_ENABLED=false. "
            "Enable it to run importer CLI commands."
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
        raise click.ClickException(
            "Importer commands are unavailable because IMPORTER_ENABLED=false."
        )

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
@click.option("--source", required=True, help="Logical source identifier (e.g., csv, salesforce).")
@click.option("--file", "file_path", type=click.Path(exists=True, dir_okay=False), help="Path to input file (if applicable).")
@click.option("--dry-run", is_flag=True, help="Prepare the run without committing writes.")
@click.pass_context
def importer_run(ctx, source: str, file_path: Optional[str], dry_run: bool):
    """
    Placeholder importer execution command.

    Future work (IMP-10+) will route this into the real pipeline. For now we
    simply log the provided parameters so upcoming stories have a consistent CLI
    entry point.
    """
    info = ctx.ensure_object(ScriptInfo)
    app = info.load_app()
    if not is_importer_enabled(app):
        raise click.ClickException(
            "Importer is disabled; enable it via IMPORTER_ENABLED before running."
        )

    message = (
        "Importer run CLI placeholder invoked.\n"
        f"  source     : {source}\n"
        f"  file       : {file_path or '(none)'}\n"
        f"  dry_run    : {dry_run}\n"
        "No actions were taken. Implement pipeline logic in future sprints."
    )
    click.echo(message)

