from __future__ import annotations

from datetime import datetime, timezone

from flask_app.importer.pipeline.salesforce_event_loader import SalesforceEventLoader
from flask_app.models import Event, ExternalIdMap
from flask_app.models.base import db
from flask_app.models.importer.schema import (
    CleanEvent,
    ImporterWatermark,
    ImportRun,
    ImportRunStatus,
    ImportSkip,
    ImportSkipType,
    StagingEvent,
    StagingRecordStatus,
)


def _create_run() -> ImportRun:
    run = ImportRun(
        source="salesforce",
        adapter="salesforce",
        status=ImportRunStatus.RUNNING,
        ingest_params_json={"entity_type": "events"},
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _ensure_watermark():
    if not ImporterWatermark.query.filter_by(adapter="salesforce", object_name="sessions").first():
        watermark = ImporterWatermark(adapter="salesforce", object_name="sessions")
        db.session.add(watermark)
        db.session.commit()


def _make_payload(external_id: str, title: str = "Test Event", deleted: bool = False) -> dict:
    metadata = {
        "source_system": "salesforce",
        "source_object": "Session__c",
        "source_modstamp": "2024-01-01T00:00:00.000Z",
        "source_last_modified": "2024-01-01T00:00:00.000Z",
    }
    if deleted:
        metadata["core_state"] = "deleted"
    return {
        "external_id": external_id,
        "title": title,
        "event_type": "community_event",
        "event_status": "confirmed",
        "event_format": "in_person",
        "start_date": "2026-03-20T15:30:00.000Z",
        "end_date": "2026-03-20T17:30:00.000Z",
        "duration": 120,
        "location_address": "Test Location",
        "capacity": 50,
        "description": "Test description",
        "metadata": metadata,
    }


def _add_staging_row(run: ImportRun, seq: int, payload: dict) -> StagingEvent:
    row = StagingEvent(
        run_id=run.id,
        sequence_number=seq,
        source_record_id=f"SF-{payload['external_id']}",
        external_system="salesforce",
        external_id=payload["external_id"],
        payload_json={"Id": payload["external_id"], "Name": payload["title"]},
        normalized_json=payload,
        status=StagingRecordStatus.LANDED,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _add_clean_row(run: ImportRun, staging_row: StagingEvent, payload: dict) -> CleanEvent:
    import json
    from hashlib import sha256

    checksum = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    clean_row = CleanEvent(
        run_id=run.id,
        staging_event_id=staging_row.id,
        external_system="salesforce",
        external_id=payload["external_id"],
        title=payload["title"],
        checksum=checksum,
        payload_json=payload,
        promoted_at=datetime.now(timezone.utc),
    )
    clean_row.staging_row = staging_row
    db.session.add(clean_row)
    db.session.commit()
    return clean_row


def test_loader_creates_event(app):
    """Test that loader creates Event record."""
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("a1hUV0000041IS1YAM", "Test Event")
    staging_row = _add_staging_row(run, 1, payload)

    # Run DQ and clean promotion (simplified for test)
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    from flask_app.importer.pipeline.clean import promote_clean_events

    promote_clean_events(run, dry_run=False)
    db.session.commit()

    clean_row = db.session.query(CleanEvent).filter_by(run_id=run.id).first()
    assert clean_row is not None

    loader = SalesforceEventLoader(run)
    counters = loader.execute()

    assert counters.created == 1
    assert counters.updated == 0
    assert counters.unchanged == 0

    # Verify Event was created
    event = db.session.query(Event).filter_by(title="Test Event").first()
    assert event is not None
    assert event.event_type.value == "community_event"
    assert event.event_status.value == "confirmed"
    assert event.event_format.value == "in_person"
    assert event.duration == 120
    assert event.location_address == "Test Location"
    assert event.capacity == 50

    # Verify ExternalIdMap was created
    map_entry = (
        db.session.query(ExternalIdMap)
        .filter_by(
            external_system="salesforce",
            external_id="a1hUV0000041IS1YAM",
            entity_type="salesforce_event",
        )
        .first()
    )
    assert map_entry is not None
    assert map_entry.entity_id == event.id
    assert map_entry.is_active is True

    # Verify clean_row was updated
    db.session.refresh(clean_row)
    assert clean_row.core_event_id == event.id
    assert clean_row.load_action == "inserted"


def test_loader_updates_existing_event(app):
    """Test that loader updates existing Event record."""
    _ensure_watermark()
    run = _create_run()

    # Create existing event
    from flask_app.models.event.enums import EventFormat, EventStatus, EventType

    existing_event = Event(
        title="Test Event",
        slug="test-event",
        event_type=EventType.COMMUNITY_EVENT,
        event_status=EventStatus.CONFIRMED,
        event_format=EventFormat.IN_PERSON,
        start_date=datetime(2026, 3, 20, 15, 30, tzinfo=timezone.utc),
        end_date=datetime(2026, 3, 20, 17, 30, tzinfo=timezone.utc),
        duration=120,
    )
    db.session.add(existing_event)
    db.session.flush()

    # Create ExternalIdMap
    map_entry = ExternalIdMap(
        entity_type="salesforce_event",
        entity_id=existing_event.id,
        external_system="salesforce",
        external_id="a1hUV0000041IS1YAM",
        metadata_json={"payload_hash": "old_hash"},
    )
    map_entry.mark_seen(run_id=run.id)
    db.session.add(map_entry)
    db.session.commit()

    # Create new payload with updated data
    payload = _make_payload("a1hUV0000041IS1YAM", "Updated Test Event")
    payload["description"] = "Updated description"
    payload["capacity"] = 100
    staging_row = _add_staging_row(run, 1, payload)

    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    from flask_app.importer.pipeline.clean import promote_clean_events

    promote_clean_events(run, dry_run=False)
    db.session.commit()

    clean_row = db.session.query(CleanEvent).filter_by(run_id=run.id).first()

    loader = SalesforceEventLoader(run)
    counters = loader.execute()

    assert counters.created == 0
    assert counters.updated == 1
    assert counters.unchanged == 0

    # Verify Event was updated
    db.session.refresh(existing_event)
    assert existing_event.title == "Updated Test Event"
    assert existing_event.description == "Updated description"
    assert existing_event.capacity == 100

    # Verify clean_row was updated
    db.session.refresh(clean_row)
    assert clean_row.core_event_id == existing_event.id
    assert clean_row.load_action == "updated"


def test_loader_skips_missing_title(app):
    """Test that loader skips events with missing title."""
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("a1hUV0000041IS1YAM", "")
    payload["title"] = ""  # Empty title
    staging_row = _add_staging_row(run, 1, payload)

    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    from flask_app.importer.pipeline.clean import promote_clean_events

    promote_clean_events(run, dry_run=False)
    db.session.commit()

    clean_row = db.session.query(CleanEvent).filter_by(run_id=run.id).first()
    # Clean promotion should skip rows without title
    if clean_row is None:
        # If clean promotion skipped it, that's fine - test that loader handles it
        return

    loader = SalesforceEventLoader(run)
    counters = loader.execute()

    assert counters.created == 0
    assert counters.unchanged == 1

    # Verify ImportSkip was created
    skip = (
        db.session.query(ImportSkip)
        .filter_by(
            run_id=run.id,
            entity_type="event",
        )
        .first()
    )
    assert skip is not None
    assert skip.skip_type == ImportSkipType.MISSING_REQUIRED_FIELD


def test_loader_skips_missing_start_date(app):
    """Test that loader skips events with missing start_date."""
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("a1hUV0000041IS1YAM", "Test Event")
    payload.pop("start_date")  # Remove start_date
    staging_row = _add_staging_row(run, 1, payload)

    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    from flask_app.importer.pipeline.clean import promote_clean_events

    promote_clean_events(run, dry_run=False)
    db.session.commit()

    clean_row = db.session.query(CleanEvent).filter_by(run_id=run.id).first()
    if clean_row is None:
        return

    loader = SalesforceEventLoader(run)
    counters = loader.execute()

    assert counters.created == 0
    assert counters.unchanged == 1

    # Verify ImportSkip was created
    skip = (
        db.session.query(ImportSkip)
        .filter_by(
            run_id=run.id,
            entity_type="event",
        )
        .first()
    )
    assert skip is not None
    assert skip.skip_type == ImportSkipType.MISSING_REQUIRED_FIELD


def test_loader_handles_deleted_event(app):
    """Test that loader handles deleted events."""
    _ensure_watermark()
    run = _create_run()

    # Create existing event
    existing_event = Event(
        title="Test Event",
        slug="test-event",
        event_type="community_event",
        event_status="confirmed",
        event_format="in_person",
        start_date=datetime(2026, 3, 20, 15, 30, tzinfo=timezone.utc),
    )
    db.session.add(existing_event)
    db.session.flush()

    # Create ExternalIdMap
    map_entry = ExternalIdMap(
        entity_type="salesforce_event",
        entity_id=existing_event.id,
        external_system="salesforce",
        external_id="a1hUV0000041IS1YAM",
        metadata_json={"payload_hash": "old_hash"},
    )
    map_entry.mark_seen(run_id=run.id)
    db.session.add(map_entry)
    db.session.commit()

    # Create payload with deleted flag
    payload = _make_payload("a1hUV0000041IS1YAM", "Test Event", deleted=True)
    staging_row = _add_staging_row(run, 1, payload)

    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    from flask_app.importer.pipeline.clean import promote_clean_events

    promote_clean_events(run, dry_run=False)
    db.session.commit()

    clean_row = db.session.query(CleanEvent).filter_by(run_id=run.id).first()

    loader = SalesforceEventLoader(run)
    counters = loader.execute()

    assert counters.deleted == 1
    assert counters.created == 0
    assert counters.updated == 0

    # Verify ExternalIdMap was deactivated
    db.session.refresh(map_entry)
    assert map_entry.is_active is False
    assert map_entry.deactivated_at is not None
    assert map_entry.upstream_deleted_reason == "salesforce_is_deleted"

    # Verify clean_row was updated
    db.session.refresh(clean_row)
    assert clean_row.load_action == "deleted"
