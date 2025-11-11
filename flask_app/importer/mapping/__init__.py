"""Utilities for loading and applying adapter field mappings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

import yaml

from flask import current_app


class MappingLoadError(RuntimeError):
    """Raised when a mapping specification cannot be loaded or validated."""


@dataclass(frozen=True)
class MappingField:
    target: str
    source: str | None = None
    required: bool = False
    default: Any | None = None
    transform: str | None = None


@dataclass(frozen=True)
class MappingTransform:
    name: str
    description: str | None = None


@dataclass(frozen=True)
class MappingSpec:
    version: int
    adapter: str
    object_name: str
    fields: Sequence[MappingField]
    transforms: Mapping[str, MappingTransform]
    checksum: str
    path: Path


def load_mapping(path: str | Path) -> MappingSpec:
    """
    Load and validate a YAML mapping specification.
    """

    path = Path(path)
    if not path.exists():
        raise MappingLoadError(f"Mapping file not found at {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - YAML parser errors
        raise MappingLoadError(f"Failed to parse mapping YAML at {path}: {exc}") from exc

    try:
        version = int(raw["version"])
        adapter = str(raw["adapter"]).strip()
        object_name = str(raw.get("object", "")).strip() or "Contact"
        fields_payload = raw["fields"]
    except KeyError as exc:
        raise MappingLoadError(f"Missing required mapping attribute: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise MappingLoadError(f"Invalid mapping attribute: {exc}") from exc

    if not adapter:
        raise MappingLoadError("Mapping adapter value cannot be empty.")

    fields: list[MappingField] = []
    seen_targets: set[str] = set()
    for entry in fields_payload:
        if not isinstance(entry, Mapping):
            raise MappingLoadError(f"Field definition must be a mapping, got {entry!r}")
        source = entry.get("source")
        target = entry.get("target")
        if not target:
            raise MappingLoadError(f"Field entry missing 'target': {entry!r}")
        target = str(target).strip()
        if target in seen_targets:
            raise MappingLoadError(f"Duplicate target '{target}' in mapping.")
        seen_targets.add(target)
        required = bool(entry.get("required", False))
        transform = entry.get("transform")
        default = entry.get("default")
        field = MappingField(
            source=str(source).strip() if source else None,
            target=target,
            required=required,
            default=default,
            transform=str(transform).strip() if transform else None,
        )
        if field.source is None and field.default is None:
            raise MappingLoadError(f"Field '{target}' requires either source or default.")
        fields.append(field)

    transforms_payload = raw.get("transforms", {})
    transforms: dict[str, MappingTransform] = {}
    for name, details in transforms_payload.items():
        if not name:
            raise MappingLoadError("Transform definition missing name.")
        description = None
        if isinstance(details, Mapping):
            description = details.get("description")
        transforms[str(name)] = MappingTransform(name=str(name), description=description)

    checksum = _compute_checksum(raw)
    return MappingSpec(
        version=version,
        adapter=adapter,
        object_name=object_name,
        fields=tuple(fields),
        transforms=transforms,
        checksum=checksum,
        path=path,
    )


def get_active_salesforce_mapping() -> MappingSpec:
    """
    Load the configured Salesforce mapping spec (cached per app context).
    """

    config_path = current_app.config.get("IMPORTER_SALESFORCE_MAPPING_PATH")
    if not config_path:
        raise MappingLoadError("IMPORTER_SALESFORCE_MAPPING_PATH is not configured.")
    cache_key = "_importer_sf_mapping_cache"
    cache: dict[str, MappingSpec] = current_app.extensions.setdefault(cache_key, {})
    cache_key_lookup = str(config_path)
    spec = cache.get(cache_key_lookup)
    if spec is None:
        spec = load_mapping(config_path)
        cache[cache_key_lookup] = spec
    return spec


def _compute_checksum(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# Transformer -----------------------------------------------------------------


@dataclass
class TransformResult:
    canonical: dict[str, Any]
    unmapped_fields: dict[str, Any]
    errors: list[str]


class SalesforceMappingTransformer:
    """Apply a mapping spec to Salesforce Contact payloads."""

    def __init__(self, spec: MappingSpec):
        self.spec = spec
        self.transform_registry = _build_transform_registry()

    def transform(self, payload: Mapping[str, Any]) -> TransformResult:
        canonical: dict[str, Any] = {}
        unmapped = dict(payload)
        errors: list[str] = []

        for field in self.spec.fields:
            value = None
            if field.source:
                value = payload.get(field.source)
                unmapped.pop(field.source, None)
            if (value is None or value == "") and field.default is not None:
                value = field.default
            if field.required and (value is None or value == ""):
                errors.append(f"Required field '{field.target}' missing (source: {field.source})")
                continue
            if field.transform:
                transform_fn = self.transform_registry.get(field.transform)
                if transform_fn is None:
                    errors.append(f"Unknown transform '{field.transform}' for field '{field.target}'")
                else:
                    try:
                        value = transform_fn(value)
                    except Exception as exc:  # pragma: no cover - defensive path
                        errors.append(f"Transform '{field.transform}' failed for {field.target}: {exc}")
            if value is None or value == "":
                continue
            _set_nested_value(canonical, field.target, value)

        return TransformResult(
            canonical=canonical,
            unmapped_fields={key: val for key, val in unmapped.items() if val not in (None, "", [])},
            errors=errors,
        )


def _build_transform_registry() -> Dict[str, Any]:
    from flask_app.importer.pipeline.deterministic import normalize_phone

    def parse_date(value: Any) -> Any:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return text[:10]
        except Exception:
            return text

    def parse_datetime(value: Any) -> Any:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            return text
        if "+" in text:
            return text
        return f"{text}Z"

    return {
        "normalize_phone": normalize_phone,
        "parse_date": parse_date,
        "parse_datetime": parse_datetime,
    }


def _set_nested_value(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value

