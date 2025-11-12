# Salesforce Transform Reference

This reference lists the transform functions available to Salesforce mappings, outlines how to add new transforms, and captures patterns for common data normalization tasks. Use it alongside `docs/salesforce-mapping-guide.md` when extending the importer.

## 1. Built-in Transforms

The default registry is defined in `flask_app/importer/mapping/__init__.py::_build_transform_registry()`.

### 1.1 `normalize_phone`
- **Source**: `flask_app/importer.pipeline.deterministic.normalize_phone`
- **Purpose**: Convert phone numbers into E.164 format (country-aware when possible).
- **Usage**: Apply to any Salesforce phone field (`Phone`, `MobilePhone`, `npe01__WorkPhone__c`).
- **Behavior**:
  - Strips non-numeric characters.
  - Applies default country if config specifies one.
  - Returns `None` when value cannot be normalized.

### 1.2 `parse_date`
- **Purpose**: Normalize Salesforce date values (`YYYY-MM-DD`).
- **Usage**: Birthdate, custom date fields.
- **Behavior**: Trims to first 10 characters; returns `None` for blank values.

### 1.3 `parse_datetime`
- **Purpose**: Normalize Salesforce datetime values.
- **Usage**: `SystemModstamp`, `LastModifiedDate`, timestamp fields.
- **Behavior**:
  - Strips whitespace.
  - Ensures string ends with `Z` or explicit offset.
  - Returns `None` for blank values.

## 2. Adding Custom Transforms

Transforms are Python callables registered by name. They are invoked by the transformer when a field entry references the `transform:` attribute.

### 2.1 Function Contract

```python
def transform_name(value: Any) -> Any:
    """Describe what the transform does."""
    if not value:
        return None
    # Transform logic here
    return transformed_value
```

- Accept a single value argument (the raw `source` output or default).
- Return the transformed value or `None` to skip the field.
- Raise only when the failure is exceptional; the transformer captures exceptions and records them as mapping errors.

### 2.2 Registration

Add your transform to the registry dictionary:

```python
def _build_transform_registry() -> Dict[str, Any]:
    from flask_app.importer.pipeline.deterministic import normalize_phone

    def normalize_picklist(value: Any) -> Any:
        if not value:
            return None
        mapping = {
            "Volunteer": "volunteer",
            "Student": "student",
        }
        return mapping.get(str(value).strip(), "other")

    return {
        "normalize_phone": normalize_phone,
        "parse_date": parse_date,
        "parse_datetime": parse_datetime,
        "normalize_picklist": normalize_picklist,
    }
```

Finally, document the transform in the YAML file under `transforms:`:

```yaml
transforms:
  normalize_picklist:
    description: Map Salesforce engagement types to canonical values.
```

### 2.3 Testing

- Add unit tests for new transforms (see `tests/test_salesforce_mapping_transformer.py`).
- Include failure cases (blank input, malformed values).
- Consider adding integration coverage if transform shapes downstream behavior.

## 3. Common Patterns

### 3.1 Picklist Normalization

```python
def normalize_picklist(value: Any) -> Any:
    if not value:
        return None
    lookup = {
        "Volunteer": "volunteer",
        "Staff": "staff",
    }
    return lookup.get(str(value).strip(), "other")
```

Use for preferred email/phone types, role designations, or any categorical field requiring canonical values.

### 3.2 Multi-select Picklists

```python
def split_multi_select(value: Any) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in str(value).split(";") if item.strip()]
```

Stores results as arrays (`list[str]`) in canonical payloads.

### 3.3 Boolean Conversion

```python
def to_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    truthy = {"true", "1", "yes", "y"}
    return str(value).strip().lower() in truthy
```

Apply this transform to Salesforce checkbox fields when canonical model expects booleans.

### 3.4 String Sanitization

```python
def strip_and_collapse(value: Any) -> str | None:
    if not value:
        return None
    return " ".join(str(value).split())
```

Useful for trimming whitespace and normalizing spacing in names or titles.

### 3.5 Lookup Resolution (Lightweight)

```python
def resolve_account_name(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    return {"account_id": value}
```

Transforms can emit dictionaries; `_set_nested_value()` handles nested structures. For complex lookups (fetching related records), prefer downstream services or preprocessing.

## 4. Best Practices

- Keep transforms pure and fast – they run for every row.
- Share transforms across fields instead of duplicating logic.
- Handle unexpected formats gracefully; return `None` rather than raising when appropriate.
- Document transforms clearly in YAML for operators.
- Log warnings for data anomalies to aid debugging.

## 5. References

- `flask_app/importer/mapping/__init__.py`
- `docs/salesforce-mapping-guide.md`
- `docs/salesforce-mapping-examples.md`
- `tests/test_salesforce_mapping_transformer.py`
