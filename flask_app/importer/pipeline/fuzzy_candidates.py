from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from config.monitoring import ImporterMonitoring
from flask_app.importer.pipeline.deterministic import match_volunteer_by_contact, normalize_email, normalize_phone
from flask_app.importer.pipeline.fuzzy_features import (
    ADDRESS_WEIGHT,
    ALT_CONTACT_WEIGHT,
    DOB_WEIGHT,
    EMPLOYER_WEIGHT,
    NAME_WEIGHT,
    SCHOOL_WEIGHT,
    compute_address_similarity,
    compute_alternate_contact_match,
    compute_dob_proximity,
    compute_employer_similarity,
    compute_name_similarity,
    compute_school_similarity,
    summarize_features,
    weighted_score,
)
from flask_app.models import ContactAddress, Volunteer, db
from flask_app.models.importer import CleanVolunteer, DedupeDecision, DedupeSuggestion


def get_auto_merge_threshold():
    """Get auto-merge threshold from Flask config, defaulting to 0.95."""
    from flask import current_app

    return current_app.config.get("FUZZY_AUTO_MERGE_THRESHOLD", 0.95)


AUTO_MERGE_THRESHOLD = 0.95  # Default, will be overridden by config
REVIEW_THRESHOLD = 0.80
BATCH_FLUSH_SIZE = 100


@dataclass
class FuzzyCandidateSummary:
    rows_considered: int = 0
    suggestions_created: int = 0
    high_confidence: int = 0
    review_band: int = 0
    low_score: int = 0
    skipped_no_signals: int = 0
    skipped_no_candidates: int = 0
    skipped_deterministic: int = 0
    auto_merged_count: int = 0
    dry_run: bool = False


def generate_fuzzy_candidates(import_run, *, dry_run: bool = False) -> FuzzyCandidateSummary:
    """
    Generate fuzzy dedupe candidate suggestions for a given import run.

    Args:
        import_run: The current ImportRun ORM instance.
        dry_run: When True, compute scores but do not persist suggestions.

    Returns:
        FuzzyCandidateSummary capturing work performed.
    """

    session = db.session
    summary = FuzzyCandidateSummary(dry_run=dry_run)

    clean_rows: List[CleanVolunteer] = (
        session.query(CleanVolunteer)
        .filter(CleanVolunteer.run_id == import_run.id)
        .options(joinedload(CleanVolunteer.staging_row))
        .all()
    )

    pending_suggestions: List[DedupeSuggestion] = []

    for clean_row in clean_rows:
        summary.rows_considered += 1
        payload = dict(clean_row.payload_json or {})

        norm_email = normalize_email(clean_row.email)
        norm_phone = normalize_phone(clean_row.phone_e164)
        postal_code = _extract_value(payload, ["postal_code", "zip", "zip_code"])

        if not any([norm_email, norm_phone, postal_code]):
            summary.skipped_no_signals += 1
            continue

        deterministic_result = match_volunteer_by_contact(
            session,
            email=clean_row.email,
            phone=clean_row.phone_e164,
        )

        if deterministic_result.is_match:
            summary.skipped_deterministic += 1
            continue

        candidate_ids = set(deterministic_result.email_match_ids + deterministic_result.phone_match_ids)
        candidate_ids.update(
            _find_candidates_by_name_zip(
                session,
                clean_row.first_name,
                clean_row.last_name,
                postal_code,
            )
        )

        if not candidate_ids:
            summary.skipped_no_candidates += 1
            continue

        volunteers = _load_volunteers(session, candidate_ids)
        if not volunteers:
            summary.skipped_no_candidates += 1
            continue

        candidate_emails = _collect_candidate_emails(clean_row.email, payload)
        candidate_phones = _collect_candidate_phones(clean_row.phone_e164, payload)
        candidate_street = _extract_value(payload, ["street", "street_address", "address", "address_line1"])
        candidate_city = _extract_value(payload, ["city", "locality"])
        candidate_employer = _extract_value(payload, ["employer", "company", "organization"])
        candidate_school = _extract_value(payload, ["school_affiliation", "school", "school_name"])
        candidate_dob = _extract_value(payload, ["dob", "date_of_birth", "birthdate"])

        for volunteer in volunteers:
            features = _build_feature_map(
                clean_row,
                candidate_dob,
                candidate_street,
                candidate_city,
                postal_code,
                candidate_employer,
                candidate_school,
                candidate_emails,
                candidate_phones,
                volunteer,
            )

            score = weighted_score(features)
            match_type = _categorize_score(score)

            if match_type == "fuzzy_low":
                summary.low_score += 1
                continue

            summary.suggestions_created += 1
            if match_type == "fuzzy_high":
                summary.high_confidence += 1
            elif match_type == "fuzzy_review":
                summary.review_band += 1

            if dry_run:
                continue

            if _suggestion_exists(session, import_run.id, clean_row.staging_volunteer_id, volunteer.id):
                continue

            ImporterMonitoring.record_fuzzy_candidate(match_type=match_type)

            suggestion = DedupeSuggestion(
                run_id=import_run.id,
                staging_volunteer_id=clean_row.staging_volunteer_id,
                primary_contact_id=volunteer.id,
                candidate_contact_id=None,
                score=_to_decimal(score),
                confidence_score=_to_decimal(score),
                match_type=match_type,
                decision=DedupeDecision.PENDING,
                features_json=_build_features_payload(features, score),
            )
            pending_suggestions.append(suggestion)

            if len(pending_suggestions) >= BATCH_FLUSH_SIZE:
                session.add_all(pending_suggestions)
                session.flush()
                pending_suggestions.clear()

    if not dry_run and pending_suggestions:
        session.add_all(pending_suggestions)
        session.flush()

    return summary


