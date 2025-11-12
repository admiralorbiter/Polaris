from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence

from flask import current_app, has_app_context
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
    _clean_text,
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
from flask_app.models.importer import CleanVolunteer, DedupeDecision, DedupeSuggestion, ImportRun


def get_auto_merge_threshold():
    """Get auto-merge threshold from Flask config, defaulting to 0.95."""
    from flask import current_app

    return current_app.config.get("FUZZY_AUTO_MERGE_THRESHOLD", 0.95)


AUTO_MERGE_THRESHOLD = 0.95  # Default, will be overridden by config
REVIEW_THRESHOLD = 0.60  # Lowered to account for employer not being stored in Volunteer model
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

        # Skip fuzzy matching if there's a deterministic match (perfect email+phone match)
        # This means the record already exists and will be handled by deterministic matching
        # in the load_core step, so no fuzzy review is needed
        if deterministic_result.is_match and deterministic_result.volunteer_id:
            skip_fuzzy = False
            if clean_row.external_id:
                from flask_app.models.importer.schema import ExternalIdMap

                # Check if this volunteer has the same external_id FROM THE CURRENT RUN
                # (meaning we're processing the same row twice in the same run)
                id_map = (
                    session.query(ExternalIdMap)
                    .filter(
                        ExternalIdMap.entity_id == deterministic_result.volunteer_id,
                        ExternalIdMap.entity_type == "volunteer",
                        ExternalIdMap.external_system == clean_row.external_system,
                        ExternalIdMap.external_id == clean_row.external_id,
                        ExternalIdMap.run_id == import_run.id,  # Only skip if from CURRENT run
                    )
                    .first()
                )
                if id_map:
                    # Duplicate row in same run - definitely skip
                    skip_fuzzy = True
                else:
                    # Deterministic match exists but not from current run
                    # This means it's a perfect match that will be handled deterministically
                    # in load_core, so skip fuzzy matching
                    skip_fuzzy = True
            else:
                # No external_id, but we have a deterministic match - skip fuzzy matching
                # because it's already a perfect match that will be handled deterministically
                skip_fuzzy = True

            if skip_fuzzy:
                summary.skipped_deterministic += 1
                continue

        # Use deterministic matches as starting point for fuzzy matching
        # This helps when we have partial matches (e.g., email matches but phone doesn't)
        candidate_ids = set(deterministic_result.email_match_ids + deterministic_result.phone_match_ids)

        # Try to find candidates by name+zip if we have postal code
        if postal_code:
            name_zip_matches = _find_candidates_by_name_zip(
                session,
                clean_row.first_name,
                clean_row.last_name,
                postal_code,
            )
            candidate_ids.update(name_zip_matches)

        # Fallback: if no matches found and we have last name, try broader search
        # This helps when addresses aren't created yet or zip codes don't match exactly
        if not candidate_ids and clean_row.last_name:
            # Find volunteers with matching last name and same first letter of first name
            last_norm = clean_row.last_name.strip().lower()
            first_norm = clean_row.first_name.strip().lower() if clean_row.first_name else ""
            query = session.query(Volunteer.id).filter(
                func.lower(Volunteer.last_name) == last_norm,
            )
            if first_norm:
                query = query.filter(func.substr(func.lower(Volunteer.first_name), 1, 1) == first_norm[0])
            # Limit to reasonable number to avoid matching too many
            broader_matches = [row[0] for row in query.limit(10).all()]
            candidate_ids.update(broader_matches)

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


