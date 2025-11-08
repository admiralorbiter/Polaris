"""
Blueprint stubs for importer UI.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

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