def _extract_value(payload: Dict[str, object], keys: Sequence[str]) -> Optional[str]:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
        else:
            return str(value).strip()
    return None


def _collect_candidate_emails(primary_email: Optional[str], payload: Dict[str, object]) -> List[str]:
    emails: List[str] = []
    if primary_email:
        emails.append(primary_email)
    emails.extend(_to_list(payload.get("alternate_emails")))
    emails.extend(_to_list(payload.get("alt_emails")))
    return emails


def _collect_candidate_phones(primary_phone: Optional[str], payload: Dict[str, object]) -> List[str]:
    phones: List[str] = []
    if primary_phone:
        phones.append(primary_phone)
    phones.extend(_to_list(payload.get("alternate_phones")))
    phones.extend(_to_list(payload.get("alt_phones")))
    return phones


def _to_list(value: object | None) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items: List[str] = []
        for entry in value:
            items.extend(_to_list(entry))
        return items
    if isinstance(value, dict):
        items: List[str] = []
        for entry in value.values():
            items.extend(_to_list(entry))
        return items
    text = str(value).strip()
    if not text:
        return []
    if "," in text or ";" in text:
        separators = [token.strip() for token in text.replace(";", ",").split(",")]
        return [token for token in separators if token]
    return [text]


def _find_candidates_by_name_zip(session, first_name: str, last_name: str, postal_code: Optional[str]) -> Sequence[int]:
    if not first_name or not last_name or not postal_code:
        return ()

    first_norm = first_name.strip().lower()
    last_norm = last_name.strip().lower()
    zip_norm = postal_code.strip().lower()

    query = (
        session.query(Volunteer.id)
        .join(ContactAddress, Volunteer.addresses)
        .filter(
            func.lower(Volunteer.last_name) == last_norm,
            ContactAddress.is_primary.is_(True),
            func.lower(ContactAddress.postal_code) == zip_norm,
        )
    )
    if first_norm:
        query = query.filter(func.substr(func.lower(Volunteer.first_name), 1, 1) == first_norm[0])
    return [row[0] for row in query.all()]


