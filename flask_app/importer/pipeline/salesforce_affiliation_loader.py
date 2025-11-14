"""
Salesforce Affiliation (npe5__Affiliation__c) loader with two-phase commit to core tracking tables.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from typing import Mapping

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import Session

from flask_app.importer.metrics import record_salesforce_rows, record_salesforce_watermark
from flask_app.importer.pipeline.load_core import _record_import_skip
from flask_app.models import ExternalIdMap, db
from flask_app.models.contact.relationships import ContactOrganization
from flask_app.models.importer.schema import (
    CleanAffiliation,
    ImporterWatermark,
    ImportRun,
    ImportRunStatus,
    ImportSkipType,
    StagingAffiliation,
    StagingRecordStatus,
)

ENTITY_TYPE = "salesforce_affiliation"
DELETE_REASON = "salesforce_is_deleted"


@dataclass
class LoaderCounters:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    skipped: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "deleted": self.deleted,
            "skipped": self.skipped,
        }


class SalesforceAffiliationLoader:
    """Two-phase loader that reconciles Salesforce Affiliations into core ContactOrganization tables."""

    def __init__(self, run: ImportRun, session: Session | None = None):
        self.run = run
        self.session = session or db.session

    def execute(self) -> LoaderCounters:
        # Read from clean_affiliations (validated rows) instead of staging
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
                elif action == "skipped":
                    counters.skipped += 1
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

    def _snapshot_clean_rows(self) -> list[CleanAffiliation | SimpleNamespace]:
        """Read validated rows from clean_affiliations (only rows that passed DQ validation)."""
        stmt = (
            select(CleanAffiliation)
            .where(CleanAffiliation.run_id == self.run.id)
            .where(CleanAffiliation.external_system == "salesforce")
            .order_by(CleanAffiliation.id.asc())
        )
        clean_rows = list(self.session.scalars(stmt))
        if clean_rows:
            return clean_rows

        # Fallback for unit tests that invoke the loader without running the clean promotion step.
        staging_rows = self._snapshot_staging_rows()
        validated_staging = [r for r in staging_rows if r.status == StagingRecordStatus.VALIDATED]
        if not validated_staging:
            return []

        fallback_rows: list[SimpleNamespace] = []
        for row in validated_staging:
            payload = dict(row.normalized_json or row.payload_json or {})
            fallback_rows.append(
                SimpleNamespace(
                    payload_json=payload,
                    staging_row=row,
                    external_id=payload.get("external_id"),
                    contact_external_id=payload.get("contact_external_id"),
                    organization_external_id=payload.get("organization_external_id"),
                    load_action=None,
                    core_contact_organization_id=None,
                    external_system=row.external_system,
                    staging_affiliation_id=row.id,
                )
            )
        return fallback_rows

    def _snapshot_staging_rows(self) -> list[StagingAffiliation]:
        """Legacy method - kept for watermark advancement."""
        stmt = (
            select(StagingAffiliation)
            .where(StagingAffiliation.run_id == self.run.id)
            .order_by(StagingAffiliation.sequence_number.asc())
        )
        return list(self.session.scalars(stmt))

    def _apply_row(self, clean_row: CleanAffiliation) -> str:
        # Get normalized payload from clean_affiliation payload_json
        payload = clean_row.payload_json or {}
        external_id = clean_row.external_id or payload.get("external_id")

        if not external_id:
            current_app.logger.warning("Salesforce import run %s skipping affiliation with no external_id", self.run.id)
            return "skipped"

        # Check if this affiliation was deleted in Salesforce
        metadata = payload.get("metadata", {})
        if metadata.get("core_state") == "IsDeleted":
            return self._handle_delete(external_id)

        # Look up contact and organization via ExternalIdMap
        contact_external_id = clean_row.contact_external_id or payload.get("contact_external_id")
        organization_external_id = clean_row.organization_external_id or payload.get("organization_external_id")

        if not contact_external_id or not organization_external_id:
            # This should have been caught by DQ, but handle gracefully
            _record_import_skip(
                self.session,
                self.run.id,
                ImportSkipType.MISSING_REQUIRED_FIELD,
                "Missing contact_external_id or organization_external_id",
                staging_affiliation_id=clean_row.staging_affiliation_id
                if hasattr(clean_row, "staging_affiliation_id")
                else None,
                clean_affiliation_id=clean_row.id if hasattr(clean_row, "id") else None,
                entity_type="affiliation",
                record_key=external_id,
                details_json={
                    "contact_external_id": contact_external_id,
                    "organization_external_id": organization_external_id,
                    "external_id": external_id,
                },
            )
            return "skipped"

        # Look up contact
        contact_map = self._get_external_map("salesforce_contact", contact_external_id)
        if not contact_map or not contact_map.is_active:
            _record_import_skip(
                self.session,
                self.run.id,
                ImportSkipType.MISSING_REFERENCE,
                f"Contact not found in ExternalIdMap: {contact_external_id}",
                staging_affiliation_id=clean_row.staging_affiliation_id
                if hasattr(clean_row, "staging_affiliation_id")
                else None,
                clean_affiliation_id=clean_row.id if hasattr(clean_row, "id") else None,
                entity_type="affiliation",
                record_key=external_id,
                details_json={
                    "contact_external_id": contact_external_id,
                    "organization_external_id": organization_external_id,
                    "external_id": external_id,
                    "missing_reference": "contact",
                },
            )
            return "skipped"

        # Look up organization
        organization_map = self._get_external_map("salesforce_organization", organization_external_id)
        if not organization_map or not organization_map.is_active:
            _record_import_skip(
                self.session,
                self.run.id,
                ImportSkipType.MISSING_REFERENCE,
                f"Organization not found in ExternalIdMap: {organization_external_id}",
                staging_affiliation_id=clean_row.staging_affiliation_id
                if hasattr(clean_row, "staging_affiliation_id")
                else None,
                clean_affiliation_id=clean_row.id if hasattr(clean_row, "id") else None,
                entity_type="affiliation",
                record_key=external_id,
                details_json={
                    "contact_external_id": contact_external_id,
                    "organization_external_id": organization_external_id,
                    "external_id": external_id,
                    "missing_reference": "organization",
                },
            )
            return "skipped"

        contact_id = contact_map.entity_id
        organization_id = organization_map.entity_id

        # Check if ExternalIdMap entry exists for this affiliation
        payload_hash = self._compute_payload_hash(payload)
        map_entry = self._get_external_map(ENTITY_TYPE, external_id)

        if map_entry is None:
            return self._handle_create(external_id, payload, payload_hash, clean_row, contact_id, organization_id)
        else:
            return self._handle_update(map_entry, payload, payload_hash, clean_row, contact_id, organization_id)

    def _get_external_map(self, entity_type: str, external_id: str) -> ExternalIdMap | None:
        stmt = (
            select(ExternalIdMap)
            .where(
                ExternalIdMap.external_system == "salesforce",
                ExternalIdMap.external_id == external_id,
                ExternalIdMap.entity_type == entity_type,
            )
            .with_for_update(of=ExternalIdMap)
        )
        return self.session.scalars(stmt).first()

    def _handle_create(
        self,
        external_id: str,
        payload: Mapping[str, object],
        payload_hash: str,
        clean_row: CleanAffiliation,
        contact_id: int,
        organization_id: int,
    ) -> str:
        # Check if ContactOrganization already exists (unique constraint on contact_id, organization_id)
        existing = (
            self.session.query(ContactOrganization)
            .filter_by(contact_id=contact_id, organization_id=organization_id)
            .first()
        )

        if existing:
            # Update existing record instead of creating duplicate
            return self._update_contact_organization(
                existing,
                payload,
                payload_hash,
                clean_row,
                external_id,
                contact_id,
                organization_id,
                is_new_external_map=True,
            )

        # Create ContactOrganization record
        is_primary = payload.get("is_primary") is True
        start_date = self._parse_date(payload.get("start_date"))
        end_date = self._parse_date(payload.get("end_date"))
        status = payload.get("metadata", {}).get("status", "")

        # If status is not "Current", set end_date if not already set
        if status and status.lower() != "current" and not end_date:
            end_date = date.today()

        contact_org = ContactOrganization(
            contact_id=contact_id,
            organization_id=organization_id,
            is_primary=is_primary,
            start_date=start_date or date.today(),
            end_date=end_date,
        )
        self.session.add(contact_org)
        self.session.flush()

        # If this is primary, deactivate other primary affiliations for this contact
        if is_primary:
            self._deactivate_other_primary_affiliations(contact_id, contact_org.id)

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
        if payload_metadata.get("role"):
            metadata_dict["role"] = payload_metadata.get("role")
        if payload_metadata.get("status"):
            metadata_dict["status"] = payload_metadata.get("status")

        entry = ExternalIdMap(
            entity_type=ENTITY_TYPE,
            entity_id=contact_org.id,
            external_system="salesforce",
            external_id=external_id,
            metadata_json=metadata_dict,
        )
        entry.mark_seen(run_id=self.run.id)
        self.session.add(entry)

        # Update clean_row
        clean_row.load_action = "inserted"
        clean_row.core_contact_organization_id = contact_org.id

        return "created"

    def _handle_update(
        self,
        entry: ExternalIdMap,
        payload: Mapping[str, object],
        payload_hash: str,
        clean_row: CleanAffiliation,
        contact_id: int,
        organization_id: int,
    ) -> str:
        current = entry.metadata_json or {}
        previous_hash = current.get("payload_hash")

        # Get the ContactOrganization record
        contact_org = self.session.get(ContactOrganization, entry.entity_id)
        if contact_org is None:
            # ExternalIdMap exists but ContactOrganization doesn't - treat as create
            return self._handle_create(
                clean_row.external_id or "", payload, payload_hash, clean_row, contact_id, organization_id
            )

        # Check if payload changed
        if previous_hash == payload_hash:
            entry.mark_seen(run_id=self.run.id)
            clean_row.load_action = "unchanged"
            clean_row.core_contact_organization_id = contact_org.id
            return "unchanged"

        # Update ContactOrganization fields
        is_primary = bool(payload.get("is_primary", False))
        start_date = self._parse_date(payload.get("start_date"))
        end_date = self._parse_date(payload.get("end_date"))
        status = payload.get("metadata", {}).get("status", "")

        # If status changed from "Current" to something else, set end_date
        previous_status = current.get("status", "")
        if (
            previous_status
            and previous_status.lower() == "current"
            and status
            and status.lower() != "current"
            and not end_date
        ):
            end_date = date.today()

        was_primary = contact_org.is_primary
        contact_org.is_primary = is_primary
        if start_date:
            contact_org.start_date = start_date
        if end_date is not None:
            contact_org.end_date = end_date

        # If this became primary, deactivate other primary affiliations
        if is_primary and not was_primary:
            self._deactivate_other_primary_affiliations(contact_id, contact_org.id)

        # Update ExternalIdMap
        entry.is_active = True
        entry.deactivated_at = None
        entry.upstream_deleted_reason = None
        entry.mark_seen(run_id=self.run.id)

        # Update metadata
        metadata_dict = {
            "payload_hash": payload_hash,
            "last_payload": payload,
        }
        payload_metadata = payload.get("metadata", {})
        if payload_metadata.get("source_modstamp"):
            metadata_dict["source_modstamp"] = payload_metadata.get("source_modstamp")
        if payload_metadata.get("source_last_modified"):
            metadata_dict["source_last_modified"] = payload_metadata.get("source_last_modified")
        if payload_metadata.get("role"):
            metadata_dict["role"] = payload_metadata.get("role")
        if payload_metadata.get("status"):
            metadata_dict["status"] = payload_metadata.get("status")
        entry.metadata_json = metadata_dict

        # Update clean_row
        clean_row.load_action = "updated"
        clean_row.core_contact_organization_id = contact_org.id

        return "updated"

    def _update_contact_organization(
        self,
        contact_org: ContactOrganization,
        payload: Mapping[str, object],
        payload_hash: str,
        clean_row: CleanAffiliation,
        external_id: str,
        contact_id: int,
        organization_id: int,
        is_new_external_map: bool = False,
    ) -> str:
        """Update existing ContactOrganization and create/update ExternalIdMap."""
        is_primary = bool(payload.get("is_primary", False))
        start_date = self._parse_date(payload.get("start_date"))
        end_date = self._parse_date(payload.get("end_date"))
        status = payload.get("metadata", {}).get("status", "")

        if status and status.lower() != "current" and not end_date:
            end_date = date.today()

        was_primary = contact_org.is_primary
        contact_org.is_primary = is_primary
        if start_date:
            contact_org.start_date = start_date
        if end_date is not None:
            contact_org.end_date = end_date

        if is_primary and not was_primary:
            self._deactivate_other_primary_affiliations(contact_id, contact_org.id)

        # Create or update ExternalIdMap
        if is_new_external_map:
            metadata_dict = {
                "payload_hash": payload_hash,
                "last_payload": payload,
            }
            payload_metadata = payload.get("metadata", {})
            if payload_metadata.get("source_modstamp"):
                metadata_dict["source_modstamp"] = payload_metadata.get("source_modstamp")
            if payload_metadata.get("source_last_modified"):
                metadata_dict["source_last_modified"] = payload_metadata.get("source_last_modified")
            if payload_metadata.get("role"):
                metadata_dict["role"] = payload_metadata.get("role")
            if payload_metadata.get("status"):
                metadata_dict["status"] = payload_metadata.get("status")

            entry = ExternalIdMap(
                entity_type=ENTITY_TYPE,
                entity_id=contact_org.id,
                external_system="salesforce",
                external_id=external_id,
                metadata_json=metadata_dict,
            )
            entry.mark_seen(run_id=self.run.id)
            self.session.add(entry)
        else:
            # Update existing ExternalIdMap
            map_entry = self._get_external_map(ENTITY_TYPE, external_id)
            if map_entry:
                map_entry.mark_seen(run_id=self.run.id)
                metadata_dict = {
                    "payload_hash": payload_hash,
                    "last_payload": payload,
                }
                payload_metadata = payload.get("metadata", {})
                if payload_metadata.get("source_modstamp"):
                    metadata_dict["source_modstamp"] = payload_metadata.get("source_modstamp")
                if payload_metadata.get("source_last_modified"):
                    metadata_dict["source_last_modified"] = payload_metadata.get("source_last_modified")
                if payload_metadata.get("role"):
                    metadata_dict["role"] = payload_metadata.get("role")
                if payload_metadata.get("status"):
                    metadata_dict["status"] = payload_metadata.get("status")
                map_entry.metadata_json = metadata_dict

        clean_row.load_action = "updated"
        clean_row.core_contact_organization_id = contact_org.id

        return "updated"

    def _deactivate_other_primary_affiliations(self, contact_id: int, exclude_id: int) -> None:
        """Deactivate other primary affiliations for this contact."""
        other_primaries = (
            self.session.query(ContactOrganization)
            .filter(
                ContactOrganization.contact_id == contact_id,
                ContactOrganization.is_primary.is_(True),
                ContactOrganization.id != exclude_id,
            )
            .all()
        )
        for primary in other_primaries:
            primary.is_primary = False

    def _handle_delete(self, external_id: str) -> str:
        """Handle deletion of an affiliation."""
        map_entry = self._get_external_map(ENTITY_TYPE, external_id)
        if map_entry is None:
            return "unchanged"

        contact_org = self.session.get(ContactOrganization, map_entry.entity_id)
        if contact_org:
            # Set end_date to today
            contact_org.end_date = date.today()
            contact_org.is_primary = False

        map_entry.is_active = False
        map_entry.deactivated_at = datetime.now(timezone.utc)
        map_entry.upstream_deleted_reason = DELETE_REASON
        map_entry.mark_seen(run_id=self.run.id)

        return "deleted"

    def _parse_date(self, value: object) -> date | None:
        """Parse a date value from payload."""
        if value is None:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except (ValueError, AttributeError):
                return None
        return None

    def _compute_payload_hash(self, payload: Mapping[str, object]) -> str:
        """Compute SHA256 hash of normalized payload for change detection."""
        normalized = deepcopy(dict(payload))
        # Remove metadata fields that change on every import
        metadata = normalized.get("metadata", {})
        if isinstance(metadata, dict):
            metadata.pop("source_modstamp", None)
            metadata.pop("source_last_modified", None)
        normalized_json = json.dumps(normalized, sort_keys=True, default=str)
        return sha256(normalized_json.encode("utf-8")).hexdigest()

    def _advance_watermark(self, staging_rows: list[StagingAffiliation]) -> None:
        """Advance watermark to max SystemModstamp from staging rows."""
        if not staging_rows:
            return

        max_modstamp = None
        for row in staging_rows:
            payload = row.payload_json or {}
            modstamp_str = payload.get("SystemModstamp")
            if modstamp_str:
                try:
                    if modstamp_str.endswith("Z"):
                        modstamp_str = modstamp_str[:-1] + "+00:00"
                    modstamp = datetime.fromisoformat(modstamp_str)
                    if modstamp.tzinfo is None:
                        modstamp = modstamp.replace(tzinfo=timezone.utc)
                    if max_modstamp is None or modstamp > max_modstamp:
                        max_modstamp = modstamp
                except (ValueError, AttributeError):
                    continue

        if max_modstamp:
            watermark = (
                self.session.query(ImporterWatermark)
                .filter_by(adapter="salesforce", object_name="affiliations")
                .first()
            )
            if watermark:
                parsed_modstamp = max_modstamp.astimezone(timezone.utc)
                watermark.last_successful_modstamp = parsed_modstamp
                watermark.last_run_id = self.run.id
                self.session.add(watermark)
                record_salesforce_watermark(parsed_modstamp)

    def _persist_counters(self, counters: LoaderCounters) -> None:
        """Persist loader counters to ImportRun metrics."""
        metrics = dict(self.run.metrics_json or {})
        loader_metrics = metrics.setdefault("loader", {}).setdefault("affiliations", {})
        loader_metrics.update(counters.to_dict())
        self.run.metrics_json = metrics

    @contextmanager
    def _transaction(self):
        """Context manager for database transaction."""
        try:
            yield
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
