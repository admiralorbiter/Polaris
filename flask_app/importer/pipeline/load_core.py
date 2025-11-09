"""
Create-only upsert helpers that load clean volunteers into the core schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, MutableMapping, Sequence

from flask import current_app, has_app_context
from sqlalchemy import func

from flask_app.models import (
    ContactEmail,
    ContactPhone,
    EmailType,
    PhoneType,
    Volunteer,
    db,
)
from flask_app.models.importer.schema import (
    CleanVolunteer,
    StagingRecordStatus,
    StagingVolunteer,
)
from .clean import CleanVolunteerPayload


@dataclass
class CoreLoadSummary:
    """Aggregate results from loading clean rows into the core schema."""

    rows_processed: int
    rows_inserted: int
    rows_skipped_duplicates: int
    duplicate_emails: tuple[str, ...]
    dry_run: bool


def load_core_volunteers(
    import_run,
    *,
    dry_run: bool = False,
    clean_candidates: Sequence[CleanVolunteerPayload] | None = None,
    batch_size: int = 100,
) -> CoreLoadSummary:
    """
    Insert clean volunteers into the core tables, skipping duplicates by email.
    """

    session = db.session
    duplicate_emails: list[str] = []

    if has_app_context():
        config = current_app.config
        if not config.get("IMPORTER_EMAIL_VALIDATION_INITIALIZED"):
            config.setdefault("EMAIL_VALIDATION_CHECK_DELIVERABILITY", False)
            config["IMPORTER_EMAIL_VALIDATION_INITIALIZED"] = True

    if dry_run:
        candidates = list(clean_candidates or _build_candidates_from_clean_rows(import_run))
        rows_inserted = 0
        rows_skipped = 0

        for candidate in candidates:
            exists = _email_exists(candidate.email)
            if exists:
                rows_skipped += 1
                if candidate.email:
                    duplicate_emails.append(candidate.email)
            else:
                rows_inserted += 1

        summary = CoreLoadSummary(
            rows_processed=len(candidates),
            rows_inserted=0,
            rows_skipped_duplicates=rows_skipped,
            duplicate_emails=tuple(filter(None, duplicate_emails)),
            dry_run=True,
        )
        _update_core_counts(import_run, summary, potential_inserts=rows_inserted)
        return summary

    clean_rows: Iterable[CleanVolunteer] = (
        session.query(CleanVolunteer)
        .filter(CleanVolunteer.run_id == import_run.id)
        .order_by(CleanVolunteer.id)
    )

    rows_processed = 0
    rows_inserted = 0
    rows_skipped = 0

    for clean_row in clean_rows:
        rows_processed += 1
        candidate = _candidate_from_clean_row(clean_row)
        staging_row = clean_row.staging_row

        if candidate.email and _email_exists(candidate.email):
            rows_skipped += 1
            duplicate_emails.append(candidate.email)
            clean_row.load_action = "skipped_duplicate"
            clean_row.core_contact_id = None
            clean_row.core_volunteer_id = None
            if staging_row is not None:
                _mark_staging_loaded(staging_row, duplicate=True)
            _log_duplicate(candidate.email, import_run.id)
            continue

        volunteer = Volunteer(
            first_name=candidate.first_name,
            last_name=candidate.last_name,
            preferred_name=_coerce_string(candidate.normalized_payload.get("preferred_name")),
            middle_name=_coerce_string(candidate.normalized_payload.get("middle_name")),
            source=candidate.external_system,
        )
        session.add(volunteer)
        session.flush()

        if candidate.email:
            session.add(
                ContactEmail(
                    contact_id=volunteer.id,
                    email=candidate.email,
                    email_type=EmailType.PERSONAL,
                    is_primary=True,
                    is_verified=False,
                )
            )
        if candidate.phone_e164:
            session.add(
                ContactPhone(
                    contact_id=volunteer.id,
                    phone_number=candidate.phone_e164,
                    phone_type=PhoneType.MOBILE,
                    is_primary=True,
                    can_text=True,
                )
            )

        clean_row.load_action = "inserted"
        clean_row.core_contact_id = volunteer.id
        clean_row.core_volunteer_id = volunteer.id
        if staging_row is not None:
            _mark_staging_loaded(staging_row, duplicate=False)

        rows_inserted += 1

        if rows_inserted % batch_size == 0:
            session.flush()

    summary = CoreLoadSummary(
        rows_processed=rows_processed,
        rows_inserted=rows_inserted,
        rows_skipped_duplicates=rows_skipped,
        duplicate_emails=tuple(duplicate_emails),
        dry_run=False,
    )
    _update_core_counts(import_run, summary)
    if has_app_context():
        current_app.logger.info(
            "Importer run %s loaded %s volunteers (duplicates=%s)",
            import_run.id,
            summary.rows_inserted,
            summary.rows_skipped_duplicates,
        )
    return summary


def _build_candidates_from_clean_rows(import_run) -> list[CleanVolunteerPayload]:
    session = db.session
    rows = (
        session.query(CleanVolunteer)
        .filter(CleanVolunteer.run_id == import_run.id)
        .order_by(CleanVolunteer.id)
    )
    return [_candidate_from_clean_row(row) for row in rows]


def _candidate_from_clean_row(clean_row: CleanVolunteer) -> CleanVolunteerPayload:
    payload: MutableMapping[str, object | None] = dict(clean_row.payload_json or {})
    payload.setdefault("first_name", clean_row.first_name)
    payload.setdefault("last_name", clean_row.last_name)
    payload.setdefault("email", clean_row.email)
    payload.setdefault("phone_e164", clean_row.phone_e164)

    return CleanVolunteerPayload(
        staging_volunteer_id=clean_row.staging_volunteer_id,
        external_system=clean_row.external_system,
        external_id=clean_row.external_id,
        first_name=clean_row.first_name,
        last_name=clean_row.last_name,
        email=clean_row.email,
        phone_e164=clean_row.phone_e164,
        checksum=clean_row.checksum,
        normalized_payload=payload,
    )


def _email_exists(email: str | None) -> bool:
    if not email:
        return False
    return (
        db.session.query(ContactEmail.id)
        .filter(func.lower(ContactEmail.email) == email.lower())
        .limit(1)
        .scalar()
        is not None
    )


def _mark_staging_loaded(staging_row: StagingVolunteer, *, duplicate: bool) -> None:
    staging_row.status = StagingRecordStatus.LOADED
    staging_row.processed_at = datetime.now(timezone.utc)
    staging_row.last_error = "Skipped duplicate by email" if duplicate else None


def _log_duplicate(email: str | None, run_id: int) -> None:
    if not email:
        return
    if has_app_context():
        current_app.logger.info("Importer run %s skipped duplicate email %s", run_id, email)


def _update_core_counts(
    import_run,
    summary: CoreLoadSummary,
    *,
    potential_inserts: int | None = None,
) -> None:
    counts = dict(import_run.counts_json or {})
    core_counts = counts.setdefault("core", {}).setdefault("volunteers", {})
    core_counts.update(
        {
            "rows_processed": summary.rows_processed,
            "rows_inserted": summary.rows_inserted if not summary.dry_run else 0,
            "rows_skipped_duplicates": summary.rows_skipped_duplicates,
            "dry_run": summary.dry_run,
        }
    )
    import_run.counts_json = counts

    metrics = dict(import_run.metrics_json or {})
    core_metrics = metrics.setdefault("core", {}).setdefault("volunteers", {})
    core_metrics.update(
        {
            "rows_processed": summary.rows_processed,
            "rows_inserted": summary.rows_inserted if potential_inserts is None else potential_inserts,
            "rows_skipped_duplicates": summary.rows_skipped_duplicates,
            "dry_run": summary.dry_run,
        }
    )
    import_run.metrics_json = metrics


def _coerce_string(value: object | None) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


