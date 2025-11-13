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
    Handles US phone numbers without country code by assuming +1.
    Strips extensions (x, ext, extension) before normalizing.
    """

    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None

    # Strip extensions (x123, ext 123, extension 123, etc.)
    # Handle common extension patterns: x123, ext123, ext 123, extension 123, #123
    import re
    # Remove extension patterns (case-insensitive)
    token = re.sub(r'\s*(x|ext|extension|#)\s*\d+.*$', '', token, flags=re.IGNORECASE)
    token = token.strip()
    if not token:
        return None

    # Strip common formatting characters
    token = token.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace(".", "")
    
    # Handle international format starting with 00
    if token.startswith("00"):
        token = f"+{token[2:]}"
    
    # Extract digits only (excluding +) for validation
    digits_only = ''.join(c for c in token if c.isdigit())
    
    # If it doesn't start with +, try to normalize it
    if not token.startswith("+"):
        # If it's 10 digits, assume US number and prepend +1
        if len(digits_only) == 10:
            normalized = f"+1{digits_only}"
        # If it's 11 digits starting with 1, prepend +
        elif len(digits_only) == 11 and digits_only.startswith("1"):
            normalized = f"+{digits_only}"
        else:
            # Can't normalize - return None
            return None
    else:
        # Already has + prefix - extract just digits to validate
        if not digits_only.isdigit():
            return None
        normalized = f"+{digits_only}"
    
    # Validate the normalized format matches E.164
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