def _update_dedupe_counts(import_run: ImportRun, fuzzy_summary: FuzzyCandidateSummary) -> None:
    """
    Update dedupe counts in import_run.counts_json and metrics_json.

    This function queries the DedupeSuggestion table to get accurate counts
    after all dedupe operations (including auto-merge) have completed.
    """
    from sqlalchemy import func

    # Query actual counts from database
    rows_auto_merged = (
        db.session.query(func.count(DedupeSuggestion.id))
        .filter(
            DedupeSuggestion.run_id == import_run.id,
            DedupeSuggestion.decision == DedupeDecision.AUTO_MERGED,
        )
        .scalar()
        or 0
    )
    rows_manual_review = (
        db.session.query(func.count(DedupeSuggestion.id))
        .filter(
            DedupeSuggestion.run_id == import_run.id,
            DedupeSuggestion.decision == DedupeDecision.PENDING,
        )
        .scalar()
        or 0
    )
    rows_total_suggestions = (
        db.session.query(func.count(DedupeSuggestion.id)).filter(DedupeSuggestion.run_id == import_run.id).scalar() or 0
    )

    # Update Prometheus metrics
    if not fuzzy_summary.dry_run:
        if ImporterMonitoring.DEDUPE_AUTO_PER_RUN_TOTAL:
            ImporterMonitoring.DEDUPE_AUTO_PER_RUN_TOTAL.labels(
                run_id=str(import_run.id), source=import_run.source or "unknown"
            ).inc(rows_auto_merged)
        if ImporterMonitoring.DEDUPE_MANUAL_REVIEW_PER_RUN_TOTAL:
            ImporterMonitoring.DEDUPE_MANUAL_REVIEW_PER_RUN_TOTAL.labels(
                run_id=str(import_run.id), source=import_run.source or "unknown"
            ).inc(rows_manual_review)

    # Update counts_json
    counts = dict(import_run.counts_json or {})
    dedupe_counts = counts.setdefault("dedupe", {}).setdefault("volunteers", {})
    dedupe_counts.update(
        {
            "rows_auto_merged": rows_auto_merged if not fuzzy_summary.dry_run else 0,
            "rows_manual_review": rows_manual_review if not fuzzy_summary.dry_run else 0,
            "rows_total_suggestions": rows_total_suggestions if not fuzzy_summary.dry_run else 0,
            "dry_run": fuzzy_summary.dry_run,
        }
    )
    import_run.counts_json = counts

    # Update metrics_json
    metrics = dict(import_run.metrics_json or {})
    dedupe_metrics = metrics.setdefault("dedupe", {}).setdefault("volunteers", {})
    dedupe_metrics.update(
        {
            "rows_auto_merged": rows_auto_merged,
            "rows_manual_review": rows_manual_review,
            "rows_total_suggestions": rows_total_suggestions,
            "rows_considered": fuzzy_summary.rows_considered,
            "suggestions_created": fuzzy_summary.suggestions_created,
            "high_confidence": fuzzy_summary.high_confidence,
            "review_band": fuzzy_summary.review_band,
            "low_score": fuzzy_summary.low_score,
            "skipped_no_signals": fuzzy_summary.skipped_no_signals,
            "skipped_no_candidates": fuzzy_summary.skipped_no_candidates,
            "skipped_deterministic": fuzzy_summary.skipped_deterministic,
            "dry_run": fuzzy_summary.dry_run,
        }
    )
    import_run.metrics_json = metrics


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
        .join(ContactAddress)
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


