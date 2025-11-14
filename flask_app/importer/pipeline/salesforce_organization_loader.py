"""
Salesforce Account (Organization) loader with two-phase commit to core tracking tables.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable, Mapping
from copy import deepcopy

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from flask import current_app

from types import SimpleNamespace

from flask_app.importer.metrics import record_salesforce_rows, record_salesforce_watermark
from flask_app.importer.pipeline.load_core import _record_import_skip
from flask_app.models import ExternalIdMap, db
from flask_app.models.importer.schema import (
    CleanOrganization,
    ImportRun,
    ImportRunStatus,
    ImportSkip,
    ImportSkipType,
    ImporterWatermark,
    StagingOrganization,
    StagingRecordStatus,
)
from flask_app.models.organization import Organization
from flask_app.models.contact.enums import OrganizationType

ENTITY_TYPE = "salesforce_organization"
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


class SalesforceOrganizationLoader:
    """Two-phase loader that reconciles Salesforce Accounts into core Organization tables."""

    def __init__(self, run: ImportRun, session: Session | None = None):
        self.run = run
        self.session = session or db.session

    def execute(self) -> LoaderCounters:
        # Read from clean_organizations (validated rows) instead of staging
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

    def _snapshot_clean_rows(self) -> list[CleanOrganization | SimpleNamespace]:
        """Read validated rows from clean_organizations (only rows that passed DQ validation)."""
        stmt = (
            select(CleanOrganization)
            .where(CleanOrganization.run_id == self.run.id)
            .where(CleanOrganization.external_system == "salesforce")
            .order_by(CleanOrganization.id.asc())
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
            # Use actual name from payload, don't default (clean promotion would have skipped if name was required)
            name = payload.get("name") or payload.get("Name") or ""
            fallback_rows.append(
                SimpleNamespace(
                    payload_json=payload,
                    staging_row=row,
                    external_id=payload.get("external_id"),
                    name=name,
                    load_action=None,
                    core_organization_id=None,
                    external_system=row.external_system,
                    staging_organization_id=row.id,
                )
            )
        return fallback_rows

    def _snapshot_staging_rows(self) -> list[StagingOrganization]:
        """Legacy method - kept for watermark advancement."""
        stmt = (
            select(StagingOrganization)
            .where(StagingOrganization.run_id == self.run.id)
            .order_by(StagingOrganization.sequence_number.asc())
        )
        return list(self.session.scalars(stmt))

    def _apply_row(self, clean_row: CleanOrganization) -> str:
        # Get normalized payload from clean_organization payload_json
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

    def _handle_create(self, external_id: str, payload: Mapping[str, object], payload_hash: str, clean_row: CleanOrganization) -> str:
        name = clean_row.name or payload.get("name") or ""
        if not name:
            # Record skip for missing name
            staging_organization_id = None
            clean_organization_id = None
            if hasattr(clean_row, 'staging_organization_id'):
                staging_organization_id = clean_row.staging_organization_id
            elif hasattr(clean_row, 'staging_row') and clean_row.staging_row:
                staging_organization_id = clean_row.staging_row.id if hasattr(clean_row.staging_row, 'id') else None
            if hasattr(clean_row, 'id'):
                clean_organization_id = clean_row.id
            
            _record_import_skip(
                self.session,
                self.run.id,
                ImportSkipType.MISSING_REQUIRED_FIELD,
                "Organization name is required.",
                staging_organization_id=staging_organization_id,
                clean_organization_id=clean_organization_id,
                entity_type="organization",
                record_key=external_id,
                details_json={"external_id": external_id, "missing_field": "name"},
            )
            return "unchanged"
        
        # Check for duplicate name (case-insensitive)
        name_match_org = _name_exists_exact_org(name)
        
        if name_match_org:
            # Merge: link external_id to existing organization and add note
            existing_map = (
                self.session.query(ExternalIdMap)
                .filter(
                    ExternalIdMap.entity_type == ENTITY_TYPE,
                    ExternalIdMap.external_system == "salesforce",
                    ExternalIdMap.external_id == external_id,
                )
                .first()
            )
            if not existing_map:
                entry = ExternalIdMap(
                    entity_type=ENTITY_TYPE,
                    entity_id=name_match_org.id,
                    external_system="salesforce",
                    external_id=external_id,
                    metadata_json={"payload_hash": payload_hash, "last_payload": payload},
                )
                entry.mark_seen(run_id=self.run.id)
                self.session.add(entry)
            
            # Add note about Salesforce import
            note_text = f"Linked from Salesforce import (run {self.run.id}, external_id: {external_id})"
            if name_match_org.description:
                if note_text not in name_match_org.description:
                    name_match_org.description = f"{name_match_org.description}\n\n{note_text}"
            else:
                name_match_org.description = note_text
            
            clean_row.load_action = "skipped_duplicate"
            clean_row.core_organization_id = name_match_org.id
            
            # Record skip
            staging_organization_id = None
            clean_organization_id = None
            if hasattr(clean_row, 'staging_organization_id'):
                staging_organization_id = clean_row.staging_organization_id
            elif hasattr(clean_row, 'staging_row') and clean_row.staging_row:
                staging_organization_id = clean_row.staging_row.id if hasattr(clean_row.staging_row, 'id') else None
            if hasattr(clean_row, 'id'):
                clean_organization_id = clean_row.id
            
            _record_import_skip(
                self.session,
                self.run.id,
                ImportSkipType.DUPLICATE_NAME,
                f"Duplicate organization name: {name} (matched organization ID: {name_match_org.id})",
                staging_organization_id=staging_organization_id,
                clean_organization_id=clean_organization_id,
                entity_type="organization",
                record_key=name,
                details_json={
                    "name": name,
                    "matched_organization_id": name_match_org.id,
                    "external_id": external_id,
                },
            )
            current_app.logger.info(
                "Salesforce import run %s skipped duplicate organization by name: %s",
                self.run.id, name
            )
            return "unchanged"
        
        # Create Organization record
        slug = _generate_unique_slug(name, self.session)
        organization = Organization(
            name=name,
            description=_coerce_string(payload.get("description")),
            slug=slug,
            is_active=True,
            organization_type=_map_organization_type(payload.get("organization_type")),
        )
        self.session.add(organization)
        self.session.flush()
        
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
        if payload_metadata.get("last_activity_date"):
            metadata_dict["last_activity_date"] = payload_metadata.get("last_activity_date")
        
        entry = ExternalIdMap(
            entity_type=ENTITY_TYPE,
            entity_id=organization.id,
            external_system="salesforce",
            external_id=external_id,
            metadata_json=metadata_dict,
        )
        entry.mark_seen(run_id=self.run.id)
        self.session.add(entry)
        
        # Update clean_row
        clean_row.load_action = "inserted"
        clean_row.core_organization_id = organization.id
        
        return "created"

    def _handle_update(self, entry: ExternalIdMap, payload: Mapping[str, object], payload_hash: str, clean_row: CleanOrganization) -> str:
        current = entry.metadata_json or {}
        previous_hash = current.get("payload_hash")
        
        # Get the organization record
        organization = self.session.get(Organization, entry.entity_id)
        if organization is None:
            # ExternalIdMap exists but organization doesn't - treat as create
            return self._handle_create(clean_row.external_id or "", payload, payload_hash, clean_row)
        
        # Update organization fields
        name = clean_row.name or payload.get("name") or organization.name
        if name != organization.name:
            organization.name = name
            # Regenerate slug if name changed
            organization.slug = _generate_unique_slug(name, self.session, exclude_id=organization.id)
        
        if payload.get("description"):
            organization.description = _coerce_string(payload.get("description"))
        
        if payload.get("organization_type"):
            org_type = _map_organization_type(payload.get("organization_type"))
            if org_type:
                organization.organization_type = org_type
        
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
        if payload_metadata.get("last_activity_date"):
            metadata_dict["last_activity_date"] = payload_metadata.get("last_activity_date")
        
        entry.metadata_json = metadata_dict
        entry.last_seen_at = datetime.now(timezone.utc)
        
        # Update clean_row
        clean_row.load_action = "updated" if previous_hash != payload_hash else "no_change"
        clean_row.core_organization_id = organization.id
        
        if previous_hash == payload_hash:
            return "unchanged"
        return "updated"

    def _handle_delete(self, external_id: str, entry: ExternalIdMap | None, clean_row: CleanOrganization) -> str:
        if entry is None:
            clean_row.load_action = "deleted"
            clean_row.core_organization_id = None
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
            clean_row.core_organization_id = entry.entity_id
        
        return "deleted"

    def _advance_watermark(self, rows: Iterable[StagingOrganization]) -> None:
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
                .filter_by(adapter="salesforce", object_name="accounts")
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
        core_bucket = counts.setdefault("core", {}).setdefault("organizations", {})
        salesforce_counts = core_bucket.get("salesforce", {})
        salesforce_counts.update(counters.to_dict())
        core_bucket["salesforce"] = salesforce_counts
        counts["core"]["organizations"] = core_bucket
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


def _name_exists_exact_org(name: str) -> Organization | None:
    """Check if an organization with the same name already exists (case-insensitive)."""
    if not name:
        return None
    return (
        db.session.query(Organization)
        .filter(func.lower(Organization.name) == name.lower())
        .first()
    )


def _generate_unique_slug(name: str, session: Session, exclude_id: int | None = None) -> str:
    """Generate a unique slug from organization name."""
    # Convert to lowercase
    slug = name.lower()
    # Replace spaces and underscores with hyphens
    slug = re.sub(r"[_\s]+", "-", slug)
    # Remove all non-alphanumeric characters except hyphens
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)
    # Remove leading/trailing hyphens
    slug = slug.strip("-")
    
    if not slug:
        slug = "organization"
    
    # Ensure uniqueness
    base_slug = slug
    counter = 1
    while True:
        query = session.query(Organization).filter_by(slug=slug)
        if exclude_id:
            query = query.filter(Organization.id != exclude_id)
        existing = query.first()
        if not existing:
            break
        slug = f"{base_slug}-{counter}"
        counter += 1
    
    return slug


def _map_organization_type(value: object | None) -> OrganizationType | None:
    """Map normalized organization type string to OrganizationType enum."""
    if not value:
        return None
    type_str = str(value).strip().lower()
    if not type_str:
        return None
    
    # Map normalized values to enum
    type_map = {
        "school": OrganizationType.SCHOOL,
        "business": OrganizationType.BUSINESS,
        "non_profit": OrganizationType.NON_PROFIT,
        "government": OrganizationType.GOVERNMENT,
        "other": OrganizationType.OTHER,
    }
    
    return type_map.get(type_str, OrganizationType.OTHER)


def _coerce_string(value: object | None) -> str | None:
    """Coerce a value to a string, returning None for empty strings."""
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def _safe_parse_datetime(value: str) -> datetime:
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

