"""
Helpers for determining field-level survivorship during importer loads.

This module evaluates incoming payloads against existing core data and any
manual remediation overrides to decide which value should win for each field.
It produces structured decision metadata that downstream code can persist in
the change log and surface via APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from collections import Counter

from config.survivorship import FieldGroup, FieldRule, SurvivorshipProfile

SourceTier = str


def _coerce_mapping(candidate: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not candidate:
        return {}
    if isinstance(candidate, Mapping):
        return candidate
    return {}


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _is_effectively_null(value: Any) -> bool:
    value = _normalize_value(value)
    return value is None


@dataclass(frozen=True)
class FieldCandidate:
    tier: SourceTier
    value: Any
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class FieldDecision:
    field_name: str
    group_name: str
    winner: FieldCandidate
    losers: Sequence[FieldCandidate]
    changed: bool
    manual_override: bool
    reason: str


@dataclass(frozen=True)
class SurvivorshipResult:
    resolved_values: Mapping[str, Any]
    decisions: Sequence[FieldDecision]
    stats: Mapping[str, int]


def _candidate_for_tier(
    tier: SourceTier,
    field_name: str,
    *,
    incoming_payload: Mapping[str, Any],
    core_snapshot: Mapping[str, Any],
    manual_overrides: Mapping[str, Mapping[str, Any]],
    verified_snapshot: Mapping[str, Mapping[str, Any]],
    incoming_provenance: Mapping[str, Any],
) -> FieldCandidate:
    metadata: MutableMapping[str, Any] = {"tier": tier}
    value: Any = None

    if tier == "manual":
        manual_entry = manual_overrides.get(field_name, {})
        if isinstance(manual_entry, Mapping):
            value = manual_entry.get("value")
            metadata.update({k: v for k, v in manual_entry.items() if k != "value"})
        else:
            value = manual_entry
        metadata.setdefault("source", "manual")
    elif tier == "verified_core":
        verified_entry = verified_snapshot.get(field_name, {})
        if isinstance(verified_entry, Mapping):
            value = verified_entry.get("value", core_snapshot.get(field_name))
            metadata.update({k: v for k, v in verified_entry.items() if k != "value"})
        else:
            value = core_snapshot.get(field_name)
        metadata.setdefault("source", "core")
        metadata.setdefault("verified", True)
    elif tier == "existing_core":
        value = core_snapshot.get(field_name)
        metadata.setdefault("source", "core")
    elif tier == "incoming":
        value = incoming_payload.get(field_name)
        metadata.setdefault("source", "incoming")
        metadata.update(incoming_provenance)
    else:
        value = None
        metadata.setdefault("source", tier)

    return FieldCandidate(tier=tier, value=_normalize_value(value), metadata=dict(metadata))


def _select_winner(rule: FieldRule, candidates: Sequence[FieldCandidate]) -> tuple[FieldCandidate, list[FieldCandidate]]:
    if not candidates:
        raise ValueError(f"Expected at least one candidate for field {rule.field_name}.")

    if rule.prefer_non_null:
        for candidate in candidates:
            if not _is_effectively_null(candidate.value):
                winner = candidate
                break
        else:
            winner = candidates[0]
    else:
        winner = candidates[0]

    losers = [candidate for candidate in candidates if candidate is not winner]
    return winner, losers


def apply_survivorship(
    *,
    profile: SurvivorshipProfile,
    incoming_payload: Mapping[str, Any],
    core_snapshot: Mapping[str, Any],
    manual_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    verified_snapshot: Mapping[str, Mapping[str, Any]] | None = None,
    incoming_provenance: Mapping[str, Any] | None = None,
) -> SurvivorshipResult:
    manual_overrides = _coerce_mapping(manual_overrides)
    verified_snapshot = _coerce_mapping(verified_snapshot)
    incoming_provenance = _coerce_mapping(incoming_provenance)

    resolved: MutableMapping[str, Any] = {}
    decisions: list[FieldDecision] = []
    stats: Counter[str] = Counter()

    field_group_lookup: dict[str, FieldGroup] = {
        rule.field_name: group for group in profile.field_groups for rule in group.fields
    }

    processed_fields: set[str] = set()

    for group in profile.field_groups:
        for rule in group.fields:
            field_name = rule.field_name
            processed_fields.add(field_name)
            tier_sequence = list(rule.tier_order)
            if "existing_core" not in tier_sequence:
                tier_sequence.append("existing_core")
            if "incoming" not in tier_sequence:
                tier_sequence.append("incoming")

            candidates: list[FieldCandidate] = []
            for tier in tier_sequence:
                if tier == "manual" and field_name not in manual_overrides:
                    continue
                if tier == "verified_core" and field_name not in verified_snapshot:
                    continue
                candidates.append(
                    _candidate_for_tier(
                        tier,
                        field_name,
                        incoming_payload=incoming_payload,
                        core_snapshot=core_snapshot,
                        manual_overrides=manual_overrides,
                        verified_snapshot=verified_snapshot,
                        incoming_provenance=incoming_provenance,
                    )
                )
            winner, losers = _select_winner(rule, candidates)
            resolved[field_name] = winner.value

            existing_value = core_snapshot.get(field_name)
            changed = winner.value != existing_value
            manual_override = winner.tier == "manual"

            if manual_override:
                stats["manual_wins"] += 1
            elif winner.tier == "incoming":
                stats["incoming_wins"] += 1
                if changed:
                    stats["incoming_overrides"] += 1
            elif winner.tier in {"verified_core", "existing_core"}:
                stats["core_wins"] += 1
                if not changed:
                    stats["core_kept"] += 1

            if changed:
                stats["fields_changed"] += 1
            else:
                stats["fields_unchanged"] += 1

            reason = "manual override" if manual_override else f"{winner.tier} selected"
            decisions.append(
                FieldDecision(
                    field_name=field_name,
                    group_name=group.name,
                    winner=winner,
                    losers=tuple(losers),
                    changed=changed,
                    manual_override=manual_override,
                    reason=reason,
                )
            )

    # Include fields not explicitly in the profile using the default tier order.
    default_tiers = profile.default_tier_order or ()
    if default_tiers:
        for field_name in incoming_payload.keys():
            if field_name in processed_fields:
                continue
            candidates = [
                _candidate_for_tier(
                    tier,
                    field_name,
                    incoming_payload=incoming_payload,
                    core_snapshot=core_snapshot,
                    manual_overrides=manual_overrides,
                    verified_snapshot=verified_snapshot,
                    incoming_provenance=incoming_provenance,
                )
                for tier in default_tiers
            ]
            winner, losers = _select_winner(
                FieldRule(field_name=field_name, tier_order=default_tiers, prefer_non_null=True, prefer_recent_verified=True),
                candidates,
            )
            resolved[field_name] = winner.value
            existing_value = core_snapshot.get(field_name)
            changed = winner.value != existing_value
            reason = f"{winner.tier} selected"
            decisions.append(
                FieldDecision(
                    field_name=field_name,
                    group_name="default",
                    winner=winner,
                    losers=tuple(losers),
                    changed=changed,
                    manual_override=winner.tier == "manual",
                    reason=reason,
                )
            )

    return SurvivorshipResult(resolved_values=dict(resolved), decisions=tuple(decisions), stats=dict(stats))


def summarize_decisions(decisions: Iterable[FieldDecision]) -> Mapping[str, Any]:
    """
    Produce a lightweight summary grouped by field group for API exposure.
    """

    summary: MutableMapping[str, MutableMapping[str, Any]] = {}
    for decision in decisions:
        group = summary.setdefault(decision.group_name, {"changed": 0, "total": 0, "manual_wins": 0, "incoming_wins": 0})
        group["total"] += 1
        if decision.changed:
            group["changed"] += 1
        if decision.manual_override:
            group["manual_wins"] += 1
        if decision.winner.tier == "incoming":
            group["incoming_wins"] += 1
    return {group: dict(values) for group, values in summary.items()}


__all__ = [
    "apply_survivorship",
    "FieldDecision",
    "FieldCandidate",
    "SurvivorshipResult",
    "summarize_decisions",
]

