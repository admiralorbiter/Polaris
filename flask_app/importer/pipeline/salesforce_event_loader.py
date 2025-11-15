"""
Salesforce Session (Event) loader with two-phase commit to core tracking tables.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from typing import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from flask_app.importer.metrics import record_salesforce_rows, record_salesforce_watermark
from flask_app.importer.pipeline.load_core import _record_import_skip
from flask_app.models import ExternalIdMap, db
from flask_app.models.event.enums import CancellationReason, EventFormat, EventStatus, EventType
from flask_app.models.event.models import Event, EventOrganization
from flask_app.models.importer.schema import (
    CleanEvent,
    ImporterWatermark,
    ImportRun,
    ImportRunStatus,
    ImportSkipType,
    StagingEvent,
    StagingRecordStatus,
)
from flask_app.models.organization import Organization

ENTITY_TYPE = "salesforce_event"
DELETE_REASON = "salesforce_is_deleted"


@dataclass
class LoaderCounters:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "deleted": self.deleted,
        }


class SalesforceEventLoader:
    """Two-phase loader that reconciles Salesforce Sessions into core Event tables."""

    def __init__(self, run: ImportRun, session: Session | None = None):
        self.run = run
        self.session = session or db.session

    def execute(self) -> LoaderCounters:
        # Read from clean_events (validated rows) instead of staging
        clean_rows = self._snapshot_clean_rows()
        counters = LoaderCounters()

        with self._transaction():
            for clean_row in clean_rows:
                action = self._apply_row(clean_row)
                if action == "created":
                    counters.created += 1
                elif action == "updated":
                    counters.updated += 1
                elif action == "deleted":
                    counters.deleted += 1
                else:
                    counters.unchanged += 1

            # Advance watermark using ALL staging rows (not just validated ones)
            # This ensures we don't re-process records that failed DQ validation
            all_staging_rows = self._snapshot_staging_rows()
            self._advance_watermark(all_staging_rows)
            self.run.status = ImportRunStatus.SUCCEEDED
            self.run.finished_at = datetime.now(timezone.utc)
            self._persist_counters(counters)

        for action, count in counters.to_dict().items():
            record_salesforce_rows(action=action, count=count)
        return counters

    def _snapshot_clean_rows(self) -> list[CleanEvent | SimpleNamespace]:
        """Read validated rows from clean_events (only rows that passed DQ validation)."""
        stmt = (
            select(CleanEvent)
            .where(CleanEvent.run_id == self.run.id)
            .where(CleanEvent.external_system == "salesforce")
            .order_by(CleanEvent.id.asc())
        )
        clean_rows = list(self.session.scalars(stmt))
        if clean_rows:
            return clean_rows

        # Fallback for unit tests that invoke the loader without running the clean promotion step.
        # Only use fallback if there are validated staging rows but no clean rows (clean promotion wasn't run)
        staging_rows = self._snapshot_staging_rows()
        validated_staging = [r for r in staging_rows if r.status == StagingRecordStatus.VALIDATED]
        if not validated_staging:
            # No validated staging rows, return empty list
            return []

        fallback_rows: list[SimpleNamespace] = []
        for row in validated_staging:
            payload = dict(row.normalized_json or row.payload_json or {})
            # Use actual title from payload, don't default (clean promotion would have skipped if title was required)
            title = payload.get("title") or payload.get("Name") or ""
            fallback_rows.append(
                SimpleNamespace(
                    payload_json=payload,
                    staging_row=row,
                    external_id=payload.get("external_id"),
                    title=title,
                    load_action=None,
                    core_event_id=None,
                    external_system=row.external_system,
                    staging_event_id=row.id,
                )
            )
        return fallback_rows

    def _snapshot_staging_rows(self) -> list[StagingEvent]:
        """Legacy method - kept for watermark advancement."""
        stmt = (
            select(StagingEvent).where(StagingEvent.run_id == self.run.id).order_by(StagingEvent.sequence_number.asc())
        )
        return list(self.session.scalars(stmt))

    def _apply_row(self, clean_row: CleanEvent) -> str:
        # Get normalized payload from clean_event payload_json
        payload = clean_row.payload_json or {}
        # Try to get metadata from staging row if available, otherwise from payload
        if clean_row.staging_row and clean_row.staging_row.normalized_json:
            staging_metadata = clean_row.staging_row.normalized_json.get("metadata", {})
            if staging_metadata:
                # Merge staging metadata into payload for watermark advancement
                payload = {**payload, "metadata": {**payload.get("metadata", {}), **staging_metadata}}
        metadata = payload.get("metadata", {})
        external_id = clean_row.external_id or payload.get("external_id")
        if not external_id:
            return "unchanged"
        external_id = str(external_id)
        map_entry = self._get_external_map(external_id)
        payload_hash = _payload_hash(payload)

        if metadata.get("core_state") == "deleted":
            return self._handle_delete(external_id, map_entry, clean_row)

        if map_entry is None:
            return self._handle_create(external_id, payload, payload_hash, clean_row)

        return self._handle_update(map_entry, payload, payload_hash, clean_row)

    def _get_external_map(self, external_id: str) -> ExternalIdMap | None:
        stmt = (
            select(ExternalIdMap)
            .where(
                ExternalIdMap.external_system == "salesforce",
                ExternalIdMap.external_id == external_id,
                ExternalIdMap.entity_type == ENTITY_TYPE,
            )
            .with_for_update(of=ExternalIdMap)
        )
        return self.session.scalars(stmt).first()

    def _handle_create(
        self, external_id: str, payload: Mapping[str, object], payload_hash: str, clean_row: CleanEvent
    ) -> str:
        title = clean_row.title or payload.get("title") or ""
        if not title:
            # Record skip for missing title
            _record_import_skip(
                self.session,
                self.run.id,
                ImportSkipType.MISSING_REQUIRED_FIELD,
                "Event title is required.",
                staging_event_id=clean_row.staging_event_id if hasattr(clean_row, "staging_event_id") else None,
                clean_event_id=clean_row.id if hasattr(clean_row, "id") else None,
                entity_type="event",
                record_key=external_id,
                details_json={"external_id": external_id, "missing_field": "title"},
            )
            return "unchanged"

        # Create Event record
        slug = _generate_unique_slug(title, self.session)

        # Parse start_date
        start_date = None
        start_date_str = payload.get("start_date")
        if start_date_str:
            try:
                start_date = datetime.fromisoformat(str(start_date_str).replace("Z", "+00:00"))
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=timezone.utc)
                start_date = start_date.astimezone(timezone.utc)
            except Exception:
                pass

        if not start_date:
            # Record skip for missing start_date
            _record_import_skip(
                self.session,
                self.run.id,
                ImportSkipType.MISSING_REQUIRED_FIELD,
                "Event start_date is required.",
                staging_event_id=clean_row.staging_event_id if hasattr(clean_row, "staging_event_id") else None,
                clean_event_id=clean_row.id if hasattr(clean_row, "id") else None,
                entity_type="event",
                record_key=external_id,
                details_json={"external_id": external_id, "missing_field": "start_date"},
            )
            return "unchanged"

        # Parse end_date
        end_date = None
        end_date_str = payload.get("end_date")
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(str(end_date_str).replace("Z", "+00:00"))
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                end_date = end_date.astimezone(timezone.utc)
            except Exception:
                pass

        # Calculate duration
        duration = None
        if start_date and end_date:
            delta = end_date - start_date
            duration = int(delta.total_seconds() / 60)
        elif payload.get("duration"):
            try:
                duration = int(payload.get("duration"))
            except Exception:
                pass

        event = Event(
            title=title,
            description=_coerce_string(payload.get("description")),
            slug=slug,
            event_type=_map_event_type(payload.get("event_type")),
            event_status=_map_event_status(payload.get("event_status")),
            event_format=_map_event_format(payload.get("event_format")),
            cancellation_reason=_map_cancellation_reason(payload.get("cancellation_reason")),
            start_date=start_date,
            end_date=end_date,
            duration=duration,
            location_address=_coerce_string(payload.get("location_address")),
            capacity=_coerce_int(payload.get("capacity")),
        )
        self.session.add(event)
        self.session.flush()

        # Handle organization relationships
        self._link_organizations(event, payload)

        # Create ExternalIdMap entry
        metadata_dict = {
            "payload_hash": payload_hash,
            "last_payload": payload,
        }
        payload_metadata = payload.get("metadata", {})
        if payload_metadata.get("source_modstamp"):
            metadata_dict["source_modstamp"] = payload_metadata.get("source_modstamp")
        if payload_metadata.get("source_last_modified"):
            metadata_dict["source_last_modified"] = payload_metadata.get("source_last_modified")

        entry = ExternalIdMap(
            entity_type=ENTITY_TYPE,
            entity_id=event.id,
            external_system="salesforce",
            external_id=external_id,
            metadata_json=metadata_dict,
        )
        entry.mark_seen(run_id=self.run.id)
        self.session.add(entry)

        # Update clean_row
        clean_row.load_action = "inserted"
        clean_row.core_event_id = event.id

        return "created"

    def _handle_update(
        self, entry: ExternalIdMap, payload: Mapping[str, object], payload_hash: str, clean_row: CleanEvent
    ) -> str:
        current = entry.metadata_json or {}
        previous_hash = current.get("payload_hash")

        # Get the event record
        event = self.session.get(Event, entry.entity_id)
        if event is None:
            # ExternalIdMap exists but event doesn't - treat as create
            return self._handle_create(clean_row.external_id or "", payload, payload_hash, clean_row)

        # Update event fields
        title = clean_row.title or payload.get("title") or event.title
        if title != event.title:
            event.title = title
            # Regenerate slug if title changed
            event.slug = _generate_unique_slug(title, self.session, exclude_id=event.id)

        if payload.get("description"):
            event.description = _coerce_string(payload.get("description"))

        if payload.get("event_type"):
            event_type = _map_event_type(payload.get("event_type"))
            if event_type:
                event.event_type = event_type

        if payload.get("event_status"):
            event_status = _map_event_status(payload.get("event_status"))
            if event_status:
                event.event_status = event_status

        if payload.get("event_format"):
            event_format = _map_event_format(payload.get("event_format"))
            if event_format:
                event.event_format = event_format

        if payload.get("cancellation_reason"):
            cancellation_reason = _map_cancellation_reason(payload.get("cancellation_reason"))
            if cancellation_reason:
                event.cancellation_reason = cancellation_reason

        # Update dates
        start_date_str = payload.get("start_date")
        if start_date_str:
            try:
                start_date = datetime.fromisoformat(str(start_date_str).replace("Z", "+00:00"))
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=timezone.utc)
                event.start_date = start_date.astimezone(timezone.utc)
            except Exception:
                pass

        end_date_str = payload.get("end_date")
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(str(end_date_str).replace("Z", "+00:00"))
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                event.end_date = end_date.astimezone(timezone.utc)
            except Exception:
                pass

        # Update duration
        if payload.get("duration"):
            try:
                event.duration = int(payload.get("duration"))
            except Exception:
                pass
        elif event.start_date and event.end_date:
            delta = event.end_date - event.start_date
            event.duration = int(delta.total_seconds() / 60)

        if payload.get("location_address"):
            event.location_address = _coerce_string(payload.get("location_address"))

        if payload.get("capacity"):
            event.capacity = _coerce_int(payload.get("capacity"))

        # Update organization relationships
        self._link_organizations(event, payload)

        # Update ExternalIdMap
        entry.is_active = True
        entry.deactivated_at = None
        entry.upstream_deleted_reason = None
        metadata_dict = {"payload_hash": payload_hash, "last_payload": payload}
        payload_metadata = payload.get("metadata", {})
        if payload_metadata.get("source_modstamp"):
            metadata_dict["source_modstamp"] = payload_metadata.get("source_modstamp")
        if payload_metadata.get("source_last_modified"):
            metadata_dict["source_last_modified"] = payload_metadata.get("source_last_modified")

        entry.metadata_json = metadata_dict
        entry.last_seen_at = datetime.now(timezone.utc)

        # Update clean_row
        clean_row.load_action = "updated" if previous_hash != payload_hash else "no_change"
        clean_row.core_event_id = event.id

        if previous_hash == payload_hash:
            return "unchanged"
        return "updated"

    def _handle_delete(self, external_id: str, entry: ExternalIdMap | None, clean_row: CleanEvent) -> str:
        if entry is None:
            clean_row.load_action = "deleted"
            clean_row.core_event_id = None
            return "deleted"
        if not entry.is_active:
            return "unchanged"
        entry.is_active = False
        entry.deactivated_at = datetime.now(timezone.utc)
        entry.upstream_deleted_reason = DELETE_REASON
        entry.last_seen_at = datetime.now(timezone.utc)

        # Update clean_row
        clean_row.load_action = "deleted"
        if entry.entity_id:
            clean_row.core_event_id = entry.entity_id

        return "deleted"

    def _link_organizations(self, event: Event, payload: Mapping[str, object]) -> None:
        """Link event to organizations based on metadata fields."""
        metadata = payload.get("metadata", {})
        district_id = metadata.get("district_id")
        school_id = metadata.get("school_id")
        parent_account_id = metadata.get("parent_account_id")

        # Look up organizations by external ID
        org_ids_to_link = []

        if district_id:
            org = self._find_organization_by_external_id(str(district_id))
            if org:
                org_ids_to_link.append((org.id, True))  # Mark as primary

        if school_id:
            org = self._find_organization_by_external_id(str(school_id))
            if org:
                org_ids_to_link.append((org.id, False))

        if parent_account_id:
            org = self._find_organization_by_external_id(str(parent_account_id))
            if org:
                org_ids_to_link.append((org.id, False))

        # Remove existing organization links for this event
        existing_links = self.session.query(EventOrganization).filter_by(event_id=event.id).all()
        for link in existing_links:
            self.session.delete(link)

        # Add new organization links
        primary_set = False
        for org_id, is_primary in org_ids_to_link:
            # Only set first one as primary if none set yet
            if is_primary and not primary_set:
                link = EventOrganization(event_id=event.id, organization_id=org_id, is_primary=True)
                primary_set = True
            else:
                link = EventOrganization(event_id=event.id, organization_id=org_id, is_primary=False)
            self.session.add(link)

    def _find_organization_by_external_id(self, external_id: str) -> Organization | None:
        """Find organization by Salesforce external ID."""
        map_entry = (
            self.session.query(ExternalIdMap)
            .filter_by(
                external_system="salesforce",
                external_id=external_id,
                entity_type="salesforce_organization",
                is_active=True,
            )
            .first()
        )
        if map_entry and map_entry.entity_id:
            return self.session.get(Organization, map_entry.entity_id)
        return None

    def _advance_watermark(self, rows: Iterable[StagingEvent]) -> None:
        latest_modstamp: str | None = None
        latest_updated_at: str | None = None

        for row in rows:
            metadata = (row.normalized_json or {}).get("metadata", {})
            modstamp = metadata.get("source_modstamp")
            updated_at = metadata.get("source_last_modified")
            if modstamp:
                latest_modstamp = max(latest_modstamp or modstamp, modstamp)
            if updated_at:
                latest_updated_at = max(latest_updated_at or updated_at, updated_at)

        if latest_modstamp:
            watermark = (
                self.session.query(ImporterWatermark)
                .filter_by(adapter="salesforce", object_name="sessions")
                .with_for_update(of=ImporterWatermark)
                .first()
            )
            if watermark:
                parsed_modstamp = _safe_parse_datetime(latest_modstamp)
                watermark.last_successful_modstamp = parsed_modstamp
                watermark.last_run_id = self.run.id
                self.session.add(watermark)
                record_salesforce_watermark(parsed_modstamp)

        target_updated = latest_updated_at or latest_modstamp
        if target_updated:
            parsed = _safe_parse_datetime(target_updated)
            self.run.max_source_updated_at = parsed
            metrics = deepcopy(self.run.metrics_json) if self.run.metrics_json else {}
            metrics.setdefault("salesforce", {})["max_source_updated_at"] = parsed.isoformat()
            self.run.metrics_json = metrics

    def _persist_counters(self, counters: LoaderCounters) -> None:
        counts = deepcopy(self.run.counts_json) if self.run.counts_json else {}
        core_bucket = counts.setdefault("core", {}).setdefault("events", {})
        salesforce_counts = core_bucket.get("salesforce", {})
        salesforce_counts.update(counters.to_dict())
        core_bucket["salesforce"] = salesforce_counts
        counts["core"]["events"] = core_bucket
        self.run.counts_json = counts

    @contextmanager
    def _transaction(self):
        try:
            yield
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise


def _payload_hash(payload: Mapping[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _generate_unique_slug(title: str, session: Session, exclude_id: int | None = None) -> str:
    """Generate a unique slug from event title."""
    # Convert to lowercase
    slug = title.lower()
    # Replace spaces and underscores with hyphens
    slug = re.sub(r"[_\s]+", "-", slug)
    # Remove all non-alphanumeric characters except hyphens
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)
    # Remove leading/trailing hyphens
    slug = slug.strip("-")

    if not slug:
        slug = "event"

    # Ensure uniqueness
    base_slug = slug
    counter = 1
    while True:
        query = session.query(Event).filter_by(slug=slug)
        if exclude_id:
            query = query.filter(Event.id != exclude_id)
        existing = query.first()
        if not existing:
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


def _map_event_type(value: object | None) -> EventType | None:
    """Map normalized event type string to EventType enum."""
    if not value:
        return None
    type_str = str(value).strip().lower()
    if not type_str:
        return None

    # Map normalized values to enum
    type_map = {
        "workshop": EventType.WORKSHOP,
        "meeting": EventType.MEETING,
        "training": EventType.TRAINING,
        "fundraiser": EventType.FUNDRAISER,
        "community_event": EventType.COMMUNITY_EVENT,
        "other": EventType.OTHER,
    }

    return type_map.get(type_str, EventType.OTHER)


def _map_event_status(value: object | None) -> EventStatus | None:
    """Map normalized event status string to EventStatus enum."""
    if not value:
        return None
    status_str = str(value).strip().lower()
    if not status_str:
        return None

    # Map normalized values to enum
    status_map = {
        "draft": EventStatus.DRAFT,
        "requested": EventStatus.REQUESTED,
        "confirmed": EventStatus.CONFIRMED,
        "completed": EventStatus.COMPLETED,
        "cancelled": EventStatus.CANCELLED,
    }

    return status_map.get(status_str, EventStatus.REQUESTED)


def _map_event_format(value: object | None) -> EventFormat | None:
    """Map normalized event format string to EventFormat enum."""
    if not value:
        return None
    format_str = str(value).strip().lower()
    if not format_str:
        return None

    # Map normalized values to enum
    format_map = {
        "in_person": EventFormat.IN_PERSON,
        "virtual": EventFormat.VIRTUAL,
        "hybrid": EventFormat.HYBRID,
    }

    return format_map.get(format_str, EventFormat.IN_PERSON)


def _map_cancellation_reason(value: object | None) -> CancellationReason | None:
    """Map normalized cancellation reason string to CancellationReason enum."""
    if not value:
        return None
    reason_str = str(value).strip().lower()
    if not reason_str:
        return None

    # Map normalized values to enum
    reason_map = {
        "weather": CancellationReason.WEATHER,
        "low_attendance": CancellationReason.LOW_ATTENDANCE,
        "emergency": CancellationReason.EMERGENCY,
        "scheduling_conflict": CancellationReason.SCHEDULING_CONFLICT,
        "other": CancellationReason.OTHER,
    }

    return reason_map.get(reason_str, CancellationReason.OTHER)


def _coerce_string(value: object | None) -> str | None:
    """Coerce a value to a string, returning None for empty strings."""
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def _coerce_int(value: object | None) -> int | None:
    """Coerce a value to an integer, returning None if conversion fails."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_parse_datetime(value: str) -> datetime:
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
