"""
Survivorship precedence configuration for importer field conflict resolution.

The importer loads this module to determine which source should win for each
field group when conflicting values are detected between an existing core
record, manual remediation edits, and fresh incoming payloads.

Configuration is file-backed so we do not require database tables or migrations.
Operators can optionally override these defaults by providing a JSON or YAML
file path through the ``IMPORTER_SURVIVORSHIP_PROFILE_PATH`` environment
variable. The helper exposed here handles loading and validating those
overrides.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, Sequence

import json

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


SourceTier = str
"""Identifier for a precedence tier (e.g., ``manual`` or ``incoming``)."""


@dataclass(frozen=True)
class FieldRule:
    """
    Survivorship precedence details for a single field.

    Attributes:
        field_name: Target attribute on the Volunteer/Contact model.
        tier_order: Ordered list of source tiers; earlier entries have higher
            precedence. The built-in tiers are ``manual``, ``verified_core``,
            ``existing_core``, and ``incoming`` but custom tiers are allowed.
        prefer_non_null: When true, null/blank values lose to non-null values
            even if they originate from a higher tier.
        prefer_recent_verified: When true, the resolver compares verification
            timestamps within the same tier and picks the most recently
            verified value.
    """

    field_name: str
    tier_order: Sequence[SourceTier]
    prefer_non_null: bool = True
    prefer_recent_verified: bool = True


@dataclass(frozen=True)
class FieldGroup:
    """
    Group of related fields that share precedence behavior.

    Groups help the UI summarize survivorship decisions.
    """

    name: str
    display_name: str
    fields: Sequence[FieldRule]


@dataclass(frozen=True)
class SurvivorshipProfile:
    """
    Container for all precedence rules.

    The loader resolves conflicts by looking up the field in the active
    profile, falling back to the ``default_tier_order`` when necessary.
    """

    key: str
    label: str
    description: str
    field_groups: Sequence[FieldGroup]
    default_tier_order: Sequence[SourceTier]

    def find_rule(self, field_name: str) -> FieldRule | None:
        for group in self.field_groups:
            for rule in group.fields:
                if rule.field_name == field_name:
                    return rule
        return None


# ---------------------------------------------------------------------------
# Default profile
# ---------------------------------------------------------------------------

DEFAULT_TIER_ORDER: tuple[SourceTier, ...] = (
    "manual",
    "verified_core",
    "incoming",
    "existing_core",
)

IDENTITY_FIELDS: tuple[FieldRule, ...] = (
    FieldRule("first_name", DEFAULT_TIER_ORDER),
    FieldRule("middle_name", DEFAULT_TIER_ORDER),
    FieldRule("last_name", DEFAULT_TIER_ORDER),
    FieldRule("preferred_name", DEFAULT_TIER_ORDER),
)

COMMUNICATION_FIELDS: tuple[FieldRule, ...] = (
    FieldRule("email", DEFAULT_TIER_ORDER),
    FieldRule("phone_e164", DEFAULT_TIER_ORDER),
)

NOTES_FIELDS: tuple[FieldRule, ...] = (
    FieldRule("notes", DEFAULT_TIER_ORDER, prefer_recent_verified=False),
    FieldRule("internal_notes", DEFAULT_TIER_ORDER, prefer_recent_verified=False),
)

DEFAULT_PROFILE = SurvivorshipProfile(
    key="default",
    label="Default survivorship",
    description="Manual edits override verified core values, which beat existing core data, "
    "and incoming payloads only win when no higher-tier value exists.",
    field_groups=(
        FieldGroup("identity", "Identity", IDENTITY_FIELDS),
        FieldGroup("communication", "Communication", COMMUNICATION_FIELDS),
        FieldGroup("notes", "Notes", NOTES_FIELDS),
    ),
    default_tier_order=DEFAULT_TIER_ORDER,
)


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


class SurvivorshipConfigError(RuntimeError):
    """Raised when a configuration override cannot be parsed."""


def _load_override(path: Path) -> MutableMapping[str, object]:
    if not path.exists():
        raise SurvivorshipConfigError(f"Survivorship override file {path} does not exist.")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem failure
        raise SurvivorshipConfigError(f"Unable to read survivorship override file {path}: {exc}") from exc

    if path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise SurvivorshipConfigError("PyYAML is required to load YAML survivorship overrides.")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    if not isinstance(data, Mapping):
        raise SurvivorshipConfigError("Survivorship override must be a JSON/YAML object.")
    return dict(data)


def _coerce_sequence(
    value: object | None,
    *,
    coerce_item,
    item_name: str,
) -> tuple:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(coerce_item(item) for item in value)
    raise SurvivorshipConfigError(f"Expected sequence for {item_name}, got {type(value).__name__}.")


def _coerce_field_rule(raw: Mapping[str, object]) -> FieldRule:
    name = str(raw.get("field_name") or "").strip()
    if not name:
        raise SurvivorshipConfigError("Each field rule requires a non-empty field_name.")
    tier_order = _coerce_sequence(
        raw.get("tier_order"),
        coerce_item=lambda item: str(item).strip(),
        item_name=f"{name}.tier_order",
    )
    if not tier_order:
        tier_order = DEFAULT_TIER_ORDER
    prefer_non_null = bool(raw.get("prefer_non_null", True))
    prefer_recent_verified = bool(raw.get("prefer_recent_verified", True))
    return FieldRule(
        field_name=name,
        tier_order=tier_order,
        prefer_non_null=prefer_non_null,
        prefer_recent_verified=prefer_recent_verified,
    )


def _coerce_field_group(raw: Mapping[str, object]) -> FieldGroup:
    name = str(raw.get("name") or "").strip()
    display_name = str(raw.get("display_name") or name or "").strip()
    if not name:
        raise SurvivorshipConfigError("Each field group requires a non-empty name.")
    fields_raw = raw.get("fields") or ()
    if not isinstance(fields_raw, Iterable):
        raise SurvivorshipConfigError(f"Group {name} fields must be a sequence.")
    rules = tuple(_coerce_field_rule(rule) for rule in fields_raw)  # type: ignore[arg-type]
    return FieldGroup(name=name, display_name=display_name or name.title(), fields=rules)


def _coerce_profile(raw: Mapping[str, object]) -> SurvivorshipProfile:
    key = str(raw.get("key") or DEFAULT_PROFILE.key).strip() or DEFAULT_PROFILE.key
    label = str(raw.get("label") or DEFAULT_PROFILE.label).strip() or DEFAULT_PROFILE.label
    description = str(raw.get("description") or DEFAULT_PROFILE.description).strip() or DEFAULT_PROFILE.description
    default_tier_order = _coerce_sequence(
        raw.get("default_tier_order"),
        coerce_item=lambda item: str(item).strip(),
        item_name="default_tier_order",
    )
    if not default_tier_order:
        default_tier_order = DEFAULT_TIER_ORDER
    raw_groups = raw.get("field_groups") or ()
    if not isinstance(raw_groups, Iterable):
        raise SurvivorshipConfigError("field_groups must be a sequence.")
    groups = tuple(_coerce_field_group(group) for group in raw_groups)  # type: ignore[arg-type]
    if not groups:
        groups = DEFAULT_PROFILE.field_groups
    return SurvivorshipProfile(
        key=key,
        label=label,
        description=description,
        field_groups=groups,
        default_tier_order=default_tier_order,
    )


def load_profile(env: Mapping[str, str] | None = None) -> SurvivorshipProfile:
    """
    Load the active survivorship profile.

    If the ``IMPORTER_SURVIVORSHIP_PROFILE_PATH`` environment variable is set,
    its JSON/YAML content is parsed to override the default profile. Otherwise
    the built-in defaults are used.
    """

    env_map = env or {}
    override_path = env_map.get("IMPORTER_SURVIVORSHIP_PROFILE_PATH")
    if not override_path:
        return DEFAULT_PROFILE
    path = Path(override_path)
    raw = _load_override(path)
    return _coerce_profile(raw)


__all__ = [
    "FieldGroup",
    "FieldRule",
    "SurvivorshipConfigError",
    "SurvivorshipProfile",
    "DEFAULT_PROFILE",
    "load_profile",
]

