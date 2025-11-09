import json
from typing import Any, Dict

import pytest
from flask import Flask

from flask_app.importer import get_celery_app, init_importer
from flask_app.importer.celery_app import DEFAULT_QUEUE_NAME


def build_importer_app(**overrides) -> Flask:
    """
    Construct a minimal Flask app with the importer enabled for worker tests.
    """
    instance_path_override = overrides.pop("INSTANCE_PATH", None)
    if instance_path_override:
        app = Flask(__name__, instance_path=instance_path_override)
        app.config["INSTANCE_PATH"] = instance_path_override
    else:
        app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        TESTING=True,
        IMPORTER_ENABLED=True,
        IMPORTER_ADAPTERS=("csv",),
    )
    app.config.update(overrides)
    init_importer(app)
    return app


def test_celery_defaults_to_sqlite_transport(tmp_path):
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    sqlite_path = instance_dir / "custom.sqlite"

    app = build_importer_app(
        CELERY_SQLITE_PATH=str(sqlite_path),
        CELERY_CONFIG={"task_always_eager": True, "task_eager_propagates": True},
        INSTANCE_PATH=str(instance_dir),
    )

    celery_app = get_celery_app(app)
    assert celery_app is not None
    assert celery_app.conf.broker_url.startswith("sqla+sqlite:///")
    assert sqlite_path.name in celery_app.conf.broker_url
    assert celery_app.conf.result_backend.startswith("db+sqlite:///")
    assert celery_app.conf.task_default_queue == DEFAULT_QUEUE_NAME
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_worker_ping_cli(monkeypatch):
    app = build_importer_app(
        IMPORTER_WORKER_ENABLED=True,
        CELERY_CONFIG={"task_always_eager": True, "task_eager_propagates": True},
    )

    runner = app.test_cli_runner()
    result = runner.invoke(args=["importer", "worker", "ping"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert "timestamp" in payload
    assert "worker_hostname" in payload


def test_worker_run_invokes_celery(monkeypatch):
    app = build_importer_app(
        IMPORTER_WORKER_ENABLED=True,
        CELERY_CONFIG={"task_always_eager": True, "task_eager_propagates": True},
    )
    celery_app = get_celery_app(app)
    assert celery_app is not None

    calls: Dict[str, Any] = {}

    def fake_worker_main(argv=None):
        calls["argv"] = argv

    monkeypatch.setattr(celery_app, "worker_main", fake_worker_main)

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=[
            "importer",
            "worker",
            "run",
            "--loglevel",
            "debug",
            "--concurrency",
            "2",
            "--pool",
            "solo",
            "--queues",
            "imports",
        ]
    )

    assert result.exit_code == 0, result.output
    assert calls["argv"] == [
        "worker",
        "--loglevel",
        "debug",
        "-Q",
        "imports",
        "--concurrency",
        "2",
        "--pool",
        "solo",
    ]


def test_worker_health_endpoint_states():
    app = build_importer_app()
    client = app.test_client()

    disabled_resp = client.get("/importer/worker_health")
    assert disabled_resp.status_code == 200
    disabled_payload = disabled_resp.get_json()
    assert disabled_payload["status"] == "disabled"
    assert disabled_payload["worker_enabled"] is False

    eager_app = build_importer_app(
        IMPORTER_WORKER_ENABLED=True,
        CELERY_CONFIG={"task_always_eager": True, "task_eager_propagates": True},
    )
    eager_client = eager_app.test_client()
    ok_resp = eager_client.get("/importer/worker_health")
    assert ok_resp.status_code == 200
    ok_payload = ok_resp.get_json()
    assert ok_payload["status"] == "ok"
    assert ok_payload["heartbeat"]["status"] == "ok"

