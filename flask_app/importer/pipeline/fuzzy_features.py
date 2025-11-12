from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable, Sequence

from rapidfuzz import fuzz, utils
from rapidfuzz.distance import JaroWinkler

from flask_app.importer.pipeline.deterministic import normalize_email, normalize_phone

# Default feature weights (kept here for now; Config UI will externalize in Sprint 7)
NAME_WEIGHT = 0.25
DOB_WEIGHT = 0.20
ADDRESS_WEIGHT = 0.15
EMPLOYER_WEIGHT = 0.10
SCHOOL_WEIGHT = 0.10
ALT_CONTACT_WEIGHT = 0.20


def _clean_text(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _combine_name(first: object | None, last: object | None) -> str:
    first_clean = _clean_text(first)
    last_clean = _clean_text(last)
    return " ".join(part for part in (first_clean, last_clean) if part)


def compute_name_similarity(first1: object | None, last1: object | None, first2: object | None, last2: object | None) -> float:
    """Return Jaro-Winkler similarity between two name pairs (0..1)."""

    if not (_clean_text(first1) and _clean_text(last1) and _clean_text(first2) and _clean_text(last2)):
        return 0.0

    name1 = _combine_name(first1, last1)
    name2 = _combine_name(first2, last2)

    if not name1 or not name2:
        return 0.0

    score = JaroWinkler.normalized_similarity(name1.lower(), name2.lower())
    return float(max(0.0, min(1.0, score)))


def _parse_iso_date(value: object | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = _clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_dob_proximity(dob1: object | None, dob2: object | None) -> float:
    """Score proximity between DOB values (0..1).

    Exact match returns 1. Values differing by a year score ~0.5. Anything beyond ~2 years drops toward 0.
    """

    dt1 = _parse_iso_date(dob1)
    dt2 = _parse_iso_date(dob2)
    if dt1 is None or dt2 is None:
        return 0.0

    diff_days = abs((dt1.date() - dt2.date()).days)
    if diff_days == 0:
        return 1.0

    # Linear decay: 0.5 at 365 days, clamp to 0 beyond ~2 years (730 days)
    score = 1.0 - (diff_days / 730)
    return float(max(0.0, min(1.0, score)))


def _address_tokens(street: object | None, city: object | None) -> str:
    parts = [utils.default_process(_clean_text(street)), utils.default_process(_clean_text(city))]
    return " ".join(filter(None, parts))


def compute_address_similarity(
    street1: object | None,
    city1: object | None,
    zip1: object | None,
    street2: object | None,
    city2: object | None,
    zip2: object | None,
) -> float:
    """Return token-based similarity for addresses (0..1) with small bonuses for exact city/ZIP matches."""

    tokens1 = _address_tokens(street1, city1)
    tokens2 = _address_tokens(street2, city2)

    if not tokens1 or not tokens2:
        return 0.0

    base_score = fuzz.token_set_ratio(tokens1, tokens2) / 100.0
    bonus = 0.0

    zip1_clean = _clean_text(zip1)
    zip2_clean = _clean_text(zip2)
    if zip1_clean and zip2_clean and zip1_clean == zip2_clean:
        bonus += 0.1

    city1_clean = _clean_text(city1).lower()
    city2_clean = _clean_text(city2).lower()
    if city1_clean and city2_clean and city1_clean == city2_clean:
        bonus += 0.05

    score = base_score + bonus
    return float(max(0.0, min(1.0, score)))


def compute_employer_similarity(emp1: object | None, emp2: object | None) -> float:
    return _token_similarity(emp1, emp2)


def compute_school_similarity(school1: object | None, school2: object | None) -> float:
    return _token_similarity(school1, school2)


def _token_similarity(value1: object | None, value2: object | None) -> float:
    text1 = utils.default_process(_clean_text(value1))
    text2 = utils.default_process(_clean_text(value2))
    if not text1 or not text2:
        return 0.0
    return float(fuzz.token_sort_ratio(text1, text2) / 100.0)


def _ensure_sequence(value: object | None) -> Sequence[str]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(_clean_text(item) for item in value if _clean_text(item))
    if isinstance(value, str):
        return (_clean_text(value),)
    return (_clean_text(value),)


def compute_alternate_contact_match(
    candidate_emails: object | None,
    candidate_phones: object | None,
    primary_emails: object | None,
    primary_phones: object | None,
) -> float:
    """Return 1.0 if any alternate contact detail from the candidate matches the primary/alternate set."""

    candidate_email_tokens = {
        normalize_email(email)
        for email in _ensure_sequence(candidate_emails)
        if normalize_email(email)
    }
    candidate_phone_tokens = {
        normalize_phone(phone)
        for phone in _ensure_sequence(candidate_phones)
        if normalize_phone(phone)
    }

    primary_email_tokens = {
        normalize_email(email)
        for email in _ensure_sequence(primary_emails)
        if normalize_email(email)
    }
    primary_phone_tokens = {
        normalize_phone(phone)
        for phone in _ensure_sequence(primary_phones)
        if normalize_phone(phone)
    }

    if candidate_email_tokens & primary_email_tokens:
        return 1.0
    if candidate_phone_tokens & primary_phone_tokens:
        return 1.0
    return 0.0


def weighted_score(features: dict[str, float]) -> float:
    """Compute a weighted composite score using default weights.

    Expected keys: name, dob, address, employer, school, alternate_contact.
    Missing keys default to 0.0.
    """

    weights = {
        "name": NAME_WEIGHT,
        "dob": DOB_WEIGHT,
        "address": ADDRESS_WEIGHT,
        "employer": EMPLOYER_WEIGHT,
        "school": SCHOOL_WEIGHT,
        "alternate_contact": ALT_CONTACT_WEIGHT,
    }

    total = 0.0
    for key, weight in weights.items():
        total += weight * max(0.0, min(1.0, features.get(key, 0.0)))

    return float(max(0.0, min(1.0, total)))


def summarize_features(features: dict[str, float]) -> dict[str, float]:
    """Clamp feature scores to [0,1] and round to 3 decimal places for persistence."""

    return {
        key: round(max(0.0, min(1.0, value)), 3)
        for key, value in features.items()
    }


__all__ = [
    "NAME_WEIGHT",
    "DOB_WEIGHT",
    "ADDRESS_WEIGHT",
    "EMPLOYER_WEIGHT",
    "SCHOOL_WEIGHT",
    "ALT_CONTACT_WEIGHT",
    "compute_name_similarity",
    "compute_dob_proximity",
    "compute_address_similarity",
    "compute_employer_similarity",
    "compute_school_similarity",
    "compute_alternate_contact_match",
    "weighted_score",
    "summarize_features",
]
