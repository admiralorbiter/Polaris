from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from flask_app.importer import init_importer
from flask_app.importer.utils import resolve_upload_directory
from flask_app.importer.pipeline.run_service import ImportRunService
from flask_app.models import AdminLog, db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus
from flask_app.routes.admin_importer import register_importer_admin_routes


@pytest.fixture
def importer_app(app):
    app.config.update(
        {
            "IMPORTER_ENABLED": True,
            "IMPORTER_ADAPTERS": ("csv",),
            "IMPORTER_SHOW_RECENT_RUNS": False,
        }
    )
    init_importer(app)
    register_importer_admin_routes(app)
    yield app


@pytest.fixture
def run_factory(importer_app, tmp_path):
    created_runs: list[ImportRun] = []

    def _factory(
        *,
        source: str = "csv",
        status: ImportRunStatus = ImportRunStatus.SUCCEEDED,
        started_offset_minutes: int = 0,
        duration_seconds: int = 120,
        dry_run: bool = False,
        keep_file: bool = True,
    ) -> ImportRun:
        now = datetime.now(timezone.utc)
        started_at = now.replace(microsecond=0) - timedelta(minutes=started_offset_minutes)
        finished_at = started_at + timedelta(seconds=duration_seconds)
        file_path: str | None = None
        if keep_file:
            with importer_app.app_context():
                upload_root = resolve_upload_directory(importer_app)
            upload_file = upload_root / f"run_{len(created_runs)}.csv"
            upload_file.write_text("id,name\n1,Alice\n")
            file_path = str(upload_file)

        run = ImportRun(
            source=source,
            adapter=source,
            status=status,
            dry_run=dry_run,
            started_at=started_at,
            finished_at=finished_at,
            counts_json={
                "staging": {"volunteers": {"rows_staged": 50}},
                "dq": {"volunteers": {"rows_validated": 48, "rows_quarantined": 2}},
                "core": {"volunteers": {"rows_inserted": 45, "rows_skipped_duplicates": 3}},
            },
            metrics_json={},
            ingest_params_json={
                "file_path": file_path,
                "keep_file": keep_file,
                "dry_run": dry_run,
                "source_system": source,
            }
            if file_path
            else None,
        )
        db.session.add(run)
        db.session.commit()
        created_runs.append(run)
        return run

    yield _factory

    for run in created_runs:
        db.session.delete(run)
    db.session.query(AdminLog).delete()
    db.session.commit()

