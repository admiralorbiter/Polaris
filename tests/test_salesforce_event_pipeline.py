from __future__ import annotations

from datetime import datetime, timezone

from flask_app.importer.adapters.salesforce.extractor import SalesforceBatch
from flask_app.importer.pipeline.salesforce import ingest_salesforce_sessions
from flask_app.importer.pipeline.salesforce_event_loader import SalesforceEventLoader
from flask_app.models import Event, ExternalIdMap
from flask_app.models.base import db
from flask_app.models.importer.schema import ImporterWatermark, ImportRun, ImportRunStatus, StagingEvent


class DummyExtractor:
    def __init__(self, batches):
        self._batches = batches

    def extract_batches(self, _soql):
        for batch in self._batches:
            yield batch


def _make_batch(sequence: int, rows: list[dict[str, str]]) -> SalesforceBatch:
    return SalesforceBatch(job_id="JOB123", sequence=sequence, records=rows, locator=None)


def _create_run(*, dry_run: bool = False) -> ImportRun:
    run = ImportRun(
        source="salesforce",
        adapter="salesforce",
        status=ImportRunStatus.PENDING,
        dry_run=dry_run,
        ingest_params_json={"entity_type": "events"},
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _create_watermark() -> ImporterWatermark:
    watermark = ImporterWatermark(adapter="salesforce", object_name="sessions")
    db.session.add(watermark)
    db.session.commit()
    return db.session.get(ImporterWatermark, watermark.id)


def test_ingest_salesforce_sessions_persists_rows(app):
    """Test that event ingestion persists staging rows correctly."""
    run = _create_run()
    watermark = _create_watermark()
    batches = [
        _make_batch(
            1,
            [
                {
                    "Id": "a1hUV0000041IS1YAM",
                    "Name": "Test Event 1",
                    "Session_Type__c": "Campus Visit",
                    "Format__c": "In-Person",
                    "Start_Date_and_Time__c": "2026-03-20T15:30:00.000+0000",
                    "End_Date_and_Time__c": "2026-03-20T17:30:00.000+0000",
                    "Session_Status__c": "Confirmed",
                    "Location_Information__c": "Test Location",
                    "Description__c": "Test description",
                    "SystemModstamp": "2024-01-01T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-01T00:00:00.000Z",
                },
                {
                    "Id": "a1hUV000003p9nWYAQ",
                    "Name": "Test Event 2",
                    "Session_Type__c": "Career Speaker",
                    "Format__c": "In-Person",
                    "Start_Date_and_Time__c": "2026-03-13T14:10:00.000+0000",
                    "End_Date_and_Time__c": "2026-03-13T15:45:00.000+0000",
                    "Session_Status__c": "Confirmed",
                    "SystemModstamp": "2024-01-02T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-02T00:00:00.000Z",
                },
            ],
        ),
        _make_batch(
            2,
            [
                {
                    "Id": "a1hUV000004ZczNYAS",
                    "Name": "Test Event 3",
                    "Session_Type__c": "Workplace Visit",
                    "Format__c": "In-Person",
                    "Start_Date_and_Time__c": "2026-03-10T17:00:00.000+0000",
                    "End_Date_and_Time__c": "2026-03-10T18:30:00.000+0000",
                    "Session_Status__c": "Confirmed",
                    "SystemModstamp": "2024-01-03T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-03T00:00:00.000Z",
                },
            ],
        ),
    ]
    extractor = DummyExtractor(batches)

    summary = ingest_salesforce_sessions(
        import_run=run,
        extractor=extractor,
        watermark=watermark,
        staging_batch_size=2,
        dry_run=False,
        logger=app.logger,
        record_limit=None,
    )

    db.session.commit()

    assert summary.records_received == 3
    assert summary.records_staged == 3
    assert summary.batches_processed == 2
    assert summary.job_id == "JOB123"

    staging_rows = db.session.query(StagingEvent).filter_by(run_id=run.id).all()
    assert len(staging_rows) == 3

    # Verify first row
    row1 = next((r for r in staging_rows if r.external_id == "a1hUV0000041IS1YAM"), None)
    assert row1 is not None
    assert row1.sequence_number == 1
    assert row1.external_system == "salesforce"
    assert row1.payload_json["Name"] == "Test Event 1"
    assert row1.normalized_json is not None
    assert row1.normalized_json.get("title") == "Test Event 1"
    assert row1.normalized_json.get("event_type") == "community_event"
    assert row1.normalized_json.get("event_status") == "confirmed"
    assert row1.normalized_json.get("event_format") == "in_person"
    assert "duration" in row1.normalized_json
    assert row1.normalized_json["duration"] == 120  # 2 hours in minutes

    # Verify watermark was updated
    db.session.refresh(watermark)
    assert watermark.last_successful_modstamp is not None
    assert watermark.last_run_id == run.id


def test_ingest_salesforce_sessions_dry_run(app):
    """Test that dry run doesn't persist staging rows."""
    run = _create_run(dry_run=True)
    watermark = _create_watermark()
    batches = [
        _make_batch(
            1,
            [
                {
                    "Id": "a1hUV0000041IS1YAM",
                    "Name": "Test Event 1",
                    "Session_Type__c": "Campus Visit",
                    "Format__c": "In-Person",
                    "Start_Date_and_Time__c": "2026-03-20T15:30:00.000+0000",
                    "End_Date_and_Time__c": "2026-03-20T17:30:00.000+0000",
                    "Session_Status__c": "Confirmed",
                    "SystemModstamp": "2024-01-01T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-01T00:00:00.000Z",
                },
            ],
        ),
    ]
    extractor = DummyExtractor(batches)

    summary = ingest_salesforce_sessions(
        import_run=run,
        extractor=extractor,
        watermark=watermark,
        staging_batch_size=2,
        dry_run=True,
        logger=app.logger,
        record_limit=None,
    )

    db.session.commit()

    assert summary.records_received == 1
    assert summary.records_staged == 0  # Dry run doesn't stage
    assert summary.dry_run is True

    staging_rows = db.session.query(StagingEvent).filter_by(run_id=run.id).all()
    assert len(staging_rows) == 0

    # Watermark should not be updated in dry run
    db.session.refresh(watermark)
    assert watermark.last_successful_modstamp is None or watermark.last_run_id != run.id
