"""Canonical volunteer ingest contract definitions.

The contract mirrors the documentation in ``docs/data-integration-platform-*.md``
and provides a single source of truth for importer adapters that must validate
CSV headers, map source payloads, and produce staging rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence, Tuple

Normalizer = Callable[[object | None], object | None]


def _strip_string(value: object | None) -> object | None:
    if isinstance(value, str):
        return value.strip()
    return value


@dataclass(frozen=True)
class FieldSpec:
    """Metadata describing a canonical ingest field."""

    name: str
    description: str
    required: bool = False
    aliases: Tuple[str, ...] = ()
    normalizer: Normalizer | None = _strip_string

    def headers(self) -> Tuple[str, ...]:
        """Return the canonical header plus aliases for validation."""

        return (self.name, *self.aliases)


VOLUNTEER_CANONICAL_FIELDS: Tuple[FieldSpec, ...] = (
    FieldSpec(
        name="external_system",
        description="Source system identifier (e.g., csv, salesforce).",
        required=False,
        aliases=("source_system",),
    ),
    FieldSpec(
        name="external_id",
        description="Stable identifier supplied by the source system.",
        required=False,
        aliases=("source_id", "record_id"),
    ),
    FieldSpec(
        name="first_name",
        description="Volunteer given name.",
        required=True,
        aliases=("given_name", "first"),
    ),
    FieldSpec(
        name="last_name",
        description="Volunteer family name.",
        required=True,
        aliases=("surname", "last"),
    ),
    FieldSpec(
        name="middle_name",
        description="Volunteer middle name or initial.",
        required=False,
        aliases=("middle",),
    ),
    FieldSpec(
        name="preferred_name",
        description="Preferred display name.",
        required=False,
        aliases=("nickname", "preferred"),
    ),
    FieldSpec(
        name="email",
        description="Primary email address (normalized lower-case).",
        required=False,
        aliases=("email_address", "primary_email"),
    ),
    FieldSpec(
        name="alternate_emails",
        description="Comma-separated list of alternate emails.",
        required=False,
        aliases=("alt_emails", "secondary_emails"),
    ),
    FieldSpec(
        name="phone",
        description="Primary phone number (E.164 when possible).",
        required=False,
        aliases=("phone_number", "primary_phone", "mobile"),
    ),
    FieldSpec(
        name="alternate_phones",
        description="Comma-separated list of alternate phone numbers.",
        required=False,
        aliases=("alt_phones", "secondary_phones"),
    ),
    FieldSpec(
        name="dob",
        description="Date of birth (ISO-8601 format).",
        required=False,
        aliases=("date_of_birth", "birthdate"),
    ),
    FieldSpec(
        name="gender",
        description="Gender identity or expression.",
        required=False,
    ),
    FieldSpec(
        name="race_ethnicity",
        description="Race/ethnicity classification.",
        required=False,
        aliases=("race", "ethnicity"),
    ),
    FieldSpec(
        name="street",
        description="Street address line.",
        required=False,
        aliases=("address", "address_line1"),
    ),
    FieldSpec(
        name="street2",
        description="Additional address line.",
        required=False,
        aliases=("address_line2", "apt"),
    ),
    FieldSpec(
        name="city",
        description="City or locality.",
        required=False,
    ),
    FieldSpec(
        name="state_code",
        description="Two-letter state or region code.",
        required=False,
        aliases=("state", "region"),
    ),
    FieldSpec(
        name="postal_code",
        description="Postal or ZIP code.",
        required=False,
        aliases=("zip", "zip_code"),
    ),
    FieldSpec(
        name="country_code",
        description="ISO country code.",
        required=False,
        aliases=("country",),
    ),
    FieldSpec(
        name="employer",
        description="Primary employer or organization.",
        required=False,
    ),
    FieldSpec(
        name="school_affiliation",
        description="School or educational affiliation.",
        required=False,
        aliases=("school", "school_name"),
    ),
    FieldSpec(
        name="student_flag",
        description="Indicates whether the volunteer is a student (true/false).",
        required=False,
        aliases=("is_student",),
    ),
    FieldSpec(
        name="consent_signed_at",
        description="Datetime when required consent was signed (ISO-8601).",
        required=False,
        aliases=("consent_date", "consent_timestamp"),
    ),
    FieldSpec(
        name="background_check_status",
        description="Background check status code.",
        required=False,
        aliases=("bgc_status", "background_status"),
    ),
    FieldSpec(
        name="background_check_date",
        description="Date of last background check (ISO-8601).",
        required=False,
        aliases=("bgc_date", "background_date"),
    ),
    FieldSpec(
        name="photo_release",
        description="Indicates consent for photo/video use (true/false).",
        required=False,
        aliases=("photo_consent",),
    ),
    FieldSpec(
        name="source_updated_at",
        description="Timestamp of the record in the source system (ISO-8601).",
        required=False,
        aliases=("last_modified", "updated_at"),
    ),
    FieldSpec(
        name="ingested_at",
        description="Timestamp when this payload was generated (ISO-8601).",
        required=False,
    ),
    FieldSpec(
        name="ingest_version",
        description="Contract version identifier for compatibility.",
        required=False,
        aliases=("contract_version",),
    ),
)


def get_volunteer_field_specs() -> Tuple[FieldSpec, ...]:
    """Return the canonical volunteer field specifications."""

    return VOLUNTEER_CANONICAL_FIELDS


def get_volunteer_required_headers() -> Tuple[str, ...]:
    """Headers that must be present in every CSV import."""

    return tuple(field.name for field in VOLUNTEER_CANONICAL_FIELDS if field.required)


def get_volunteer_optional_headers() -> Tuple[str, ...]:
    """Headers that are part of the contract but optional for importers."""

    return tuple(field.name for field in VOLUNTEER_CANONICAL_FIELDS if not field.required)


def get_volunteer_supported_headers() -> Tuple[str, ...]:
    """Return all canonical header names supported by the contract."""

    return tuple(field.name for field in VOLUNTEER_CANONICAL_FIELDS)


def get_volunteer_alias_map() -> Mapping[str, str]:
    """Map normalized header tokens to canonical names (includes aliases)."""

    mapping: dict[str, str] = {}
    for field in VOLUNTEER_CANONICAL_FIELDS:
        for header in field.headers():
            mapping[normalize_header(header)] = field.name
    return mapping


def normalize_header(header: str) -> str:
    """Normalize a CSV header for comparison (case/space/underscore agnostic)."""

    token = header.strip().lower()
    for char in (" ", "-", "."):
        token = token.replace(char, "_")
    return token


def normalize_payload(payload: Mapping[str, object]) -> dict[str, object | None]:
    """Apply field normalizers to a raw payload and coerce to canonical keys."""

    alias_map = get_volunteer_alias_map()
    normalized: dict[str, object | None] = {}
    for raw_key, value in payload.items():
        canonical_key = alias_map.get(normalize_header(raw_key))
        if canonical_key is None:
            continue
        spec = next(field for field in VOLUNTEER_CANONICAL_FIELDS if field.name == canonical_key)
        normalizer = spec.normalizer
        normalized[canonical_key] = normalizer(value) if normalizer else value
    return normalized


def required_headers_missing(headers: Iterable[str]) -> Tuple[str, ...]:
    """Return the subset of required headers that are missing from a CSV file."""

    header_set = {normalize_header(header) for header in headers}
    missing: list[str] = []
    for required in get_volunteer_required_headers():
        if normalize_header(required) not in header_set:
            missing.append(required)
    return tuple(missing)


def resolve_headers(headers: Sequence[str]) -> Tuple[str, ...]:
    """Resolve raw headers to canonical names using aliases."""

    alias_map = get_volunteer_alias_map()
    resolved: list[str] = []
    for header in headers:
        normalized_header = normalize_header(header)
        canonical = alias_map.get(normalized_header)
        if canonical is None:
            resolved.append(header)
        else:
            resolved.append(canonical)
    return tuple(resolved)
