"""Utilities for loading and applying adapter field mappings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
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
    Cache is invalidated if the file modification time or checksum changes.
    """

    config_path = current_app.config.get("IMPORTER_SALESFORCE_MAPPING_PATH")
    if not config_path:
        raise MappingLoadError("IMPORTER_SALESFORCE_MAPPING_PATH is not configured.")
    config_path = Path(config_path)
    cache_key = "_importer_sf_mapping_cache"
    cache: dict[str, tuple[MappingSpec, float, str]] = current_app.extensions.setdefault(cache_key, {})
    cache_key_lookup = str(config_path)
    
    # Check if we have a cached spec and if the file has changed
    cached_entry = cache.get(cache_key_lookup)
    if cached_entry:
        cached_spec, cached_mtime, cached_checksum = cached_entry
        current_mtime = config_path.stat().st_mtime
        # Reload if file modification time changed
        if current_mtime != cached_mtime:
            # File changed, reload
            current_app.logger.debug(f"Mapping file changed, reloading: {config_path}")
            spec = load_mapping(config_path)
            cache[cache_key_lookup] = (spec, current_mtime, spec.checksum)
            return spec
        # File hasn't changed, use cached spec
        return cached_spec
    
    # No cache entry, load and cache
    spec = load_mapping(config_path)
    mtime = config_path.stat().st_mtime
    cache[cache_key_lookup] = (spec, mtime, spec.checksum)
    return spec


def _compute_checksum(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# Transformer -----------------------------------------------------------------


@dataclass
class FieldImportStats:
    """Statistics for a single field during transformation."""
    source_field: str
    target_field: str | None
    records_with_value: int = 0
    records_mapped: int = 0
    records_transformed: int = 0
    records_failed_transform: int = 0
    records_used_default: int = 0
    total_records_processed: int = 0
    
    @property
    def population_rate(self) -> float:
        if self.total_records_processed == 0:
            return 0.0
        return self.records_with_value / self.total_records_processed


@dataclass
class TransformResult:
    canonical: dict[str, Any]
    unmapped_fields: dict[str, Any]
    errors: list[str]
    field_stats: dict[str, FieldImportStats] = field(default_factory=dict)


class SalesforceMappingTransformer:
    """Apply a mapping spec to Salesforce Contact payloads."""

    def __init__(self, spec: MappingSpec):
        self.spec = spec
        self.transform_registry = _build_transform_registry()

    def transform(self, payload: Mapping[str, Any]) -> TransformResult:
        canonical: dict[str, Any] = {}
        unmapped = dict(payload)
        errors: list[str] = []
        field_stats: dict[str, FieldImportStats] = {}

        for field in self.spec.fields:
            # Only track stats for fields with a source (not default-only fields)
            source_field_name = field.source
            if source_field_name:
                if source_field_name not in field_stats:
                    field_stats[source_field_name] = FieldImportStats(
                        source_field=source_field_name,
                        target_field=field.target,
                    )
                stats = field_stats[source_field_name]
                stats.total_records_processed += 1
            
            value = None
            had_value = False
            used_default = False
            transform_applied = False
            transform_failed = False
            
            if field.source:
                value = payload.get(field.source)
                unmapped.pop(field.source, None)
                if value is not None and value != "":
                    had_value = True
                    if source_field_name and source_field_name in field_stats:
                        field_stats[source_field_name].records_with_value += 1
            
            if (value is None or value == "") and field.default is not None:
                value = field.default
                used_default = True
                if source_field_name and source_field_name in field_stats:
                    field_stats[source_field_name].records_used_default += 1
            
            if field.required and (value is None or value == ""):
                errors.append(f"Required field '{field.target}' missing (source: {field.source})")
                continue
            
            if field.transform:
                transform_fn = self.transform_registry.get(field.transform)
                if transform_fn is None:
                    errors.append(f"Unknown transform '{field.transform}' for field '{field.target}'")
                    transform_failed = True
                    if source_field_name and source_field_name in field_stats:
                        field_stats[source_field_name].records_failed_transform += 1
                else:
                    try:
                        original_value = value
                        transformed_value = transform_fn(value)
                        transform_applied = True
                        if source_field_name and source_field_name in field_stats:
                            field_stats[source_field_name].records_transformed += 1
                        # For phone/email transforms, if the original value exists but transform returns None,
                        # keep the original value (might be already normalized or in unexpected format)
                        if transformed_value is None and original_value is not None and original_value != "":
                            # Transform returned None but we had a value - keep original for manual review
                            # The loader will handle normalization/validation
                            value = str(original_value).strip() if original_value else None
                        else:
                            value = transformed_value
                    except Exception as exc:  # pragma: no cover - defensive path
                        errors.append(f"Transform '{field.transform}' failed for {field.target}: {exc}")
                        transform_failed = True
                        if source_field_name and source_field_name in field_stats:
                            field_stats[source_field_name].records_failed_transform += 1
            
            # Update mapped count if field was successfully processed
            if source_field_name and source_field_name in field_stats:
                if had_value or used_default:
                    field_stats[source_field_name].records_mapped += 1
            
            # Skip only None and empty strings, but include False (boolean) values
            # Note: False is not None and False != "", so it will pass through
            # However, if we have a boolean default and the value is None/empty, we should use the default
            if value is None or value == "":
                # If we have a boolean default, use it (don't skip)
                if isinstance(field.default, bool):
                    value = field.default
                else:
                    continue
            # Normalize boolean values from Salesforce (handles both bool and string "true"/"false")
            if isinstance(field.default, bool) or isinstance(value, bool):
                if isinstance(value, str):
                    # Convert string representations to bool
                    value = value.lower() in ("true", "1", "yes", "y", "on")
                elif not isinstance(value, bool) and value is not None:
                    # Convert other types to bool if default is bool
                    value = bool(value)
            _set_nested_value(canonical, field.target, value)

        return TransformResult(
            canonical=canonical,
            unmapped_fields={key: val for key, val in unmapped.items() if val not in (None, "", [])},
            errors=errors,
            field_stats=field_stats,
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

    def split_semicolon(value: Any) -> list[str] | None:
        """Split semicolon-separated values into list."""
        if not value:
            return []
        text = str(value).strip()
        if not text:
            return []
        return [v.strip() for v in text.split(";") if v.strip()]

    return {
        "normalize_phone": normalize_phone,
        "parse_date": parse_date,
        "parse_datetime": parse_datetime,
        "split_semicolon": split_semicolon,
    }


def _set_nested_value(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value

