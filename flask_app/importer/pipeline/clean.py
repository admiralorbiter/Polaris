"""
Promotion helpers for moving validated staging rows into the clean layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import MutableMapping

from flask import current_app, has_app_context

from flask_app.models.base import db
from flask_app.models.importer.schema import (
    CleanAffiliation,
    CleanOrganization,
    CleanVolunteer,
    StagingAffiliation,
    StagingOrganization,
    StagingRecordStatus,
    StagingVolunteer,
)


@dataclass(frozen=True)
class CleanVolunteerPayload:
    """Normalized payload used for core inserts."""

    staging_volunteer_id: int | None
    external_system: str
    external_id: str | None
    first_name: str
    last_name: str
    email: str | None
    phone_e164: str | None
    checksum: str | None
    normalized_payload: MutableMapping[str, object | None]


@dataclass(frozen=True)
class CleanOrganizationPayload:
    """Normalized payload used for core organization inserts."""

    staging_organization_id: int | None
    external_system: str
    external_id: str | None
    name: str
    checksum: str | None
    normalized_payload: MutableMapping[str, object | None]


@dataclass(frozen=True)
class CleanAffiliationPayload:
    """Normalized payload used for core affiliation inserts."""

    staging_affiliation_id: int | None
    external_system: str
    external_id: str | None
    contact_external_id: str | None
    organization_external_id: str | None
    checksum: str | None
    normalized_payload: MutableMapping[str, object | None]


@dataclass
class CleanPromotionSummary:
    """Aggregate results from promoting staging rows to the clean layer."""

    rows_considered: int
    rows_promoted: int
    rows_skipped: int
    dry_run: bool
    candidates: tuple[CleanVolunteerPayload, ...] = ()


def promote_clean_volunteers(import_run, *, dry_run: bool = False) -> CleanPromotionSummary:
    """
    Promote validated staging volunteers into the clean layer for further processing.
    """

    session = db.session
    rows = (
        session.query(StagingVolunteer)
        .filter(
            StagingVolunteer.run_id == import_run.id,
            StagingVolunteer.status == StagingRecordStatus.VALIDATED,
        )
        .order_by(StagingVolunteer.sequence_number)
    )

    rows_considered = 0
    rows_promoted = 0
    rows_skipped = 0
    candidates: list[CleanVolunteerPayload] = []

    for row in rows:
        rows_considered += 1
        payload = _build_payload(row)
        if payload is None:
            rows_skipped += 1
            continue

        if dry_run:
            candidates.append(payload)
            continue

        if row.clean_record is not None:
            rows_skipped += 1
            continue

        clean_row = CleanVolunteer(
            run_id=import_run.id,
            staging_volunteer_id=row.id,
            external_system=payload.external_system,
            external_id=payload.external_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            phone_e164=payload.phone_e164,
            checksum=payload.checksum,
            payload_json=dict(payload.normalized_payload),
            promoted_at=datetime.now(timezone.utc),
            load_action=None,
        )
        clean_row.staging_row = row
        session.add(clean_row)
        rows_promoted += 1

    summary = CleanPromotionSummary(
        rows_considered=rows_considered,
        rows_promoted=rows_promoted,
        rows_skipped=rows_skipped,
        dry_run=dry_run,
        candidates=tuple(candidates),
    )
    _update_clean_counts(import_run, summary)
    if has_app_context():
        current_app.logger.info(
            "Importer run %s promoted %s clean volunteers (skipped=%s, dry_run=%s)",
            import_run.id,
            summary.rows_promoted,
            summary.rows_skipped,
            summary.dry_run,
        )
    return summary


def _build_payload(row: StagingVolunteer) -> CleanVolunteerPayload | None:
    normalized = dict(row.normalized_json or {})
    raw = dict(row.payload_json or {})

    first_name = _coerce_string(normalized.get("first_name") or raw.get("first_name"))
    last_name = _coerce_string(normalized.get("last_name") or raw.get("last_name"))
    if not first_name or not last_name:
        return None

    external_system = (
        _coerce_string(normalized.get("external_system") or raw.get("external_system")) or row.external_system
    )
    external_id = _coerce_string(normalized.get("external_id") or raw.get("external_id") or row.external_id)

    email = _normalize_email(normalized.get("email") or normalized.get("email_normalized") or raw.get("email"))
    phone = _normalize_phone(normalized.get("phone_e164") or normalized.get("phone") or raw.get("phone"))

    normalized.update(
        {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone_e164": phone,
        }
    )

    return CleanVolunteerPayload(
        staging_volunteer_id=row.id,
        external_system=external_system,
        external_id=external_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone_e164=phone,
        checksum=row.checksum,
        normalized_payload=normalized,
    )


def _update_clean_counts(import_run, summary: CleanPromotionSummary) -> None:
    counts = dict(import_run.counts_json or {})
    clean_counts = counts.setdefault("clean", {}).setdefault("volunteers", {})
    clean_counts.update(
        {
            "rows_considered": summary.rows_considered,
            "rows_promoted": summary.rows_promoted if not summary.dry_run else 0,
            "rows_skipped": summary.rows_skipped,
            "dry_run": summary.dry_run,
        }
    )
    import_run.counts_json = counts

    metrics = dict(import_run.metrics_json or {})
    clean_metrics = metrics.setdefault("clean", {}).setdefault("volunteers", {})
    clean_metrics.update(
        {
            "rows_considered": summary.rows_considered,
            "rows_promoted": summary.rows_promoted,
            "rows_skipped": summary.rows_skipped,
            "dry_run": summary.dry_run,
        }
    )
    import_run.metrics_json = metrics


def _coerce_string(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_email(value: object | None) -> str | None:
    # Handle nested dict structures (e.g., Salesforce email.primary)
    if isinstance(value, dict):
        email_value = value.get("primary") or value.get("home") or value.get("work") or value.get("alternate")
        if email_value:
            token = _coerce_string(email_value)
            return token.lower() if token else None
        return None
    token = _coerce_string(value)
    return token.lower() or None


def _normalize_phone(value: object | None) -> str | None:
    # Handle nested dict structures (e.g., Salesforce phone.mobile)
    if isinstance(value, dict):
        phone_value = value.get("primary") or value.get("mobile") or value.get("home") or value.get("work")
        if phone_value:
            return _coerce_string(phone_value)
        return None
    token = _coerce_string(value)
    return token or None


def promote_clean_organizations(import_run, *, dry_run: bool = False) -> CleanPromotionSummary:
    """
    Promote validated staging organizations into the clean layer for further processing.
    """

    session = db.session
    rows = (
        session.query(StagingOrganization)
        .filter(
            StagingOrganization.run_id == import_run.id,
            StagingOrganization.status == StagingRecordStatus.VALIDATED,
        )
        .order_by(StagingOrganization.sequence_number)
    )

    rows_considered = 0
    rows_promoted = 0
    rows_skipped = 0
    candidates: list[CleanOrganizationPayload] = []

    for row in rows:
        rows_considered += 1
        payload = _build_organization_payload(row)
        if payload is None:
            rows_skipped += 1
            continue

        if dry_run:
            candidates.append(payload)
            continue

        if row.clean_record is not None:
            rows_skipped += 1
            continue

        clean_row = CleanOrganization(
            run_id=import_run.id,
            staging_organization_id=row.id,
            external_system=payload.external_system,
            external_id=payload.external_id,
            name=payload.name,
            checksum=payload.checksum,
            payload_json=dict(payload.normalized_payload),
            promoted_at=datetime.now(timezone.utc),
            load_action=None,
        )
        clean_row.staging_row = row
        session.add(clean_row)
        rows_promoted += 1

    summary = CleanPromotionSummary(
        rows_considered=rows_considered,
        rows_promoted=rows_promoted,
        rows_skipped=rows_skipped,
        dry_run=dry_run,
        candidates=tuple(candidates),
    )
    _update_clean_organization_counts(import_run, summary)
    if has_app_context():
        current_app.logger.info(
            "Importer run %s promoted %s clean organizations (skipped=%s, dry_run=%s)",
            import_run.id,
            summary.rows_promoted,
            summary.rows_skipped,
            summary.dry_run,
        )
    return summary


def _build_organization_payload(row: StagingOrganization) -> CleanOrganizationPayload | None:
    normalized = dict(row.normalized_json or {})
    raw = dict(row.payload_json or {})

    name = _coerce_string(normalized.get("name") or raw.get("Name"))
    if not name:
        return None

    external_system = (
        _coerce_string(normalized.get("external_system") or raw.get("external_system")) or row.external_system
    )
    external_id = _coerce_string(normalized.get("external_id") or raw.get("external_id") or row.external_id)

    normalized.update(
        {
            "name": name,
        }
    )

    return CleanOrganizationPayload(
        staging_organization_id=row.id,
        external_system=external_system,
        external_id=external_id,
        name=name,
        checksum=row.checksum,
        normalized_payload=normalized,
    )


def _update_clean_organization_counts(import_run, summary: CleanPromotionSummary) -> None:
    counts = dict(import_run.counts_json or {})
    clean_counts = counts.setdefault("clean", {}).setdefault("organizations", {})
    clean_counts.update(
        {
            "rows_considered": summary.rows_considered,
            "rows_promoted": summary.rows_promoted if not summary.dry_run else 0,
            "rows_skipped": summary.rows_skipped,
            "dry_run": summary.dry_run,
        }
    )
    import_run.counts_json = counts

    metrics = dict(import_run.metrics_json or {})
    clean_metrics = metrics.setdefault("clean", {}).setdefault("organizations", {})
    clean_metrics.update(
        {
            "rows_considered": summary.rows_considered,
            "rows_promoted": summary.rows_promoted,
            "rows_skipped": summary.rows_skipped,
            "dry_run": summary.dry_run,
        }
    )
    import_run.metrics_json = metrics


def promote_clean_affiliations(import_run, *, dry_run: bool = False) -> CleanPromotionSummary:
    """
    Promote validated staging affiliations into the clean layer for further processing.
    """

    session = db.session
    rows = (
        session.query(StagingAffiliation)
        .filter(
            StagingAffiliation.run_id == import_run.id,
            StagingAffiliation.status == StagingRecordStatus.VALIDATED,
        )
        .order_by(StagingAffiliation.sequence_number)
    )

    rows_considered = 0
    rows_promoted = 0
    rows_skipped = 0
    candidates: list[CleanAffiliationPayload] = []

    for row in rows:
        rows_considered += 1
        payload = _build_affiliation_payload(row)
        if payload is None:
            rows_skipped += 1
            continue

        if dry_run:
            candidates.append(payload)
            continue

        if row.clean_record is not None:
            rows_skipped += 1
            continue

        clean_row = CleanAffiliation(
            run_id=import_run.id,
            staging_affiliation_id=row.id,
            external_system=payload.external_system,
            external_id=payload.external_id,
            contact_external_id=payload.contact_external_id,
            organization_external_id=payload.organization_external_id,
            checksum=payload.checksum,
            payload_json=dict(payload.normalized_payload),
            promoted_at=datetime.now(timezone.utc),
            load_action=None,
        )
        clean_row.staging_row = row
        session.add(clean_row)
        rows_promoted += 1

    summary = CleanPromotionSummary(
        rows_considered=rows_considered,
        rows_promoted=rows_promoted,
        rows_skipped=rows_skipped,
        dry_run=dry_run,
        candidates=tuple(candidates),
    )
    _update_clean_affiliation_counts(import_run, summary)
    if has_app_context():
        current_app.logger.info(
            "Importer run %s promoted %s clean affiliations (skipped=%s, dry_run=%s)",
            import_run.id,
            summary.rows_promoted,
            summary.rows_skipped,
            summary.dry_run,
        )
    return summary


def _build_affiliation_payload(row: StagingAffiliation) -> CleanAffiliationPayload | None:
    normalized = dict(row.normalized_json or {})
    raw = dict(row.payload_json or {})

    contact_external_id = _coerce_string(normalized.get("contact_external_id") or raw.get("npe5__Contact__c"))
    organization_external_id = _coerce_string(
        normalized.get("organization_external_id") or raw.get("npe5__Organization__c")
    )

    if not contact_external_id or not organization_external_id:
        return None

    external_system = (
        _coerce_string(normalized.get("external_system") or raw.get("external_system")) or row.external_system
    )
    external_id = _coerce_string(normalized.get("external_id") or raw.get("external_id") or row.external_id)

    normalized.update(
        {
            "contact_external_id": contact_external_id,
            "organization_external_id": organization_external_id,
        }
    )

    return CleanAffiliationPayload(
        staging_affiliation_id=row.id,
        external_system=external_system,
        external_id=external_id,
        contact_external_id=contact_external_id,
        organization_external_id=organization_external_id,
        checksum=row.checksum,
        normalized_payload=normalized,
    )


def _update_clean_affiliation_counts(import_run, summary: CleanPromotionSummary) -> None:
    counts = dict(import_run.counts_json or {})
    clean_counts = counts.setdefault("clean", {}).setdefault("affiliations", {})
    clean_counts.update(
        {
            "rows_considered": summary.rows_considered,
            "rows_promoted": summary.rows_promoted if not summary.dry_run else 0,
            "rows_skipped": summary.rows_skipped,
            "dry_run": summary.dry_run,
        }
    )
    import_run.counts_json = counts

    metrics = dict(import_run.metrics_json or {})
    clean_metrics = metrics.setdefault("clean", {}).setdefault("affiliations", {})
    clean_metrics.update(
        {
            "rows_considered": summary.rows_considered,
            "rows_promoted": summary.rows_promoted,
            "rows_skipped": summary.rows_skipped,
            "dry_run": summary.dry_run,
        }
    )
    import_run.metrics_json = metrics
