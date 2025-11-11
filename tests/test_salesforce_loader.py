from __future__ import annotations

from datetime import datetime, timezone

from flask_app.importer.pipeline.salesforce_loader import SalesforceContactLoader
from flask_app.models import ExternalIdMap
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus, ImporterWatermark, StagingVolunteer


def _create_run() -> ImportRun:
    run = ImportRun(
        source="salesforce",
        adapter="salesforce",
        status=ImportRunStatus.RUNNING,
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _ensure_watermark():
    if not ImporterWatermark.query.filter_by(adapter="salesforce", object_name="contacts").first():
        watermark = ImporterWatermark(adapter="salesforce", object_name="contacts")
        db.session.add(watermark)
        db.session.commit()


def _make_payload(external_id: str, first_name: str = "Ada", deleted: bool = False) -> dict:
    metadata = {
        "source_system": "salesforce",
        "source_object": "Contact",
        "source_modstamp": "2024-01-01T00:00:00.000Z",
        "source_last_modified": "2024-01-01T00:00:00.000Z",
    }
    if deleted:
        metadata["core_state"] = "deleted"
    return {
        "external_id": external_id,
        "first_name": first_name,
        "metadata": metadata,
    }


def _add_staging_row(run: ImportRun, sequence: int, payload: dict) -> None:
    staging = StagingVolunteer(
        run_id=run.id,
        sequence_number=sequence,
        external_system="salesforce",
        payload_json=payload,
        normalized_json=payload,
    )
    db.session.add(staging)
    db.session.commit()


def test_loader_creates_entries(app):
    _ensure_watermark()
    run = _create_run()
    _add_staging_row(run, 1, _make_payload("001"))
    loader = SalesforceContactLoader(run)
    counters = loader.execute()

    assert counters.created == 1
    assert counters.updated == 0
    assert counters.deleted == 0
    assert counters.unchanged == 0
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="001").first()
    assert entry is not None and entry.is_active


def test_loader_detects_updates_and_unchanged(app):
    _ensure_watermark()
    run = _create_run()
    _add_staging_row(run, 1, _make_payload("002"))
    loader = SalesforceContactLoader(run)
    loader.execute()

    # same payload -> unchanged
    run2 = _create_run()
    _add_staging_row(run2, 1, _make_payload("002"))
    loader2 = SalesforceContactLoader(run2)
    counters = loader2.execute()
    assert counters.unchanged == 1

    # modified payload -> updated
    run3 = _create_run()
    _add_staging_row(run3, 1, _make_payload("002", first_name="Grace"))
    loader3 = SalesforceContactLoader(run3)
    counters2 = loader3.execute()
    assert counters2.updated == 1
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="002").first()
    assert entry is not None and entry.is_active


def test_loader_handles_deletes(app):
    _ensure_watermark()
    run = _create_run()
    _add_staging_row(run, 1, _make_payload("003"))
    SalesforceContactLoader(run).execute()

    run_delete = _create_run()
    _add_staging_row(run_delete, 1, _make_payload("003", deleted=True))
    counters = SalesforceContactLoader(run_delete).execute()

    assert counters.deleted == 1
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="003").first()
    assert entry is not None
    assert not entry.is_active


