"""
Utility helpers for importer feature flag checks.
"""

from __future__ import annotations

from typing import Iterable, Tuple

from flask import current_app


def _get_config(app=None):
    if app is not None:
        return app.config
    return current_app.config


def is_importer_enabled(app=None) -> bool:
    """Return True when the importer feature flag is enabled."""
    config = _get_config(app)
    return bool(config.get("IMPORTER_ENABLED", False))


def get_importer_adapters(app=None) -> Tuple[str, ...]:
    """Return the configured importer adapter identifiers."""
    config = _get_config(app)
    adapters: Iterable[str] = config.get("IMPORTER_ADAPTERS", ())
    # Normalize to tuple for immutability, matching config default
    return tuple(adapters)

