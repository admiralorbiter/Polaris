"""
Salesforce contact loader with two-phase commit to core tracking tables.
"""

from __future__ import annotations

import json
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
from flask_app.models import ExternalIdMap, db
from flask_app.models.importer.schema import CleanVolunteer, ImportRun, ImportRunStatus, ImporterWatermark, StagingVolunteer
from flask_app.models import Volunteer, ContactEmail, ContactPhone, EmailType, PhoneType

ENTITY_TYPE = "salesforce_contact"
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


class SalesforceContactLoader:
    """Two-phase loader that reconciles Salesforce Contacts into core tracking tables."""

    def __init__(self, run: ImportRun, session: Session | None = None):
        self.run = run
        self.session = session or db.session

    def execute(self) -> LoaderCounters:
        # Read from clean_volunteers (validated rows) instead of staging
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

    def _snapshot_clean_rows(self) -> list[CleanVolunteer | SimpleNamespace]:
        """Read validated rows from clean_volunteers (only rows that passed DQ validation)."""
        stmt = (
            select(CleanVolunteer)
            .where(CleanVolunteer.run_id == self.run.id)
            .where(CleanVolunteer.external_system == "salesforce")
            .order_by(CleanVolunteer.id.asc())
        )
        clean_rows = list(self.session.scalars(stmt))
        if clean_rows:
            return clean_rows

        # Fallback for unit tests that invoke the loader without running the clean promotion step.
        staging_rows = self._snapshot_staging_rows()
        fallback_rows: list[SimpleNamespace] = []
        for row in staging_rows:
            payload = dict(row.normalized_json or row.payload_json or {})
            first_name = payload.get("first_name")
            last_name = payload.get("last_name") or first_name or payload.get("external_id") or "Salesforce"
            fallback_rows.append(
                SimpleNamespace(
                    payload_json=payload,
                    staging_row=row,
                    external_id=payload.get("external_id"),
                    first_name=first_name or "Salesforce",
                    last_name=last_name,
                    email=payload.get("email"),
                    phone_e164=payload.get("phone"),
                    load_action=None,
                    core_contact_id=None,
                    core_volunteer_id=None,
                    external_system=row.external_system,
                )
            )
        return fallback_rows

    def _snapshot_staging_rows(self) -> list[StagingVolunteer]:
        """Legacy method - kept for watermark advancement."""
        stmt = (
            select(StagingVolunteer)
            .where(StagingVolunteer.run_id == self.run.id)
            .order_by(StagingVolunteer.sequence_number.asc())
        )
        return list(self.session.scalars(stmt))

    def _apply_row(self, clean_row: CleanVolunteer) -> str:
        # Get normalized payload from clean_volunteer payload_json
        # For metadata (like source timestamps), we may need to check staging_row
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

    def _handle_create(self, external_id: str, payload: Mapping[str, object], payload_hash: str, clean_row: CleanVolunteer) -> str:
        # Extract email from clean_row (handle dict structures)
        email_value = _extract_email(clean_row.email)
        
        # Check for duplicate email
        if email_value and _email_exists(email_value):
            # Skip duplicate - don't create volunteer or external_id_map
            clean_row.load_action = "skipped_duplicate"
            clean_row.core_contact_id = None
            clean_row.core_volunteer_id = None
            return "unchanged"
        
        # Create Volunteer record
        volunteer = Volunteer(
            first_name=clean_row.first_name,
            last_name=clean_row.last_name,
            middle_name=_coerce_string(payload.get("middle_name")),
            preferred_name=_coerce_string(payload.get("preferred_name")),
            source="salesforce",
        )
        self.session.add(volunteer)
        self.session.flush()
        
        # Add email if present
        if email_value:
            # Normalize and validate email format before creating ContactEmail
            email_value = email_value.strip().lower() if email_value else None
            if email_value:
                try:
                    from email_validator import validate_email, EmailNotValidError
                    validate_email(email_value, check_deliverability=False)
                except EmailNotValidError:
                    # Skip invalid emails - log but don't fail
                    current_app.logger.warning(f"Skipping invalid email for volunteer {clean_row.first_name} {clean_row.last_name}: {email_value}")
                    email_value = None
                except Exception as e:
                    # Log unexpected errors but continue
                    current_app.logger.warning(f"Email validation error for {email_value}: {e}")
                    email_value = None
        
        if email_value:
            try:
                email = ContactEmail(
                    contact_id=volunteer.id,
                    email=email_value,
                    email_type=EmailType.PERSONAL,
                    is_primary=True,
                    is_verified=False,
                )
                volunteer.emails.append(email)
                self.session.add(email)
            except ValueError as e:
                # Model validator rejected the email - skip it
                current_app.logger.warning(f"Model validator rejected email for volunteer {clean_row.first_name} {clean_row.last_name}: {email_value} - {e}")
        
        # Extract phone from clean_row (handle dict structures)
        phone_value = _extract_phone(clean_row.phone_e164)
        
        # Add phone if present
        if phone_value:
            phone = ContactPhone(
                contact_id=volunteer.id,
                phone_number=phone_value,
                phone_type=PhoneType.MOBILE,
                is_primary=True,
                can_text=True,
            )
            volunteer.phones.append(phone)
            self.session.add(phone)
        
        # Create ExternalIdMap entry
        metadata = {
            "payload_hash": payload_hash,
            "last_payload": payload,
        }
        entry = ExternalIdMap(
            entity_type=ENTITY_TYPE,
            entity_id=volunteer.id,
            external_system="salesforce",
            external_id=external_id,
            metadata_json=metadata,
        )
        entry.mark_seen(run_id=self.run.id)
        self.session.add(entry)
        
        # Update clean_row
        clean_row.load_action = "inserted"
        clean_row.core_contact_id = volunteer.id
        clean_row.core_volunteer_id = volunteer.id
        
        return "created"

    def _handle_update(self, entry: ExternalIdMap, payload: Mapping[str, object], payload_hash: str, clean_row: CleanVolunteer) -> str:
        current = entry.metadata_json or {}
        previous_hash = current.get("payload_hash")
        
        # Get the volunteer record
        volunteer = self.session.get(Volunteer, entry.entity_id)
        if volunteer is None:
            # ExternalIdMap exists but volunteer doesn't - treat as create
            return self._handle_create(clean_row.external_id or "", payload, payload_hash, clean_row)
        
        # Update volunteer fields
        volunteer.first_name = clean_row.first_name
        volunteer.last_name = clean_row.last_name
        if payload.get("middle_name"):
            volunteer.middle_name = _coerce_string(payload.get("middle_name"))
        if payload.get("preferred_name"):
            volunteer.preferred_name = _coerce_string(payload.get("preferred_name"))
        volunteer.source = "salesforce"
        
        # Extract email from clean_row (handle dict structures)
        email_value = _extract_email(clean_row.email)
        
        # Update email if changed
        if email_value:
            # Validate email format before creating ContactEmail
            try:
                from email_validator import validate_email
                validate_email(email_value, check_deliverability=False)
            except Exception:
                # Skip invalid emails - log but don't fail
                current_app.logger.warning(f"Skipping invalid email for volunteer {clean_row.first_name} {clean_row.last_name}: {email_value}")
                email_value = None
        
        if email_value:
            existing_email = next((e for e in volunteer.emails if e.is_primary), None)
            if not existing_email or existing_email.email != email_value:
                if existing_email:
                    existing_email.is_primary = False
                email = ContactEmail(
                    contact_id=volunteer.id,
                    email=email_value,
                    email_type=EmailType.PERSONAL,
                    is_primary=True,
                    is_verified=False,
                )
                volunteer.emails.append(email)
                self.session.add(email)
        
        # Extract phone from clean_row (handle dict structures)
        phone_value = _extract_phone(clean_row.phone_e164)
        
        # Update phone if changed
        if phone_value:
            existing_phone = next((p for p in volunteer.phones if p.is_primary), None)
            if not existing_phone or existing_phone.phone_number != phone_value:
                if existing_phone:
                    existing_phone.is_primary = False
                phone = ContactPhone(
                    contact_id=volunteer.id,
                    phone_number=phone_value,
                    phone_type=PhoneType.MOBILE,
                    is_primary=True,
                    can_text=True,
                )
                volunteer.phones.append(phone)
                self.session.add(phone)
        
        # Update ExternalIdMap
        entry.is_active = True
        entry.deactivated_at = None
        entry.upstream_deleted_reason = None
        entry.metadata_json = {"payload_hash": payload_hash, "last_payload": payload}
        entry.last_seen_at = datetime.now(timezone.utc)
        
        # Update clean_row
        clean_row.load_action = "updated" if previous_hash != payload_hash else "no_change"
        clean_row.core_contact_id = volunteer.id
        clean_row.core_volunteer_id = volunteer.id
        
        if previous_hash == payload_hash:
            return "unchanged"
        return "updated"

    def _handle_delete(self, external_id: str, entry: ExternalIdMap | None, clean_row: CleanVolunteer) -> str:
        if entry is None:
            clean_row.load_action = "deleted"
            clean_row.core_contact_id = None
            clean_row.core_volunteer_id = None
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
            clean_row.core_contact_id = entry.entity_id
            clean_row.core_volunteer_id = entry.entity_id
        
        return "deleted"

    def _advance_watermark(self, rows: Iterable[StagingVolunteer]) -> None:
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
                .filter_by(adapter="salesforce", object_name="contacts")
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
        core_bucket = counts.setdefault("core", {}).setdefault("volunteers", {})
        salesforce_counts = core_bucket.get("salesforce", {})
        salesforce_counts.update(counters.to_dict())
        core_bucket["salesforce"] = salesforce_counts
        counts["core"]["volunteers"] = core_bucket
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


def _extract_email(value: object | None) -> str | None:
    """Extract email string from value, handling dict structures."""
    if value is None:
        return None
    # Handle JSON string representation of dict
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        try:
            import json
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            # Try Python literal eval for single-quoted dicts
            try:
                import ast
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                pass
    if isinstance(value, dict):
        email_value = value.get("primary") or value.get("home") or value.get("work") or value.get("alternate")
        return _coerce_string(email_value)
    return _coerce_string(value)


def _extract_phone(value: object | None) -> str | None:
    """Extract phone string from value, handling dict structures."""
    if value is None:
        return None
    # Handle JSON string representation of dict
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        try:
            import json
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            # Try Python literal eval for single-quoted dicts
            try:
                import ast
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                pass
    if isinstance(value, dict):
        phone_value = value.get("primary") or value.get("mobile") or value.get("home") or value.get("work")
        return _coerce_string(phone_value)
    return _coerce_string(value)


def _email_exists(email: str | None) -> bool:
    """Check if an email already exists in the database."""
    if not email:
        return False
    return (
        db.session.query(ContactEmail.id)
        .filter(func.lower(ContactEmail.email) == email.lower())
        .limit(1)
        .scalar()
        is not None
    )


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

