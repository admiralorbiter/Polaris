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


def get_active_salesforce_account_mapping() -> MappingSpec:
    """
    Load the configured Salesforce Account mapping spec (cached per app context).
    Cache is invalidated if the file modification time or checksum changes.
    """

    config_path = current_app.config.get("IMPORTER_SALESFORCE_ACCOUNT_MAPPING_PATH")
    if not config_path:
        # Default to salesforce_account_v1.yaml in config/mappings
        # Use instance_path to find project root (go up from instance/ to project root)
        instance_path = Path(current_app.instance_path)
        # instance_path is typically <project_root>/instance, so parent is project root
        config_path = (instance_path.parent / "config" / "mappings" / "salesforce_account_v1.yaml").resolve()
    else:
        config_path = Path(config_path)
    
    if not config_path.exists():
        raise MappingLoadError(f"Salesforce Account mapping file not found at {config_path}")
    
    cache_key = "_importer_sf_account_mapping_cache"
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

    def normalize_race_ethnicity(value: Any) -> str | None:
        """Normalize Salesforce racial/ethnic background values to enum values."""
        if not value:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        
        # Mapping of Salesforce values to enum values (case-insensitive)
        # Based on actual Salesforce picklist values observed
        mapping = {
            # Prefer not to answer variants
            "prefer not to answer": "prefer_not_to_say",
            "prefer not to say": "prefer_not_to_say",
            "prefer_not_to_say": "prefer_not_to_say",
            "prefer not to respond": "prefer_not_to_say",
            
            # Black/African American variants
            "black": "black_or_african_american",
            "black/african american": "black_or_african_american",
            "african american": "black_or_african_american",
            "african-american": "black_or_african_american",
            "black_or_african_american": "black_or_african_american",
            
            # White/Caucasian variants
            "white": "white",
            "caucasian": "white",
            "white/caucasian": "white",
            "white/caucasian/european american": "white",
            "european american": "white",
            
            # Asian variants
            "asian": "asian",
            "asian american": "asian",
            "asian/pacific islander": "asian",
            
            # Hispanic/Latino variants
            "hispanic": "hispanic_or_latino",
            "latino": "hispanic_or_latino",
            "latina": "hispanic_or_latino",
            "hispanic or latino": "hispanic_or_latino",
            "hispanic/latino": "hispanic_or_latino",
            "hispanic_or_latino": "hispanic_or_latino",
            
            # Native American variants
            "native american": "native_american",
            "american indian": "native_american",
            "native american/american indian": "native_american",
            "native_american": "native_american",
            
            # Pacific Islander variants
            "pacific islander": "pacific_islander",
            "pacific_islander": "pacific_islander",
            
            # Multi-racial/Bi-racial variants
            "bi-racial": "two_or_more",
            "multi-racial": "two_or_more",
            "multiracial": "two_or_more",
            "bi-racial/multi-racial/multicultural white/caucasian/european american": "two_or_more",
            "bi-racial/multi-racial": "two_or_more",
            "two or more": "two_or_more",
            "two_or_more": "two_or_more",
            "mixed": "two_or_more",
            "multicultural": "two_or_more",
            
            # Other
            "other": "other",
        }
        
        # Direct lookup
        normalized = mapping.get(text)
        if normalized:
            return normalized
        
        # Fuzzy matching for partial matches
        # Check if text contains any key phrase
        for key, enum_value in mapping.items():
            if key in text or text in key:
                return enum_value
        
        # If no match found, return None to let the loader log it
        # This will help identify new values that need mapping
        return None

    def normalize_education_level(value: Any) -> str | None:
        """Normalize Salesforce education level values to enum values."""
        if not value:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        
        # Mapping of Salesforce values to enum values (case-insensitive)
        # Based on common education level picklist values
        mapping = {
            # Less than high school variants
            "less than high school": "less_than_high_school",
            "less than hs": "less_than_high_school",
            "no high school": "less_than_high_school",
            "elementary school": "less_than_high_school",
            "middle school": "less_than_high_school",
            "less_than_high_school": "less_than_high_school",
            
            # High school variants
            "high school": "high_school",
            "high school diploma": "high_school",
            "high school graduate": "high_school",
            "hs diploma": "high_school",
            "ged": "high_school",
            "general equivalency diploma": "high_school",
            "high_school": "high_school",
            
            # Some college variants
            "some college": "some_college",
            "some college credit": "some_college",
            "college credit": "some_college",
            "attended college": "some_college",
            "some_college": "some_college",
            
            # Associate's degree variants
            "associate's": "associates",
            "associates": "associates",
            "associate degree": "associates",
            "associate's degree": "associates",
            "aa": "associates",
            "a.a.": "associates",
            "as": "associates",
            "a.s.": "associates",
            "aas": "associates",
            
            # Bachelor's degree variants
            "bachelor's": "bachelors",
            "bachelor": "bachelors",
            "bachelors": "bachelors",
            "bachelor's degree": "bachelors",
            "bachelor degree": "bachelors",
            "ba": "bachelors",
            "b.a.": "bachelors",
            "bs": "bachelors",
            "b.s.": "bachelors",
            "bsba": "bachelors",
            "bsc": "bachelors",
            
            # Master's degree variants
            "master's": "masters",
            "masters": "masters",
            "master": "masters",
            "master's degree": "masters",
            "master degree": "masters",
            "ma": "masters",
            "m.a.": "masters",
            "ms": "masters",
            "m.s.": "masters",
            "msc": "masters",
            "mba": "masters",
            
            # Doctorate variants
            "doctorate": "doctorate",
            "doctorate degree": "doctorate",
            "phd": "doctorate",
            "ph.d.": "doctorate",
            "ph.d": "doctorate",
            "d.phil": "doctorate",
            "ed.d.": "doctorate",
            "edd": "doctorate",
            "doctoral degree": "doctorate",
            
            # Professional degree variants
            "professional": "professional",
            "professional degree": "professional",
            "jd": "professional",
            "j.d.": "professional",
            "law degree": "professional",
            "md": "professional",
            "m.d.": "professional",
            "medical degree": "professional",
            
            # Other
            "other": "other",
            "not specified": "other",
            "prefer not to answer": "other",
        }
        
        # Direct lookup
        normalized = mapping.get(text)
        if normalized:
            return normalized
        
        # Fuzzy matching for partial matches
        # Check if text contains any key phrase
        for key, enum_value in mapping.items():
            if key in text or text in key:
                return enum_value
        
        # If no match found, return None to let the loader log it
        # This will help identify new values that need mapping
        return None

    def normalize_age_group(value: Any) -> str | None:
        """Normalize Salesforce age group values to AgeGroup enum values."""
        if not value:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        
        # Mapping of Salesforce values to enum values (case-insensitive)
        # AgeGroup enum values: child (0-12), teen (13-17), adult (18-64), senior (65+)
        mapping = {
            # Direct enum value matches
            "child": "child",
            "teen": "teen",
            "adult": "adult",
            "senior": "senior",
            
            # Age range formats (e.g., "60-69", "60-69 years", etc.)
            "0-12": "child",
            "0-12 years": "child",
            "under 13": "child",
            "12 and under": "child",
            
            "13-17": "teen",
            "13-17 years": "teen",
            "teenager": "teen",
            "teens": "teen",
            
            "18-64": "adult",
            "18-64 years": "adult",
            "adult": "adult",
            "adults": "adult",
            
            "65+": "senior",
            "65 and over": "senior",
            "65 and older": "senior",
            "over 65": "senior",
            "senior": "senior",
            "seniors": "senior",
            "elderly": "senior",
            
            # Specific age ranges that map to senior
            "60-69": "senior",
            "60-69 years": "senior",
            "70-79": "senior",
            "70-79 years": "senior",
            "80+": "senior",
            "80 and over": "senior",
        }
        
        # Direct lookup
        normalized = mapping.get(text)
        if normalized:
            return normalized
        
        # Try to extract numeric age ranges from text
        import re
        # Match patterns like "60-69", "18-64", "65+", etc.
        range_match = re.search(r'(\d+)\s*-\s*(\d+)', text)
        if range_match:
            start_age = int(range_match.group(1))
            end_age = int(range_match.group(2))
            # Determine age group based on range
            if end_age <= 12:
                return "child"
            elif start_age >= 13 and end_age <= 17:
                return "teen"
            elif start_age >= 18 and end_age <= 64:
                return "adult"
            elif start_age >= 65:
                return "senior"
            # For ranges that span multiple groups, use the majority or higher group
            elif start_age < 13 and end_age > 17:
                # Spans child and teen, default to teen
                return "teen"
            elif start_age < 18 and end_age > 64:
                # Spans teen and adult, default to adult
                return "adult"
            elif start_age < 65:
                # Spans adult and senior, default to senior
                return "senior"
        
        # Match patterns like "65+", "80+", etc.
        plus_match = re.search(r'(\d+)\s*\+', text)
        if plus_match:
            age = int(plus_match.group(1))
            if age >= 65:
                return "senior"
            elif age >= 18:
                return "adult"
            elif age >= 13:
                return "teen"
            else:
                return "child"
        
        # Fuzzy matching for partial matches
        for key, enum_value in mapping.items():
            if key in text or text in key:
                return enum_value
        
        # If no match found, return None to let the loader log it
        # This will help identify new values that need mapping
        return None

    def normalize_organization_type(value: Any) -> str | None:
        """Normalize Salesforce Account Type values to OrganizationType enum values."""
        if not value:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        
        # Mapping of Salesforce Account Type values to OrganizationType enum values
        # OrganizationType enum: SCHOOL, BUSINESS, NON_PROFIT, GOVERNMENT, OTHER
        mapping = {
            # School variants (but note: we filter out 'School' in the query)
            "school": "school",
            "elementary school": "school",
            "middle school": "school",
            "high school": "school",
            "school district": "school",  # Note: filtered in query but handle if present
            "educational institution": "school",
            "university": "school",
            "college": "school",
            
            # Business variants
            "business": "business",
            "company": "business",
            "corporation": "business",
            "corp": "business",
            "llc": "business",
            "partnership": "business",
            "for-profit": "business",
            "for profit": "business",
            "commercial": "business",
            
            # Non-profit variants
            "non-profit": "non_profit",
            "nonprofit": "non_profit",
            "non profit": "non_profit",
            "non_profit": "non_profit",
            "501(c)(3)": "non_profit",
            "501c3": "non_profit",
            "charity": "non_profit",
            "foundation": "non_profit",
            "ngo": "non_profit",
            
            # Government variants
            "government": "government",
            "federal": "government",
            "state": "government",
            "local government": "government",
            "municipal": "government",
            "city": "government",
            "county": "government",
            "public sector": "government",
            
            # Other (default)
            "other": "other",
            "unknown": "other",
        }
        
        # Direct lookup
        normalized = mapping.get(text)
        if normalized:
            return normalized
        
        # Fuzzy matching for partial matches
        for key, enum_value in mapping.items():
            if key in text or text in key:
                return enum_value
        
        # Default to OTHER for unmapped types
        return "other"

    return {
        "normalize_phone": normalize_phone,
        "parse_date": parse_date,
        "parse_datetime": parse_datetime,
        "split_semicolon": split_semicolon,
        "normalize_race_ethnicity": normalize_race_ethnicity,
        "normalize_education_level": normalize_education_level,
        "normalize_age_group": normalize_age_group,
        "normalize_organization_type": normalize_organization_type,
    }


def _set_nested_value(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value