def _load_volunteers(session, ids: Iterable[int]) -> List[Volunteer]:
    id_list = list(set(ids))
    if not id_list:
        return []
    return (
        session.query(Volunteer)
        .options(
            joinedload(Volunteer.emails),
            joinedload(Volunteer.phones),
            joinedload(Volunteer.addresses),
            joinedload(Volunteer.organization),
        )
        .filter(Volunteer.id.in_(id_list))
        .all()
    )


def _build_feature_map(
    clean_row: CleanVolunteer,
    candidate_dob: Optional[str],
    candidate_street: Optional[str],
    candidate_city: Optional[str],
    candidate_zip: Optional[str],
    candidate_employer: Optional[str],
    candidate_school: Optional[str],
    candidate_emails: Sequence[str],
    candidate_phones: Sequence[str],
    volunteer: Volunteer,
) -> Dict[str, float]:
    volunteer_dob = volunteer.birthdate.isoformat() if getattr(volunteer, "birthdate", None) else None
    primary_address = _get_primary_address(volunteer)
    core_street = primary_address.street_address_1 if primary_address else None
    core_city = primary_address.city if primary_address else None
    core_zip = primary_address.postal_code if primary_address else None
    core_employer = volunteer.organization.name if getattr(volunteer, "organization", None) else None

    core_school = getattr(volunteer, "school_affiliation", None)

    core_emails = [email.email for email in getattr(volunteer, "emails", [])]
    core_phones = [phone.phone_number for phone in getattr(volunteer, "phones", [])]

    features = {
        "name": compute_name_similarity(
            clean_row.first_name,
            clean_row.last_name,
            volunteer.first_name,
            volunteer.last_name,
        ),
        "dob": compute_dob_proximity(candidate_dob, volunteer_dob),
        "address": compute_address_similarity(
            candidate_street,
            candidate_city,
            candidate_zip,
            core_street,
            core_city,
            core_zip,
        ),
        "employer": compute_employer_similarity(candidate_employer, core_employer),
        "school": compute_school_similarity(candidate_school, core_school),
        "alternate_contact": compute_alternate_contact_match(
            candidate_emails,
            candidate_phones,
            core_emails,
            core_phones,
        ),
    }

    return features


def _get_primary_address(volunteer: Volunteer) -> Optional[ContactAddress]:
    addresses = getattr(volunteer, "addresses", [])
    for address in addresses:
        if address.is_primary:
            return address
    return addresses[0] if addresses else None


def _categorize_score(score: float) -> str:
    """Categorize fuzzy match score into match type."""
    threshold = get_auto_merge_threshold()
    if score >= threshold:
        return "fuzzy_high"
    if score >= REVIEW_THRESHOLD:
        return "fuzzy_review"
    return "fuzzy_low"


def _to_decimal(score: float) -> Decimal:
    return Decimal(f"{score:.4f}")


def _build_features_payload(features: Dict[str, float], score: float) -> Dict[str, object]:
    rounded_features = summarize_features(features)
    return {
        "score": round(score, 4),
        "thresholds": {
            "auto_merge": AUTO_MERGE_THRESHOLD,
            "review": REVIEW_THRESHOLD,
        },
        "weights": {
            "name": NAME_WEIGHT,
            "dob": DOB_WEIGHT,
            "address": ADDRESS_WEIGHT,
            "employer": EMPLOYER_WEIGHT,
            "school": SCHOOL_WEIGHT,
            "alternate_contact": ALT_CONTACT_WEIGHT,
        },
        "features": rounded_features,
    }


def _suggestion_exists(session, run_id: int, staging_id: Optional[int], primary_contact_id: int) -> bool:
    query = session.query(DedupeSuggestion.id).filter(
        DedupeSuggestion.run_id == run_id,
        DedupeSuggestion.primary_contact_id == primary_contact_id,
    )
    if staging_id is not None:
        query = query.filter(DedupeSuggestion.staging_volunteer_id == staging_id)
    return session.query(query.exists()).scalar()


__all__ = ["generate_fuzzy_candidates", "FuzzyCandidateSummary"]
