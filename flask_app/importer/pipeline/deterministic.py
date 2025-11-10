"""
Deterministic email/phone matching helpers for importer dedupe (IMP-31).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from flask_app.models import ContactEmail, ContactPhone, Volunteer

_E164_REGEX = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_email(value: object | None) -> str | None:
    """
    Normalize email for deterministic matching.

    - Lower-case entire address
    - Trim whitespace
    - Drop plus-addressing suffix (everything after '+') in the local part
    """

    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None
    token = token.lower()
    if "@" not in token:
        return token
    local_part, domain = token.split("@", 1)
    if "+" in local_part:
        local_part = local_part.split("+", 1)[0]
    return f"{local_part}@{domain}"


def normalize_phone(value: object | None) -> str | None:
    """
    Normalize phone numbers to strict E.164 (+<country><number>) format.
    """

    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None

    token = token.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if token.startswith("00"):
        token = f"+{token[2:]}"
    if not token.startswith("+"):
        return None
    candidate = f"+{token[1:]}" if token.startswith("+") else token
    digits = candidate[1:]
    if not digits.isdigit():
        return None
    normalized = f"+{digits}"
    if _E164_REGEX.match(normalized):
        return normalized
    return None


@dataclass(frozen=True)
class DeterministicMatchResult:
    """
    Outcome from running deterministic email/phone matching.

    Attributes:
        outcome: Resolution status ('combined', 'email', 'phone', 'none',
            'ambiguous', or 'insufficient' when no identifiers supplied).
        volunteer_id: Matched volunteer ID when outcome is deterministic.
        email_match_ids: Volunteer IDs that matched by email heuristic.
        phone_match_ids: Volunteer IDs that matched by phone heuristic.
        normalized_email: Normalized email token (if supplied).
        normalized_phone: Normalized phone token (if supplied).
    """

    outcome: Literal["combined", "email", "phone", "none", "ambiguous", "insufficient"]
    volunteer_id: int | None
    email_match_ids: tuple[int, ...]
    phone_match_ids: tuple[int, ...]
    normalized_email: str | None
    normalized_phone: str | None

    @property
    def is_match(self) -> bool:
        return self.outcome in {"combined", "email", "phone"}


def match_volunteer_by_contact(
    session: Session,
    *,
    email: object | None,
    phone: object | None,
) -> DeterministicMatchResult:
    """
    Attempt deterministic resolution of a volunteer via normalized email/phone.
    """

    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone)

    if not normalized_email and not normalized_phone:
        return DeterministicMatchResult(
            outcome="insufficient",
            volunteer_id=None,
            email_match_ids=(),
            phone_match_ids=(),
            normalized_email=None,
            normalized_phone=None,
        )

    email_ids: set[int] = set()
    phone_ids: set[int] = set()

    if normalized_email and "@" in normalized_email:
        local_part, domain = normalized_email.split("@", 1)
        lower_email = func.lower(ContactEmail.email)
        filters = [lower_email == normalized_email]
        if local_part:
            filters.append(lower_email.like(f"{local_part}%@{domain}"))
        email_matches = (
            session.query(Volunteer.id)
            .join(ContactEmail, ContactEmail.contact_id == Volunteer.id)
            .filter(or_(*filters))
            .all()
        )
        email_ids = {match[0] for match in email_matches}

    if normalized_phone:
        phone_matches = (
            session.query(Volunteer.id)
            .join(ContactPhone, ContactPhone.contact_id == Volunteer.id)
            .filter(ContactPhone.phone_number == normalized_phone)
            .all()
        )
        phone_ids = {match[0] for match in phone_matches}

    email_tuple = tuple(sorted(email_ids))
    phone_tuple = tuple(sorted(phone_ids))

    if not email_ids and not phone_ids:
        return DeterministicMatchResult(
            outcome="none",
            volunteer_id=None,
            email_match_ids=email_tuple,
            phone_match_ids=phone_tuple,
            normalized_email=normalized_email,
            normalized_phone=normalized_phone,
        )

    common_ids = email_ids & phone_ids
    if common_ids:
        if len(common_ids) == 1:
            volunteer_id = next(iter(common_ids))
            return DeterministicMatchResult(
                outcome="combined",
                volunteer_id=volunteer_id,
                email_match_ids=email_tuple,
                phone_match_ids=phone_tuple,
                normalized_email=normalized_email,
                normalized_phone=normalized_phone,
            )
        return DeterministicMatchResult(
            outcome="ambiguous",
            volunteer_id=None,
            email_match_ids=email_tuple,
            phone_match_ids=phone_tuple,
            normalized_email=normalized_email,
            normalized_phone=normalized_phone,
        )

    if email_ids and not phone_ids:
        if len(email_ids) == 1:
            volunteer_id = next(iter(email_ids))
            return DeterministicMatchResult(
                outcome="email",
                volunteer_id=volunteer_id,
                email_match_ids=email_tuple,
                phone_match_ids=phone_tuple,
                normalized_email=normalized_email,
                normalized_phone=normalized_phone,
            )
        return DeterministicMatchResult(
            outcome="ambiguous",
            volunteer_id=None,
            email_match_ids=email_tuple,
            phone_match_ids=phone_tuple,
            normalized_email=normalized_email,
            normalized_phone=normalized_phone,
        )

    if phone_ids and not email_ids:
        if len(phone_ids) == 1:
            volunteer_id = next(iter(phone_ids))
            return DeterministicMatchResult(
                outcome="phone",
                volunteer_id=volunteer_id,
                email_match_ids=email_tuple,
                phone_match_ids=phone_tuple,
                normalized_email=normalized_email,
                normalized_phone=normalized_phone,
            )
        return DeterministicMatchResult(
            outcome="ambiguous",
            volunteer_id=None,
            email_match_ids=email_tuple,
            phone_match_ids=phone_tuple,
            normalized_email=normalized_email,
            normalized_phone=normalized_phone,
        )

    return DeterministicMatchResult(
        outcome="ambiguous",
        volunteer_id=None,
        email_match_ids=email_tuple,
        phone_match_ids=phone_tuple,
        normalized_email=normalized_email,
        normalized_phone=normalized_phone,
    )