def scan_existing_volunteers_for_duplicates(
    *,
    dry_run: bool = False,
    batch_size: int = 100,
    similarity_threshold: float = 0.80,
) -> FuzzyCandidateSummary:
    """
    Scan all existing volunteers in the database to find potential duplicates.
    This is useful for finding duplicates in data that was already imported.
    
    Args:
        dry_run: When True, compute scores but do not persist suggestions.
        batch_size: Number of volunteers to process in each batch.
        similarity_threshold: Minimum similarity score to consider (default 0.80 for review band).
    
    Returns:
        FuzzyCandidateSummary capturing work performed.
    """
    from flask_app.models.importer.schema import DedupeSuggestion, DedupeDecision
    from flask_app.importer.pipeline.deterministic import match_volunteer_by_contact, normalize_email, normalize_phone
    from sqlalchemy import func
    
    session = db.session
    summary = FuzzyCandidateSummary(dry_run=dry_run)
    
    # Optimized approach: Use database queries with blocking instead of O(n²) in-memory comparison
    # Get count first for progress tracking
    total_volunteers = session.query(func.count(Volunteer.id)).scalar()
    if total_volunteers == 0:
        return summary
    
    # Get all volunteer IDs with names (for blocking strategy)
    volunteer_ids_with_names = (
        session.query(Volunteer.id, Volunteer.first_name, Volunteer.last_name)
        .filter(
            Volunteer.first_name.isnot(None),
            Volunteer.last_name.isnot(None),
        )
        .order_by(Volunteer.id)
        .all()
    )
    
    if not volunteer_ids_with_names:
        return summary
    
    pending_suggestions: List[DedupeSuggestion] = []
    
    # Process volunteers using blocking strategy (much more efficient than O(n²))
    for i, (volunteer1_id, first1, last1) in enumerate(volunteer_ids_with_names):
        if i % 100 == 0 and has_app_context():
            current_app.logger.info(f"Scanning volunteer {i+1}/{len(volunteer_ids_with_names)} for duplicates...")
        
        summary.rows_considered += 1
        
        # Normalize volunteer1 name for comparison
        first1_norm = _clean_text(first1).lower().strip() if first1 else ""
        last1_norm = _clean_text(last1).lower().strip() if last1 else ""
        
        if not first1_norm or not last1_norm:
            continue
        
        # Use database query to find potential matches (blocking strategy)
        # Find volunteers with same last name and first initial (efficient blocking)
        first_initial = first1_norm[0] if first1_norm else None
        if not first_initial:
            continue
        
        # Query for potential matches using blocking (same last name + first initial)
        potential_matches = (
            session.query(Volunteer)
            .options(
                joinedload(Volunteer.emails),
                joinedload(Volunteer.phones),
                joinedload(Volunteer.addresses),
            )
            .filter(
                Volunteer.id > volunteer1_id,  # Only compare with volunteers we haven't checked yet
                func.lower(Volunteer.last_name) == last1_norm,
                func.lower(func.substr(Volunteer.first_name, 1, 1)) == first_initial,
                Volunteer.first_name.isnot(None),
                Volunteer.last_name.isnot(None),
            )
            .all()
        )
        
        # Load volunteer1 with relationships for comparison
        volunteer1 = (
            session.query(Volunteer)
            .options(
                joinedload(Volunteer.emails),
                joinedload(Volunteer.phones),
                joinedload(Volunteer.addresses),
            )
            .filter(Volunteer.id == volunteer1_id)
            .first()
        )
        
        if not volunteer1:
            continue
        
        # Compare against potential matches
        for volunteer2 in potential_matches:
            if not volunteer2.first_name or not volunteer2.last_name:
                continue
            
            # Skip if same volunteer
            if volunteer1.id == volunteer2.id:
                continue
            
            # Check for exact name match first (case-insensitive, normalized)
            # We already normalized volunteer1 above, now normalize volunteer2
            first2_norm = _clean_text(volunteer2.first_name).lower().strip() if volunteer2.first_name else ""
            last2_norm = _clean_text(volunteer2.last_name).lower().strip() if volunteer2.last_name else ""
            
            # Exact match check (both first and last must match exactly)
            exact_match = (first1_norm == first2_norm and last1_norm == last2_norm)
            
            # Debug logging for exact matches (can be removed later)
            if exact_match and has_app_context():
                current_app.logger.debug(
                    f"Exact name match found: Volunteer {volunteer1.id} ('{volunteer1.first_name} {volunteer1.last_name}') "
                    f"matches Volunteer {volunteer2.id} ('{volunteer2.first_name} {volunteer2.last_name}')"
                )
            
            # If not exact match, check fuzzy similarity
            if not exact_match:
                name_sim = compute_name_similarity(
                    volunteer1.first_name, volunteer1.last_name,
                    volunteer2.first_name, volunteer2.last_name
                )
                
                if name_sim < similarity_threshold:
                    continue
            else:
                # For exact matches, set similarity to 1.0
                name_sim = 1.0
            
            # Build full feature map for scoring
            volunteer1_dob = volunteer1.birthdate.isoformat() if volunteer1.birthdate else None
            volunteer2_dob = volunteer2.birthdate.isoformat() if volunteer2.birthdate else None
            
            primary_address1 = _get_primary_address_for_volunteer(volunteer1)
            primary_address2 = _get_primary_address_for_volunteer(volunteer2)
            
            volunteer1_emails = [e.email for e in volunteer1.emails]
            volunteer1_phones = [p.phone_number for p in volunteer1.phones]
            volunteer2_emails = [e.email for e in volunteer2.emails]
            volunteer2_phones = [p.phone_number for p in volunteer2.phones]
            
            # Build features dictionary (needed for both exact and fuzzy matches)
            dob_match = compute_dob_proximity(volunteer1_dob, volunteer2_dob)
            address_match = compute_address_similarity(
                primary_address1.street_address_1 if primary_address1 else None,
                primary_address1.city if primary_address1 else None,
                primary_address1.postal_code if primary_address1 else None,
                primary_address2.street_address_1 if primary_address2 else None,
                primary_address2.city if primary_address2 else None,
                primary_address2.postal_code if primary_address2 else None,
            )
            alt_contact_match = compute_alternate_contact_match(
                volunteer1_emails, volunteer1_phones,
                volunteer2_emails, volunteer2_phones,
            )
            
            # For exact name matches, use a high score even if other features are missing
            if exact_match:
                # Exact name match should score high (at least 0.90) even without other signals
                base_score = 0.90
                # Boost score with additional matches
                score = min(1.0, base_score + (dob_match * 0.05) + (address_match * 0.03) + (alt_contact_match * 0.02))
                # Build features dict for exact matches (for logging/debugging)
                features = {
                    "name": 1.0,  # Exact match
                    "dob": dob_match,
                    "address": address_match,
                    "employer": 0.0,  # Not available in Volunteer model
                    "school": 0.0,  # Not available in Volunteer model
                    "alternate_contact": alt_contact_match,
                }
            else:
                # Use normal weighted scoring for fuzzy matches
                features = {
                    "name": name_sim,
                    "dob": dob_match,
                    "address": address_match,
                    "employer": 0.0,  # Not available in Volunteer model
                    "school": 0.0,  # Not available in Volunteer model
                    "alternate_contact": alt_contact_match,
                }
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
            
            # Use the volunteer with the lower ID as primary to avoid duplicate suggestions
            if volunteer1.id < volunteer2.id:
                primary_id = volunteer1.id
                candidate_id = volunteer2.id
            else:
                primary_id = volunteer2.id
                candidate_id = volunteer1.id
            
            # Check if suggestion already exists (always check with lower ID as primary)
            existing = (
                session.query(DedupeSuggestion.id)
                .filter(
                    DedupeSuggestion.primary_contact_id == primary_id,
                    DedupeSuggestion.candidate_contact_id == candidate_id,
                    DedupeSuggestion.decision == DedupeDecision.PENDING,
                )
                .first()
            )
            if existing:
                continue
            
            # Create a special "scan" import run if needed, or use a placeholder
            # For now, we'll need to create a dummy run or make run_id nullable
            # Check if we can use None - if not, we'll need to create a special run
            # Let's try using a special run_id of 0 or create a scan run
            from flask_app.models.importer.schema import ImportRun, ImportRunStatus
            scan_run = (
                session.query(ImportRun)
                .filter(ImportRun.source == "duplicate_scan", ImportRun.status == ImportRunStatus.SUCCEEDED)
                .order_by(ImportRun.id.desc())
                .first()
            )
            if not scan_run:
                # Create a special run for tracking scans
                scan_run = ImportRun(
                    source="duplicate_scan",
                    adapter="manual_scan",
                    status=ImportRunStatus.SUCCEEDED,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    dry_run=False,
                )
                session.add(scan_run)
                session.flush()
            
            suggestion = DedupeSuggestion(
                run_id=scan_run.id,
                staging_volunteer_id=None,
                primary_contact_id=primary_id,
                candidate_contact_id=candidate_id,
                score=_to_decimal(score),
                confidence_score=_to_decimal(score),
                match_type=match_type,
                decision=DedupeDecision.PENDING,
                features_json=_build_features_payload(features, score),
                decision_notes="Found during manual duplicate scan of existing volunteers.",
            )
            pending_suggestions.append(suggestion)
            
            if len(pending_suggestions) >= batch_size:
                session.add_all(pending_suggestions)
                session.flush()
                pending_suggestions.clear()
    
    if not dry_run and pending_suggestions:
        session.add_all(pending_suggestions)
        session.flush()
    
    return summary


def _get_primary_address_for_volunteer(volunteer: Volunteer) -> ContactAddress | None:
    """Get primary address for a volunteer."""
    from flask_app.models import ContactAddress
    addresses = getattr(volunteer, "addresses", [])
    for address in addresses:
        if address.is_primary:
            return address
    return addresses[0] if addresses else None


def _get_primary_address(volunteer: Volunteer) -> Optional[ContactAddress]:
    addresses = getattr(volunteer, "addresses", [])
    for address in addresses:
        if address.is_primary:
            return address
    return addresses[0] if addresses else None


__all__ = ["generate_fuzzy_candidates", "FuzzyCandidateSummary", "scan_existing_volunteers_for_duplicates"]
