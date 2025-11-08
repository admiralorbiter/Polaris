"""
CLI scaffolding for importer commands.

Commands intentionally avoid heavy imports so they can load even when optional
dependencies are not installed.
"""

from __future__ import annotations

import click
from flask.cli import ScriptInfo

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

