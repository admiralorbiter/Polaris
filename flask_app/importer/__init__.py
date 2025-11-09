"""
Importer feature package scaffolding.

Provides conditional blueprint and CLI registration along with adapter registry
validation while remaining lightweight when the importer is disabled.
"""

from __future__ import annotations

from typing import Any, Iterable, Tuple

from flask import Flask

from flask_app.utils.importer import get_importer_adapters, is_importer_enabled

from .celery_app import ensure_celery_app, get_celery_app
from .cli import get_disabled_importer_group, importer_cli
from .pipeline.run_service import ImportRunService, RunFilters
from .registry import AdapterDescriptor, get_adapter_registry, resolve_adapters
from .views import importer_blueprint

IMPORTER_EXTENSION_KEY = "importer"

__all__ = [
    "init_importer",
    "IMPORTER_EXTENSION_KEY",
    "get_celery_app",
    "ImportRunService",
    "RunFilters",
]


def _ensure_extension_state(app: Flask) -> dict:
    state = app.extensions.setdefault(
        IMPORTER_EXTENSION_KEY,
        {
            "enabled": False,
            "configured_adapters": (),
            "active_adapters": (),
            "menu_items": (),
            "worker_enabled": False,
            "celery_app": None,
            "_context_registered": False,
        },
    )
    return state


def _register_template_context(app: Flask, state: dict[str, Any]) -> None:
    if state.get("_context_registered"):
        return

    @app.context_processor
    def importer_context():
        enabled_flag = bool(app.config.get("IMPORTER_ENABLED", False))
        extension_state = app.extensions.get(IMPORTER_EXTENSION_KEY, {})
        return {
            "importer_enabled": enabled_flag,
            "importer_menu_items": extension_state.get("menu_items", ()) if enabled_flag else (),
        }

    state["_context_registered"] = True


def _set_cli(app: Flask, enabled: bool) -> None:
    """Register the appropriate CLI group based on flag state."""
    # Avoid duplicate registrations when running tests
    command_name = importer_cli.name
    if command_name in app.cli.commands:
        app.cli.commands.pop(command_name)

    if enabled:
        app.cli.add_command(importer_cli)
    else:
        app.cli.add_command(get_disabled_importer_group())


def init_importer(app: Flask) -> None:
    """
    Conditionally mount importer blueprint and CLI based on configuration.

    Records importer state inside ``app.extensions['importer']`` for reuse in
    templates, CLI, and other helpers.
    """
    enabled = is_importer_enabled(app)
    configured_adapters: Tuple[str, ...] = get_importer_adapters(app)

    state = _ensure_extension_state(app)
    worker_enabled = bool(app.config.get("IMPORTER_WORKER_ENABLED", False))
    state.update(
        {
            "enabled": enabled,
            "configured_adapters": configured_adapters,
            "worker_enabled": worker_enabled,
        }
    )
    _register_template_context(app, state)

    if not enabled:
        state["active_adapters"] = ()
        state["menu_items"] = ()
        _set_cli(app, enabled=False)
        app.logger.info("Importer disabled via IMPORTER_ENABLED flag; skipping registration.")
        return

    registry = get_adapter_registry()
    active_descriptors: Iterable[AdapterDescriptor] = resolve_adapters(configured_adapters, registry)
    state["active_adapters"] = tuple(active_descriptors)
    state["menu_items"] = (
        {
            "label": "Importer Runs",
            "endpoint": "admin_importer.importer_dashboard",
        },
        {
            "label": "Importer Health",
            "endpoint": "importer.importer_healthcheck",
        },
    )
    ensure_celery_app(app, state)

    if importer_blueprint.name not in app.blueprints and not getattr(app, "_got_first_request", False):
        app.register_blueprint(importer_blueprint)
    elif importer_blueprint.name not in app.blueprints:
        app.logger.warning(
            "Importer blueprint registration skipped because the app has already handled its first request."
        )
    _set_cli(app, enabled=True)

    adapter_names = ", ".join(adapter.name for adapter in active_descriptors) or "none"
    app.logger.info("Importer enabled with adapters: %s", adapter_names)
