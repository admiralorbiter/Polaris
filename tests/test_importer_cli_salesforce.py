from __future__ import annotations

from flask_app.importer import init_importer
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus


def _create_salesforce_run():
    run = ImportRun(
        source="salesforce",
        adapter="salesforce",
        status=ImportRunStatus.PENDING,
        dry_run=False,
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def test_importer_run_salesforce_queues_task(app, runner, monkeypatch):
    monkeypatch.setitem(app.config, "IMPORTER_ENABLED", True)
    monkeypatch.setitem(app.config, "IMPORTER_ADAPTERS", ("csv", "salesforce"))
    run = _create_salesforce_run()
    init_importer(app)

    sent_tasks: list[tuple[str, dict]] = []

    class FakeAsyncResult:
        id = "celery-task-123"

    class FakeCelery:
        def send_task(self, name, kwargs=None):
            sent_tasks.append((name, kwargs or {}))
            return FakeAsyncResult()

    monkeypatch.setattr("flask_app.importer.cli.ensure_celery_app", lambda app, state: FakeCelery())

    result = runner.invoke(args=["importer", "run-salesforce", "--run-id", str(run.id)])

    assert result.exit_code == 0, result.output
    assert sent_tasks == [
        ("importer.pipeline.ingest_salesforce_contacts", {"run_id": run.id}),
    ]
    assert "task_id=celery-task-123" in result.output


def test_importer_run_salesforce_requires_existing_run(app, runner, monkeypatch):
    monkeypatch.setitem(app.config, "IMPORTER_ENABLED", True)
    monkeypatch.setitem(app.config, "IMPORTER_ADAPTERS", ("csv", "salesforce"))
    init_importer(app)

    result = runner.invoke(args=["importer", "run-salesforce", "--run-id", "9999"])

    assert result.exit_code != 0
    assert "Import run 9999 not found." in result.output

