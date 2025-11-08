import json
from pathlib import Path

import pytest
from flask import Flask, render_template_string

from flask_app.importer import IMPORTER_EXTENSION_KEY, init_importer

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


def build_app(enabled=False, adapters=()):
    app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
    app.config.update(
        SECRET_KEY="test-secret",
        TESTING=True,
        IMPORTER_ENABLED=enabled,
        IMPORTER_ADAPTERS=tuple(adapters),
    )

    init_importer(app)
    return app


def test_importer_disabled_registers_stub_cli(monkeypatch):
    called = {"flag": False}

    def record_call(*args, **kwargs):
        called["flag"] = True
        return ()

    monkeypatch.setattr("flask_app.importer.resolve_adapters", record_call)

    app = build_app(enabled=False)

    assert called["flag"] is False, "resolve_adapters should not run when importer disabled"
    assert "importer" not in app.blueprints

    runner = app.test_cli_runner()
    result = runner.invoke(args=["importer"])
    assert result.exit_code != 0
    assert "Importer commands are unavailable" in result.output

    with app.app_context():
        rendered = render_template_string(
            "{{ importer_enabled }} {{ importer_menu_items|length }}"
        )
        assert rendered.strip() == "False 0"


def test_importer_enabled_registers_blueprint_and_cli():
    app = build_app(enabled=True, adapters=("csv",))

    assert "importer" in app.blueprints
    assert "importer.importer_healthcheck" in app.view_functions

    client = app.test_client()
    response = client.get("/importer/health")
    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload["enabled"] is True
    assert payload["adapters"][0]["name"] == "csv"

    runner = app.test_cli_runner()
    result = runner.invoke(args=["importer"])
    assert result.exit_code == 0
    assert "- csv" in result.output or "csv" in result.output

    importer_state = app.extensions[IMPORTER_EXTENSION_KEY]
    assert importer_state["enabled"] is True
    assert importer_state["active_adapters"][0].name == "csv"
    assert importer_state["menu_items"]

    with app.app_context():
        rendered = render_template_string(
            "{{ importer_enabled }} {{ importer_menu_items|length }}"
        )
        values = rendered.strip().split()
        assert values[0] == "True"
        assert int(values[1]) >= 1


def test_importer_unknown_adapter_raises():
    with pytest.raises(ValueError):
        build_app(enabled=True, adapters=("unknown",))

