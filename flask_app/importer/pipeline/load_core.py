"""
Create-only upsert helpers that load clean volunteers into the core schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, MutableMapping, Sequence

from flask import current_app, has_app_context
from sqlalchemy import func

from config.monitoring import ImporterMonitoring
from flask_app.models import ContactEmail, ContactPhone, EmailType, PhoneType, Volunteer, db
from flask_app.models.importer.schema import (
    ChangeLogEntry,
    CleanVolunteer,
    ExternalIdMap,
    StagingRecordStatus,
    StagingVolunteer,
)

from .clean import CleanVolunteerPayload
from .idempotency import MissingExternalIdentifier, resolve_import_target


@dataclass
class CoreLoadSummary:
    """Aggregate results from loading clean rows into the core schema."""

    rows_processed: int
    rows_created: int
    rows_updated: int
    rows_reactivated: int
    rows_skipped_duplicates: int
    rows_skipped_no_change: int
    rows_missing_external_id: int
    rows_soft_deleted: int
    duplicate_emails: tuple[str, ...]
    dry_run: bool

    _legacy_rows_inserted: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_legacy_rows_inserted", self.rows_created)

    @property
    def rows_inserted(self) -> int:
        """
        Backwards-compatible alias for pre-idempotency callers.
        """

        return self._legacy_rows_inserted

    @property
    def rows_changed(self) -> int:
        """
        Alias for downstream code that expects a derived \"rows_changed\" metric.
        """

        return self.rows_updated


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
        rows_skipped_duplicates = 0
        rows_created = 0
        rows_missing_external_id = 0

        for candidate in candidates:
            if not candidate.external_id:
                rows_missing_external_id += 1
                continue

            exists = _email_exists(candidate.email)
            if exists:
                rows_skipped_duplicates += 1
                if candidate.email:
                    duplicate_emails.append(candidate.email)
            else:
                rows_created += 1

        summary = CoreLoadSummary(
            rows_processed=len(candidates),
            rows_created=0,
            rows_updated=0,
            rows_reactivated=0,
            rows_skipped_duplicates=rows_skipped_duplicates,
            rows_skipped_no_change=0,
            rows_missing_external_id=rows_missing_external_id,
            rows_soft_deleted=0,
            duplicate_emails=tuple(filter(None, duplicate_emails)),
            dry_run=True,
        )
        _update_core_counts(import_run, summary, potential_inserts=rows_created)
        return summary

    clean_rows: Iterable[CleanVolunteer] = (
        session.query(CleanVolunteer).filter(CleanVolunteer.run_id == import_run.id).order_by(CleanVolunteer.id)
    )

    rows_processed = 0
    rows_created = 0
    rows_updated = 0
    rows_reactivated = 0
    rows_skipped_duplicates = 0
    rows_skipped_no_change = 0
    rows_missing_external_id = 0
    rows_soft_deleted = 0

    for clean_row in clean_rows:
        rows_processed += 1
        candidate = _candidate_from_clean_row(clean_row)
        staging_row = clean_row.staging_row

        try:
            target = resolve_import_target(
                session=session,
                run_id=import_run.id,
                external_system=candidate.external_system,
                external_id=candidate.external_id,
            )
        except MissingExternalIdentifier as exc:
            rows_missing_external_id += 1
            clean_row.load_action = "error_missing_external_id"
            clean_row.core_contact_id = None
            clean_row.core_volunteer_id = None
            if staging_row is not None:
                _mark_staging_error(staging_row, message=str(exc))
            continue

        if target.action == "create":
            if candidate.email and _email_exists(candidate.email):
                rows_skipped_duplicates += 1
                if candidate.email:
                    duplicate_emails.append(candidate.email)
                clean_row.load_action = "skipped_duplicate"
                clean_row.core_contact_id = None
                clean_row.core_volunteer_id = None
                if staging_row is not None:
                    _mark_staging_loaded(staging_row, duplicate=True)
                _log_duplicate(candidate.email, import_run.id)
                continue

            volunteer = _create_volunteer_from_candidate(candidate)
            session.flush()

            id_map = ExternalIdMap(
                run_id=import_run.id,
                entity_type="volunteer",
                entity_id=volunteer.id,
                external_system=candidate.external_system,
                external_id=candidate.external_id,
            )
            id_map.mark_seen(run_id=import_run.id)
            session.add(id_map)

            clean_row.load_action = "inserted"
            clean_row.core_contact_id = volunteer.id
            clean_row.core_volunteer_id = volunteer.id
            if staging_row is not None:
                _mark_staging_loaded(staging_row, duplicate=False)

            rows_created += 1
        else:
            volunteer = target.volunteer
            id_map = target.id_map

            if volunteer is None:
                volunteer = _create_volunteer_from_candidate(candidate)
                session.flush()
                rows_created += 1
            else:
                session.flush()

            if id_map is None:
                raise RuntimeError("resolve_import_target returned update/reactivate without external_id_map")

            id_map.entity_id = volunteer.id
            id_map.mark_seen(run_id=import_run.id)

            changes = _apply_updates(volunteer, candidate)

            if target.action == "reactivate":
                rows_reactivated += 1

            if not changes:
                rows_skipped_no_change += 1
                clean_row.load_action = "reactivated" if target.action == "reactivate" else "skipped_no_change"
            else:
                rows_updated += 1
                clean_row.load_action = "reactivated" if target.action == "reactivate" else "updated"
                _persist_change_log(
                    import_run_id=import_run.id,
                    volunteer_id=volunteer.id,
                    changes=changes,
                    idempotency_action=target.action,
                    external_system=candidate.external_system,
                    external_id=candidate.external_id,
                )

            clean_row.core_contact_id = volunteer.id
            clean_row.core_volunteer_id = volunteer.id
            if staging_row is not None:
                _mark_staging_loaded(staging_row, duplicate=False)

        processed_mutations = rows_created + rows_updated
        if processed_mutations and processed_mutations % batch_size == 0:
            session.flush()

    summary = CoreLoadSummary(
        rows_processed=rows_processed,
        rows_created=rows_created,
        rows_updated=rows_updated,
        rows_reactivated=rows_reactivated,
        rows_skipped_duplicates=rows_skipped_duplicates,
        rows_skipped_no_change=rows_skipped_no_change,
        rows_missing_external_id=rows_missing_external_id,
        rows_soft_deleted=rows_soft_deleted,
        duplicate_emails=tuple(duplicate_emails),
        dry_run=False,
    )
    _update_core_counts(import_run, summary)
    if not summary.dry_run:
        ImporterMonitoring.record_idempotent_outcomes(
            source=getattr(import_run, "source", None),
            created=summary.rows_created,
            updated=summary.rows_updated,
            skipped=summary.rows_skipped_no_change,
        )
    if has_app_context():
        current_app.logger.info(
            (
                "Importer run %s loaded %s volunteers "
                "(created=%s updated=%s reactivated=%s duplicates=%s "
                "no_change=%s missing_external_id=%s)"
            ),
            import_run.id,
            summary.rows_created + summary.rows_updated,
            summary.rows_created,
            summary.rows_updated,
            summary.rows_reactivated,
            summary.rows_skipped_duplicates,
            summary.rows_skipped_no_change,
            summary.rows_missing_external_id,
        )
    return summary


def _build_candidates_from_clean_rows(import_run) -> list[CleanVolunteerPayload]:
    session = db.session
    rows = session.query(CleanVolunteer).filter(CleanVolunteer.run_id == import_run.id).order_by(CleanVolunteer.id)
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
        db.session.query(ContactEmail.id).filter(func.lower(ContactEmail.email) == email.lower()).limit(1).scalar()
        is not None
    )


def _mark_staging_loaded(staging_row: StagingVolunteer, *, duplicate: bool) -> None:
    staging_row.status = StagingRecordStatus.LOADED
    staging_row.processed_at = datetime.now(timezone.utc)
    staging_row.last_error = "Skipped duplicate by email" if duplicate else None


def _mark_staging_error(staging_row: StagingVolunteer, *, message: str) -> None:
    staging_row.status = StagingRecordStatus.QUARANTINED
    staging_row.processed_at = datetime.now(timezone.utc)
    staging_row.last_error = message


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
    created_count = summary.rows_created if not summary.dry_run else 0
    updated_count = summary.rows_updated if not summary.dry_run else 0
    reactivated_count = summary.rows_reactivated if not summary.dry_run else 0
    changed_count = summary.rows_changed if not summary.dry_run else 0
    core_counts.update(
        {
            "rows_processed": summary.rows_processed,
            "rows_created": created_count,
            "rows_updated": updated_count,
            "rows_reactivated": reactivated_count,
            "rows_changed": changed_count,
            "rows_skipped_duplicates": summary.rows_skipped_duplicates,
            "rows_skipped_no_change": summary.rows_skipped_no_change,
            "rows_missing_external_id": summary.rows_missing_external_id,
            "rows_soft_deleted": summary.rows_soft_deleted,
            "dry_run": summary.dry_run,
        }
    )
    import_run.counts_json = counts

    metrics = dict(import_run.metrics_json or {})
    core_metrics = metrics.setdefault("core", {}).setdefault("volunteers", {})
    metrics_created = summary.rows_created if potential_inserts is None else potential_inserts
    core_metrics.update(
        {
            "rows_processed": summary.rows_processed,
            "rows_created": metrics_created,
            "rows_updated": summary.rows_updated,
            "rows_reactivated": summary.rows_reactivated,
            "rows_changed": summary.rows_changed,
            "rows_skipped_duplicates": summary.rows_skipped_duplicates,
            "rows_skipped_no_change": summary.rows_skipped_no_change,
            "rows_missing_external_id": summary.rows_missing_external_id,
            "rows_soft_deleted": summary.rows_soft_deleted,
            "dry_run": summary.dry_run,
        }
    )
    import_run.metrics_json = metrics


def _coerce_string(value: object | None) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def _create_volunteer_from_candidate(candidate: CleanVolunteerPayload) -> Volunteer:
    volunteer = Volunteer(
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        preferred_name=_coerce_string(candidate.normalized_payload.get("preferred_name")),
        middle_name=_coerce_string(candidate.normalized_payload.get("middle_name")),
        source=candidate.external_system,
    )
    db.session.add(volunteer)
    db.session.flush()

    if candidate.email:
        email = ContactEmail(
            contact_id=volunteer.id,
            email=candidate.email,
            email_type=EmailType.PERSONAL,
            is_primary=True,
            is_verified=False,
        )
        volunteer.emails.append(email)
        db.session.add(email)
    if candidate.phone_e164:
        phone = ContactPhone(
            contact_id=volunteer.id,
            phone_number=candidate.phone_e164,
            phone_type=PhoneType.MOBILE,
            is_primary=True,
            can_text=True,
        )
        volunteer.phones.append(phone)
        db.session.add(phone)
    return volunteer


def _apply_updates(
    volunteer: Volunteer,
    candidate: CleanVolunteerPayload,
) -> dict[str, tuple[object | None, object | None]]:
    changes: dict[str, tuple[object | None, object | None]] = {}

    def _update_attr(attr: str, new_value: object | None) -> None:
        current = getattr(volunteer, attr)
        if current != new_value:
            setattr(volunteer, attr, new_value)
            changes[attr] = (current, new_value)

    _update_attr("first_name", candidate.first_name)
    _update_attr("last_name", candidate.last_name)
    _update_attr("preferred_name", _coerce_string(candidate.normalized_payload.get("preferred_name")))
    _update_attr("middle_name", _coerce_string(candidate.normalized_payload.get("middle_name")))
    _update_attr("source", candidate.external_system)

    primary_email = _get_primary_email(volunteer)
    normalized_candidate_email = candidate.email.lower() if candidate.email else None
    if candidate.email:
        if primary_email is None:
            new_email = ContactEmail(
                contact_id=volunteer.id,
                email=candidate.email,
                email_type=EmailType.PERSONAL,
                is_primary=True,
                is_verified=False,
            )
            volunteer.emails.append(new_email)
            db.session.add(new_email)
            for email in volunteer.emails:
                if email is not new_email:
                    email.is_primary = False
            changes["email"] = (None, candidate.email)
        elif primary_email.email.lower() != normalized_candidate_email:
            before = primary_email.email
            primary_email.email = candidate.email
            primary_email.is_verified = False
            changes["email"] = (before, candidate.email)
    elif primary_email is not None and primary_email.email:
        # No new email provided; leave existing primary in place.
        pass

    primary_phone = _get_primary_phone(volunteer)
    if candidate.phone_e164:
        if primary_phone is None:
            new_phone = ContactPhone(
                contact_id=volunteer.id,
                phone_number=candidate.phone_e164,
                phone_type=PhoneType.MOBILE,
                is_primary=True,
                can_text=True,
            )
            volunteer.phones.append(new_phone)
            db.session.add(new_phone)
            for phone in volunteer.phones:
                if phone is not new_phone:
                    phone.is_primary = False
            changes["phone_e164"] = (None, candidate.phone_e164)
        elif primary_phone.phone_number != candidate.phone_e164:
            before = primary_phone.phone_number
            primary_phone.phone_number = candidate.phone_e164
            primary_phone.can_text = True
            changes["phone_e164"] = (before, candidate.phone_e164)
    elif primary_phone is not None and primary_phone.phone_number:
        # Keep existing phone when no new number supplied.
        pass

    return changes


def _get_primary_email(volunteer: Volunteer) -> ContactEmail | None:
    for email in volunteer.emails:
        if email.is_primary:
            return email
    return volunteer.emails[0] if volunteer.emails else None


def _get_primary_phone(volunteer: Volunteer) -> ContactPhone | None:
    for phone in volunteer.phones:
        if phone.is_primary:
            return phone
    return volunteer.phones[0] if volunteer.phones else None


def _persist_change_log(
    *,
    import_run_id: int,
    volunteer_id: int,
    changes: dict[str, tuple[object | None, object | None]],
    idempotency_action: str,
    external_system: str,
    external_id: str | None,
) -> None:
    metadata = {
        "idempotency_action": idempotency_action,
        "external_system": external_system,
    }
    if external_id:
        metadata["external_id"] = external_id

    for field_name, (before, after) in changes.items():
        entry = ChangeLogEntry(
            run_id=import_run_id,
            entity_type="volunteer",
            entity_id=volunteer_id,
            field_name=field_name,
            old_value=_serialize_change_value(before),
            new_value=_serialize_change_value(after),
            metadata_json=metadata,
        )
        db.session.add(entry)


def _serialize_change_value(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)
