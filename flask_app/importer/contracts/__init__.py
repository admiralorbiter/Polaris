"""Canonical ingest contract helpers for importer adapters."""

from __future__ import annotations

from .volunteer import (
    VOLUNTEER_CANONICAL_FIELDS,
    FieldSpec,
    get_volunteer_alias_map,
    get_volunteer_field_specs,
    get_volunteer_optional_headers,
    get_volunteer_required_headers,
    get_volunteer_supported_headers,
    normalize_header,
)

__all__ = [
    "FieldSpec",
    "VOLUNTEER_CANONICAL_FIELDS",
    "get_volunteer_field_specs",
    "get_volunteer_required_headers",
    "get_volunteer_optional_headers",
    "get_volunteer_supported_headers",
    "get_volunteer_alias_map",
    "normalize_header",
]
