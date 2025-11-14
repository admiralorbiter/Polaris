"""
Celery configuration helpers for the importer worker.

These utilities keep Celery optional until the importer is enabled, while
providing sensible defaults (SQLite transport) so developers do not need Redis
for local testing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from celery import Celery
from flask import Flask
from kombu import Queue

DEFAULT_QUEUE_NAME = "imports"
DEFAULT_SQLITE_FILENAME = "celery.sqlite"


def _configure_quiet_loggers(app: Flask) -> None:
    """
    Configure specific loggers to be quieter during Celery task execution.

    This reduces verbosity from SQLAlchemy queries and other noisy loggers
    while keeping important application logs visible.
    """
    # Check if SQLAlchemy echo is disabled (user preference)
    sqlalchemy_echo = app.config.get("SQLALCHEMY_ECHO", False)

    # Suppress SQLAlchemy engine logging unless explicitly enabled
    if not sqlalchemy_echo:
        sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
        sqlalchemy_logger.setLevel(logging.WARNING)

    # Suppress Celery worker state messages (very verbose)
    celery_state_logger = logging.getLogger("celery.worker.strategy")
    celery_state_logger.setLevel(logging.WARNING)

    # Optionally suppress other verbose loggers
    # Uncomment if you want even quieter output:
    # celery_worker_logger = logging.getLogger("celery.worker")
    # celery_worker_logger.setLevel(logging.WARNING)


def _normalize_sqlite_path(app: Flask) -> Path:
    """
    Determine the path backing the SQLite transport/result backend.

    The path can be overridden via ``CELERY_SQLITE_PATH``; otherwise we reuse the
    Flask instance folder. The directory is created eagerly so Celery can open
    the database without additional setup.
    """
    configured = app.config.get("CELERY_SQLITE_PATH")
    if configured:
        sqlite_path = Path(configured)
        if not sqlite_path.is_absolute():
            sqlite_path = Path(app.instance_path) / sqlite_path
    else:
        sqlite_path = Path(app.instance_path) / DEFAULT_SQLITE_FILENAME

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite_path


def _determine_connection_urls(app: Flask) -> tuple[str, str]:
    """
    Resolve broker/result backend URLs, defaulting to SQLite transports.

    Returns:
        tuple[str, str]: (broker_url, result_backend)
    """
    broker_url = app.config.get("CELERY_BROKER_URL")
    result_backend = app.config.get("CELERY_RESULT_BACKEND")

    if broker_url and result_backend:
        return broker_url, result_backend

    sqlite_path = _normalize_sqlite_path(app)
    # Celery expects forward slashes even on Windows.
    normalized = sqlite_path.as_posix()
    default_broker = f"sqla+sqlite:///{normalized}"
    default_backend = f"db+sqlite:///{normalized}"

    return broker_url or default_broker, result_backend or default_backend


def create_celery_app(app: Flask) -> Celery:
    """
    Create and configure a Celery instance bound to the given Flask app.

    The Celery app is configured lazily and can be swapped to Redis/Postgres by
    setting ``CELERY_BROKER_URL``/``CELERY_RESULT_BACKEND`` in the Flask config.
    """
    broker_url, result_backend = _determine_connection_urls(app)
    celery_app = Celery(
        app.import_name,
        broker=broker_url,
        backend=result_backend,
        include=("flask_app.importer.tasks",),
    )

    celery_app.conf.update(
        task_default_queue=DEFAULT_QUEUE_NAME,
        task_queues=[Queue(DEFAULT_QUEUE_NAME)],
        task_default_exchange=DEFAULT_QUEUE_NAME,
        task_default_routing_key=DEFAULT_QUEUE_NAME,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        result_extended=True,
        broker_connection_retry_on_startup=True,
        task_time_limit=app.config.get("IMPORTER_TASK_TIME_LIMIT", 15 * 60),
        task_soft_time_limit=app.config.get("IMPORTER_TASK_SOFT_TIME_LIMIT", 12 * 60),
        # Reduce logging verbosity
        worker_log_format="[%(asctime)s: %(levelname)s/%(processName)s] %(message)s",
        worker_task_log_format="[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s",
        worker_hijack_root_logger=False,  # Don't hijack root logger
    )

    extra_conf: Mapping[str, Any] | str | None = app.config.get("CELERY_CONFIG")
    if isinstance(extra_conf, str):
        try:
            extra_conf = json.loads(extra_conf)
        except json.JSONDecodeError:
            app.logger.warning(
                "CELERY_CONFIG is not valid JSON; ignoring value.",
                exc_info=True,
            )
            extra_conf = None

    app.logger.info(
        "Importer Celery configuration resolved",
        extra={
            "importer_celery_extra_conf": extra_conf,
            "importer_celery_broker_url": broker_url,
            "importer_celery_result_backend": result_backend,
            "importer_worker_enabled": app.config.get("IMPORTER_WORKER_ENABLED"),
        },
    )

    if extra_conf:
        celery_app.conf.update(extra_conf)

    # Configure quieter logging for verbose loggers
    _configure_quiet_loggers(app)

    class FlaskContextTask(celery_app.Task):  # type: ignore[misc]
        """
        Run Celery tasks inside a Flask application context automatically.
        """

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return super().__call__(*args, **kwargs)

    celery_app.Task = FlaskContextTask  # type: ignore[assignment]
    celery_app.loader.import_default_modules()
    return celery_app


def ensure_celery_app(app: Flask, state: dict[str, Any]) -> Celery:
    """
    Return (and cache) the Celery instance inside the importer extension state.
    """
    celery_app: Celery | None = state.get("celery_app")
    if celery_app is None:
        celery_app = create_celery_app(app)
        state["celery_app"] = celery_app
    return celery_app


def get_celery_app(app: Flask) -> Celery | None:
    """
    Fetch the Celery instance from the importer extension, initialising it if
    the importer is enabled but the worker has not yet been configured.
    """
    state: dict[str, Any] | None = app.extensions.get("importer")  # type: ignore[arg-type]
    if not state:
        return None
    celery_app: Celery | None = state.get("celery_app")
    if celery_app is None and state.get("enabled"):
        celery_app = ensure_celery_app(app, state)
    return celery_app
