"""
Create-only upsert helpers that load clean volunteers into the core schema.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from flask import current_app, has_app_context
from sqlalchemy import func

from config.monitoring import ImporterMonitoring
from config.survivorship import SurvivorshipProfile, load_profile
from flask_app.models import ContactAddress, ContactEmail, ContactPhone, EmailType, PhoneType, Volunteer, db
from flask_app.models.contact.enums import AddressType
from flask_app.models.importer.schema import (
    ChangeLogEntry,
    CleanVolunteer,
    DataQualityViolation,
    DedupeDecision,
    DedupeSuggestion,
    ExternalIdMap,
    StagingRecordStatus,
    StagingVolunteer,
)

from .clean import CleanVolunteerPayload
from .deterministic import match_volunteer_by_contact
from .idempotency import MissingExternalIdentifier, resolve_import_target
from .survivorship import SurvivorshipResult, apply_survivorship, summarize_decisions


@dataclass
class CoreLoadSummary:
    """Aggregate results from loading clean rows into the core schema."""

    rows_processed: int
    rows_created: int
    rows_updated: int
    rows_reactivated: int
    rows_deduped_auto: int
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


@lru_cache(maxsize=1)
def _get_active_survivorship_profile() -> SurvivorshipProfile:
    """
    Load and cache the survivorship profile for importer runs.
    """

    return load_profile(dict(os.environ))


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
            rows_deduped_auto=0,
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
    rows_deduped_auto = 0
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

        dedupe_result = None
        deterministic_volunteer = None
        current_action = target.action

        if target.action == "create":
            dedupe_result = match_volunteer_by_contact(
                session=session,
                email=candidate.email,
                phone=candidate.phone_e164,
            )
            if dedupe_result.is_match:
                deterministic_volunteer = session.get(Volunteer, dedupe_result.volunteer_id)
                if deterministic_volunteer is not None:
                    current_action = "deterministic_update"
            elif dedupe_result and dedupe_result.outcome == "ambiguous" and staging_row is not None:
                _record_ambiguous_dedupe(
                    run_id=import_run.id,
                    staging_row=staging_row,
                    match_result=dedupe_result,
                )

        if current_action == "deterministic_update" and deterministic_volunteer is None:
            current_action = "create"

        if current_action == "create":
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
        elif current_action in {"update", "reactivate"}:
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

            profile = _get_active_survivorship_profile()
            changes, survivorship = _apply_survivorship_updates(
                volunteer,
                candidate,
                import_run=import_run,
                staging_row=staging_row,
                profile=profile,
            )

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
                    survivorship=survivorship,
                )
                _record_survivorship_metrics(import_run, survivorship)

            clean_row.core_contact_id = volunteer.id
            clean_row.core_volunteer_id = volunteer.id
            if staging_row is not None:
                _mark_staging_loaded(staging_row, duplicate=False)
        elif current_action == "deterministic_update":
            volunteer = deterministic_volunteer
            if volunteer is None:
                continue

            profile = _get_active_survivorship_profile()
            changes, survivorship = _apply_survivorship_updates(
                volunteer,
                candidate,
                import_run=import_run,
                staging_row=staging_row,
                profile=profile,
            )
            rows_deduped_auto += 1

            if not changes:
                rows_skipped_no_change += 1
                clean_row.load_action = "deterministic_no_change"
            else:
                rows_updated += 1
                clean_row.load_action = "deterministic_update"
                _persist_change_log(
                    import_run_id=import_run.id,
                    volunteer_id=volunteer.id,
                    changes=changes,
                    idempotency_action="deterministic_update",
                    external_system=candidate.external_system,
                    external_id=candidate.external_id,
                    survivorship=survivorship,
                )
                _record_survivorship_metrics(import_run, survivorship)

            clean_row.core_contact_id = volunteer.id
            clean_row.core_volunteer_id = volunteer.id
            if staging_row is not None:
                _mark_staging_loaded(staging_row, duplicate=False)
                if dedupe_result and dedupe_result.is_match:
                    _record_auto_resolved_dedupe(
                        run_id=import_run.id,
                        staging_row=staging_row,
                        volunteer=volunteer,
                        match_result=dedupe_result,
                    )

        processed_mutations = rows_created + rows_updated
        if processed_mutations and processed_mutations % batch_size == 0:
            session.flush()

    summary = CoreLoadSummary(
        rows_processed=rows_processed,
        rows_created=rows_created,
        rows_updated=rows_updated,
        rows_reactivated=rows_reactivated,
        rows_deduped_auto=rows_deduped_auto,
        rows_skipped_duplicates=rows_skipped_duplicates,
        rows_skipped_no_change=rows_skipped_no_change,
        rows_missing_external_id=rows_missing_external_id,
        rows_soft_deleted=rows_soft_deleted,
        duplicate_emails=tuple(duplicate_emails),
        dry_run=False,
    )
    _update_core_counts(import_run, summary)
    metrics_enabled = True
    metrics_source = getattr(import_run, "source", None)
    metrics_environment = None
    if has_app_context():
        config = current_app.config
        metrics_enabled = config.get("IMPORTER_METRICS_SANDBOX_ENABLED", True)
        metrics_environment = config.get("IMPORTER_METRICS_ENV")
    if metrics_environment and metrics_source:
        metrics_source = f"{metrics_environment}:{metrics_source}"
    elif metrics_environment:
        metrics_source = metrics_environment
    if metrics_enabled and not summary.dry_run:
        ImporterMonitoring.record_idempotent_outcomes(
            source=metrics_source,
            created=summary.rows_created,
            updated=summary.rows_updated,
            skipped=summary.rows_skipped_no_change,
        )
    if has_app_context():
        current_app.logger.info(
            (
                "Importer run %s loaded %s volunteers "
                "(created=%s updated=%s reactivated=%s duplicates=%s "
                "no_change=%s missing_external_id=%s dedupe_auto=%s)"
            ),
            import_run.id,
            summary.rows_created + summary.rows_updated,
            summary.rows_created,
            summary.rows_updated,
            summary.rows_reactivated,
            summary.rows_skipped_duplicates,
            summary.rows_skipped_no_change,
            summary.rows_missing_external_id,
            summary.rows_deduped_auto,
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
    deduped_count = summary.rows_deduped_auto if not summary.dry_run else 0
    core_counts.update(
        {
            "rows_processed": summary.rows_processed,
            "rows_created": created_count,
            "rows_updated": updated_count,
            "rows_reactivated": reactivated_count,
            "rows_deduped_auto": deduped_count,
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
            "rows_deduped_auto": summary.rows_deduped_auto,
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
    payload = candidate.normalized_payload

    # Extract and parse birthdate
    birthdate = None
    dob_str = payload.get("dob") or payload.get("date_of_birth") or payload.get("birthdate")
    if dob_str:
        try:
            from datetime import datetime

            if isinstance(dob_str, str):
                # Try ISO format first (YYYY-MM-DD)
                if len(dob_str) >= 10:
                    birthdate = datetime.strptime(dob_str[:10], "%Y-%m-%d").date()
                else:
                    # Try other common formats
                    for fmt in ["%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"]:
                        try:
                            birthdate = datetime.strptime(dob_str, fmt).date()
                            break
                        except ValueError:
                            continue
        except (ValueError, TypeError, AttributeError):
            pass

    volunteer = Volunteer(
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        preferred_name=_coerce_string(payload.get("preferred_name")),
        middle_name=_coerce_string(payload.get("middle_name")),
        birthdate=birthdate,
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

    # Create address if address fields are present
    # (payload already extracted above)
    street = _coerce_string(
        payload.get("street") or payload.get("street_address") or payload.get("address") or payload.get("address_line1")
    )
    city = _coerce_string(payload.get("city") or payload.get("locality"))
    state = _coerce_string(payload.get("state") or payload.get("state_code"))
    postal_code = _coerce_string(payload.get("postal_code") or payload.get("zip") or payload.get("zip_code"))
    country = _coerce_string(payload.get("country") or payload.get("country_code")) or "US"

    if street and city and state and postal_code:
        address = ContactAddress(
            contact_id=volunteer.id,
            address_type=AddressType.HOME,
            street_address_1=street,
            street_address_2=_coerce_string(payload.get("street_address_2") or payload.get("address_line2")),
            city=city,
            state=state,
            postal_code=postal_code,
            country=country,
            is_primary=True,
        )
        volunteer.addresses.append(address)
        db.session.add(address)

    return volunteer


def _apply_survivorship_updates(
    volunteer: Volunteer,
    candidate: CleanVolunteerPayload,
    *,
    import_run,
    staging_row: StagingVolunteer | None,
    profile: SurvivorshipProfile,
) -> tuple[dict[str, tuple[object | None, object | None]], SurvivorshipResult]:
    field_names = _profile_field_names(profile)
    core_snapshot = _build_core_snapshot(volunteer, field_names)
    incoming_payload = _build_incoming_payload(candidate, field_names)
    manual_overrides = _resolve_manual_overrides(import_run, staging_row, field_names)
    verified_snapshot = _build_verified_snapshot(volunteer, field_names)
    incoming_provenance = _build_incoming_provenance(import_run, candidate, staging_row)

    survivorship = apply_survivorship(
        profile=profile,
        incoming_payload=incoming_payload,
        core_snapshot=core_snapshot,
        manual_overrides=manual_overrides,
        verified_snapshot=verified_snapshot,
        incoming_provenance=incoming_provenance,
    )

    changes: dict[str, tuple[object | None, object | None]] = {}

    for field_name, final_value in survivorship.resolved_values.items():
        if field_name == "email":
            before, after, changed = _apply_email_change(volunteer, final_value)
            if changed:
                changes[field_name] = (before, after)
        elif field_name == "phone_e164":
            before, after, changed = _apply_phone_change(volunteer, final_value)
            if changed:
                changes[field_name] = (before, after)
        elif hasattr(volunteer, field_name):
            before = getattr(volunteer, field_name)
            if before != final_value:
                setattr(volunteer, field_name, final_value)
                changes[field_name] = (before, final_value)

    if volunteer.source != candidate.external_system:
        previous_source = volunteer.source
        volunteer.source = candidate.external_system
        if previous_source != candidate.external_system:
            changes.setdefault("source", (previous_source, candidate.external_system))

    return changes, survivorship


def _profile_field_names(profile: SurvivorshipProfile) -> set[str]:
    names = {rule.field_name for group in profile.field_groups for rule in group.fields}
    # Ensure standard fields are included.
    names.update(
        {
            "email",
            "phone_e164",
            "first_name",
            "last_name",
            "middle_name",
            "preferred_name",
            "notes",
            "internal_notes",
        }
    )
    return names


def _build_core_snapshot(volunteer: Volunteer, field_names: set[str]) -> Mapping[str, Any]:
    snapshot: dict[str, Any] = {}
    for field_name in field_names:
        if field_name == "email":
            email = _get_primary_email(volunteer)
            snapshot[field_name] = email.email if email else None
        elif field_name == "phone_e164":
            phone = _get_primary_phone(volunteer)
            snapshot[field_name] = phone.phone_number if phone else None
        elif hasattr(volunteer, field_name):
            snapshot[field_name] = getattr(volunteer, field_name)
    return snapshot


def _build_incoming_payload(candidate: CleanVolunteerPayload, field_names: set[str]) -> Mapping[str, Any]:
    payload: dict[str, Any] = {}
    normalized_payload = candidate.normalized_payload or {}
    for field_name in field_names:
        if field_name == "first_name":
            payload[field_name] = candidate.first_name
        elif field_name == "last_name":
            payload[field_name] = candidate.last_name
        elif field_name == "middle_name":
            payload[field_name] = _coerce_string(normalized_payload.get("middle_name"))
        elif field_name == "preferred_name":
            payload[field_name] = _coerce_string(normalized_payload.get("preferred_name"))
        elif field_name == "email":
            payload[field_name] = candidate.email
        elif field_name == "phone_e164":
            payload[field_name] = candidate.phone_e164
        else:
            payload[field_name] = normalized_payload.get(field_name)
    return payload


def _resolve_manual_overrides(
    import_run,
    staging_row: StagingVolunteer | None,
    field_names: set[str],
) -> Mapping[str, Mapping[str, Any]]:
    overrides: dict[str, Mapping[str, Any]] = {}
    violation_candidates: list[Any] = []
    if staging_row is not None:
        violation_candidates.extend(getattr(staging_row, "dq_violations", []) or [])

    if not violation_candidates and import_run is not None:
        ingest_params = getattr(import_run, "ingest_params_json", {}) or {}
        remediation = ingest_params.get("remediation", {}) if isinstance(ingest_params, Mapping) else {}
        violation_id = remediation.get("violation_id") if isinstance(remediation, Mapping) else None
        if violation_id is not None:
            violation = db.session.get(DataQualityViolation, violation_id)
            if violation is not None:
                violation_candidates.append(violation)

    for violation in violation_candidates:
        diff = violation.edited_fields_json or {}
        if isinstance(diff, Mapping) and diff:
            source_fields = diff.items()
        else:
            payload = violation.edited_payload_json or {}
            source_fields = payload.items() if isinstance(payload, Mapping) else ()

        for field_name, details in source_fields:
            if field_name not in field_names:
                continue
            if isinstance(details, Mapping):
                after_value = details.get("after")
                before_value = details.get("before")
            else:
                after_value = details
                before_value = None

            data = {
                "value": after_value,
                "before": before_value,
                "violation_id": violation.id,
                "remediation_notes": violation.remediation_notes,
                "user_id": violation.remediated_by_user_id,
                "verified_at": violation.remediated_at.isoformat() if violation.remediated_at else None,
                "source": "manual",
            }
            overrides[field_name] = data
    return overrides


def _build_verified_snapshot(volunteer: Volunteer, field_names: set[str]) -> Mapping[str, Mapping[str, Any]]:
    snapshot: dict[str, Mapping[str, Any]] = {}
    if "email" in field_names:
        email = _get_primary_email(volunteer)
        if email and getattr(email, "is_verified", False):
            snapshot["email"] = {
                "value": email.email,
                "verified": True,
            }
    return snapshot


def _build_incoming_provenance(
    import_run,
    candidate: CleanVolunteerPayload,
    staging_row: StagingVolunteer | None,
) -> Mapping[str, Any]:
    provenance = {
        "source_run_id": getattr(import_run, "id", None),
        "external_system": candidate.external_system,
        "ingest_version": candidate.normalized_payload.get("ingest_version"),
    }
    if staging_row is not None:
        provenance["staging_volunteer_id"] = staging_row.id
    return {key: value for key, value in provenance.items() if value is not None}


def _apply_email_change(
    volunteer: Volunteer,
    final_value: object | None,
) -> tuple[object | None, object | None, bool]:
    normalized_value = _coerce_string(final_value)
    primary = _get_primary_email(volunteer)

    before = primary.email if primary else None
    after = normalized_value

    if normalized_value is None:
        return before, after, False

    if primary is None:
        new_email = ContactEmail(
            contact_id=volunteer.id,
            email=normalized_value,
            email_type=EmailType.PERSONAL,
            is_primary=True,
            is_verified=False,
        )
        volunteer.emails.append(new_email)
        db.session.add(new_email)
        for email in volunteer.emails:
            if email is not new_email:
                email.is_primary = False
        return before, normalized_value, True

    if primary.email.lower() != normalized_value.lower():
        primary.email = normalized_value
        primary.is_verified = False
        return before, normalized_value, True

    return before, normalized_value, False


def _apply_phone_change(
    volunteer: Volunteer,
    final_value: object | None,
) -> tuple[object | None, object | None, bool]:
    normalized_value = _coerce_string(final_value)
    primary = _get_primary_phone(volunteer)

    before = primary.phone_number if primary else None
    after = normalized_value

    if normalized_value is None:
        return before, after, False

    if primary is None:
        new_phone = ContactPhone(
            contact_id=volunteer.id,
            phone_number=normalized_value,
            phone_type=PhoneType.MOBILE,
            is_primary=True,
            can_text=True,
        )
        volunteer.phones.append(new_phone)
        db.session.add(new_phone)
        for phone in volunteer.phones:
            if phone is not new_phone:
                phone.is_primary = False
        return before, normalized_value, True

    if primary.phone_number != normalized_value:
        primary.phone_number = normalized_value
        primary.can_text = True
        return before, normalized_value, True

    return before, normalized_value, False


def _record_survivorship_metrics(import_run, survivorship: SurvivorshipResult) -> None:
    stats = survivorship.stats or {}
    if not stats:
        return

    counts = dict(import_run.counts_json or {})
    core_counts = counts.setdefault("core", {}).setdefault("volunteers", {})
    survivorship_counts = core_counts.setdefault("survivorship", {"stats": {}, "groups": {}})

    stats_bucket = survivorship_counts.setdefault("stats", {})
    for key, value in stats.items():
        stats_bucket[key] = int(stats_bucket.get(key, 0) or 0) + int(value)

    group_summary = summarize_decisions(survivorship.decisions)
    groups_bucket = survivorship_counts.setdefault("groups", {})
    for group_name, data in group_summary.items():
        group_target = groups_bucket.setdefault(group_name, {})
        for metric, value in data.items():
            group_target[metric] = int(group_target.get(metric, 0) or 0) + int(value)

    core_counts["survivorship"] = survivorship_counts
    import_run.counts_json = counts

    metrics = dict(import_run.metrics_json or {})
    core_metrics = metrics.setdefault("core", {}).setdefault("volunteers", {})
    survivorship_metrics = core_metrics.setdefault("survivorship", {})
    for key, value in stats.items():
        survivorship_metrics[key] = int(survivorship_metrics.get(key, 0) or 0) + int(value)
    core_metrics["survivorship"] = survivorship_metrics
    import_run.metrics_json = metrics

    manual_overridden = [
        decision.field_name
        for decision in survivorship.decisions
        if any(candidate.tier == "manual" for candidate in decision.losers) and decision.winner.tier != "manual"
    ]
    if manual_overridden:
        ImporterMonitoring.record_survivorship_warnings(count=len(manual_overridden))
        if has_app_context():
            current_app.logger.warning(
                "Importer run %s survivorship overrides manual edits for fields: %s",
                getattr(import_run, "id", "unknown"),
                ", ".join(sorted(manual_overridden)),
            )

    ImporterMonitoring.record_survivorship_decisions(stats=stats)


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
    survivorship: SurvivorshipResult | None = None,
) -> None:
    decision_lookup = {decision.field_name: decision for decision in survivorship.decisions} if survivorship else {}

    for field_name, (before, after) in changes.items():
        metadata = {
            "idempotency_action": idempotency_action,
            "external_system": external_system,
        }
        if external_id:
            metadata["external_id"] = external_id

        decision = decision_lookup.get(field_name)
        if decision:
            metadata["survivorship"] = {
                "winner": {
                    "tier": decision.winner.tier,
                    "value": _serialize_change_value(decision.winner.value),
                    "metadata": decision.winner.metadata,
                },
                "losers": [
                    {
                        "tier": candidate.tier,
                        "value": _serialize_change_value(candidate.value),
                        "metadata": candidate.metadata,
                    }
                    for candidate in decision.losers
                ],
                "manual_override": decision.manual_override,
                "reason": decision.reason,
            }

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


def _record_auto_resolved_dedupe(
    *,
    run_id: int,
    staging_row: StagingVolunteer,
    volunteer: Volunteer,
    match_result,
) -> None:
    features = {
        "match_type": match_result.outcome,
        "email_matches": list(match_result.email_match_ids),
        "phone_matches": list(match_result.phone_match_ids),
        "normalized_email": match_result.normalized_email,
        "normalized_phone": match_result.normalized_phone,
    }
    ImporterMonitoring.record_deterministic_dedupe(match_type=match_result.outcome)
    suggestion = DedupeSuggestion(
        run_id=run_id,
        staging_volunteer_id=staging_row.id if staging_row else None,
        primary_contact_id=volunteer.id,
        candidate_contact_id=None,
        score=1.0,
        match_type=match_result.outcome,
        confidence_score=1.0,
        features_json=features,
        decision=DedupeDecision.AUTO_MERGED,
        decision_notes="Resolved deterministically by email/phone heuristic.",
        decided_at=datetime.now(timezone.utc),
    )
    db.session.add(suggestion)


def _record_ambiguous_dedupe(
    *,
    run_id: int,
    staging_row: StagingVolunteer,
    match_result,
) -> None:
    features = {
        "match_type": match_result.outcome,
        "email_matches": list(match_result.email_match_ids),
        "phone_matches": list(match_result.phone_match_ids),
        "normalized_email": match_result.normalized_email,
        "normalized_phone": match_result.normalized_phone,
    }
    suggestion = DedupeSuggestion(
        run_id=run_id,
        staging_volunteer_id=staging_row.id if staging_row else None,
        primary_contact_id=None,
        candidate_contact_id=None,
        score=None,
        match_type=match_result.outcome,
        features_json=features,
        decision_notes="Multiple deterministic candidates detected; requires manual review.",
    )
    db.session.add(suggestion)
