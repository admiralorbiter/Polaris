# Salesforce Mapping Expansion Guide

This guide explains how Polaris maps Salesforce data into the importer pipeline and how to extend that mapping both **vertically** (new fields, transforms, and patterns) and **horizontally** (new Salesforce objects). It is intended for developers and operators working on Sprint 4+ deliverables, with an eye toward Sprint 7 mapping versioning and Sprint 8 multi-entity imports.

## 1. Architecture Overview

- **Source of truth**: YAML mapping specs under `config/mappings/` (e.g. `config/mappings/salesforce_contact_v1.yaml`).
- **Loader/validator**: `flask_app/importer/mapping/__init__.py`
  - `MappingSpec` – parsed mapping metadata (adapter, object, version, checksum).
  - `SalesforceMappingTransformer` – applies the mapping to a Salesforce payload and produces canonical dictionaries.
  - `_build_transform_registry()` – registers transform functions used by the mapping spec.
- **Pipeline integration**:
  - `flask_app/importer/adapters/salesforce/extractor.py` executes Bulk API SOQL jobs and streams rows.
  - `flask_app/importer/pipeline/salesforce.py` loads the mapping, transforms rows, and stages them (`StagingVolunteer`).
  - `flask_app/importer/pipeline/salesforce_loader.py` promotes clean rows into core via the two-phase loader.
- **Configuration**: `IMPORTER_SALESFORCE_MAPPING_PATH` controls the active mapping file. Overridable per environment.
- **Observability**:
  - Mapping checksum + version are stored on `ImportRun` metadata.
  - Unmapped fields tracked via `importer_salesforce_mapping_unmapped_total{field}` metric and run `metrics_json`.
  - Admin → Imports page exposes mapping version and download link.

### Data Flow

1. **Extract**: Salesforce extractor builds SOQL (Bulk API 2.0) with watermark filtering (`SystemModstamp`) and volunteer filtering (`Contact_Type__c`).
2. **Transform**: Transformer applies YAML specification, creating canonical payloads (`normalized_json`) and collecting unmapped fields/errors. Records without email/phone are flagged with `metadata.missing_contact_info = True`.
3. **DQ**: Minimal rules (`VOL_EMAIL_FORMAT`, `VOL_PHONE_E164`) run against canonical payloads. Missing contact info creates metadata flags by default; optional DQ warnings can be enabled via `IMPORTER_WARN_ON_MISSING_CONTACT`.
4. **Clean/Load**: Valid rows promote into `clean_volunteers`, then `SalesforceContactLoader` performs idempotent upsert with survivorship.

## 2. Mapping File Structure Reference

A mapping file is a YAML document with three top-level sections: metadata, `fields`, and optional `transforms`.

```yaml
version: 1
adapter: salesforce
object: Contact
fields:
  - source: Id
    target: external_id
    required: true
  - source: Email
    target: email.primary
  - target: metadata.source_system
    default: salesforce
transforms:
  normalize_phone:
    description: Normalize phone numbers to E.164 where possible.
```

### 2.1 Metadata

- `version` – positive integer. Increment on breaking changes (see §8).
- `adapter` – must be `salesforce` for Salesforce mappings.
- `object` – Salesforce object API name (e.g. `Contact`, `CampaignMember`). Defaults to `Contact` if omitted, but we recommend specifying explicitly.

### 2.2 Field Definitions

Each `fields` entry defines how to populate a canonical field:

| Attribute  | Description |
|------------|-------------|
| `source`   | Salesforce field API name (case-sensitive). Optional if `default` present. |
| `target`   | Canonical field path (dot-notation for nested dicts). Required. |
| `required` | If true, missing/blank values raise transformer error (row still processed but error recorded). |
| `default`  | Fallback value used when `source` missing or blank. |
| `transform`| Name of transform function (registered in `_build_transform_registry()`). Optional. |

#### Nested Targets

- Use dot notation to build nested dicts (e.g. `email.primary`, `phone.mobile`, `metadata.source_modstamp`).
- `_set_nested_value()` ensures missing intermediate objects are created on demand.

#### Required Fields

- `required: true` ensures presence **after** defaulting and transforms.
- Errors are appended to the transform result; DQ stage can act on them (e.g., missing `external_id`).

#### Default Values

- Provide canonical defaults (`metadata.source_system`, `metadata.source_object`).
- Defaults run after reading the source value but before transforms.

### 2.3 Transform Declarations

- `transforms` section documents the transform alias (`normalize_phone`) with optional description.
- The actual implementation resides in `_build_transform_registry()` (see §3.2).

## 3. Vertical Scaling: Adding Fields & Transforms

### 3.1 Adding a New Field

1. **Locate mapping**: open `config/mappings/salesforce_contact_v1.yaml` (or relevant file configured via `IMPORTER_SALESFORCE_MAPPING_PATH`).
2. **Add field entry**:
   ```yaml
   - source: Custom_Field__c
     target: engagement.last_touchpoint
   ```
3. **Optional**: specify `required`, `default`, or `transform` as needed.
4. **Update tests**: extend fixtures or unit tests in `tests/test_salesforce_mapping_transformer.py` if coverage needed.
5. **Dry-run**: execute `flask importer run-salesforce --dry-run` with sample data to verify mapping.
6. **Monitor**: validate run metrics for unmapped fields or transform errors.

### 3.2 Creating Custom Transforms

#### Implement Transform Function

- Add logic inside `_build_transform_registry()` in `flask_app/importer/mapping/__init__.py`.
- Functions should accept a single value and return transformed output (or `None` to omit field).
- Handle null/blank inputs defensively; log or raise for unrecoverable conditions.

Example: picklist normalization.

```python
def _build_transform_registry() -> Dict[str, Any]:
    from flask_app.importer.pipeline.deterministic import normalize_phone

    def map_picklist(value: Any) -> Any:
        if not value:
            return None
        lookup = {
            "Volunteer": "volunteer",
            "Student": "student",
        }
        return lookup.get(str(value).strip(), "other")

    registry = {
        "normalize_phone": normalize_phone,
        "parse_date": parse_date,
        "parse_datetime": parse_datetime,
        "map_picklist": map_picklist,
    }
    return registry
```

#### Guidelines

- **Pure functions**: avoid DB access or network calls inside transforms; transforms run for every row.
- **Error handling**: catch and handle exceptions; the transformer records errors but continues processing other fields.
- **Documentation**: add a descriptive entry under `transforms:` in the YAML spec.
- **Reusability**: prefer generic names (e.g., `normalize_postal_code`) so multiple fields can share logic.

### 3.3 Common Mapping Patterns

- **Nested contact info**: `email.primary`, `email.home`, `phone.mobile`, `phone.primary`.
- **Preferred type fields**: map picklists to `email.preferred_type` or `phone.preferred_type` to inform UI.
- **Dates and timestamps**: use `parse_date` for `YYYY-MM-DD`, `parse_datetime` for ISO 8601 (appends `Z` if missing timezone).
- **Lookup IDs**: map raw IDs into `metadata` or canonical references (further resolution handled downstream).
- **Multi-select picklists**: create custom transform that splits values (`value.split(';')`) into arrays.
- **Formula fields**: treat as read-only strings; transforms can parse or split values if needed.

## 4. Horizontal Scaling: Adding Salesforce Objects

While Sprint 4 implemented Contacts, the architecture supports additional objects (Campaign, CampaignMember, Event). To onboard a new object:

### 4.1 Create Mapping File

1. Copy the existing mapping: `cp config/mappings/salesforce_contact_v1.yaml config/mappings/salesforce_campaign_member_v1.yaml`.
2. Update metadata:
   ```yaml
   version: 1
   adapter: salesforce
   object: CampaignMember
   ```
3. Define `fields` for the new canonical contract (e.g., `signup` entity).
4. Place file under version control. Reference via `IMPORTER_SALESFORCE_MAPPING_PATH` (per object support is a Sprint 7 goal; for now single mapping active per environment).

### 4.2 Extend Extractor

- Add `build_<object>_soql()` helper in `flask_app/importer/adapters/salesforce/extractor.py`.
- Include necessary fields in the SELECT clause; use `SystemModstamp` or other timestamp for incremental filtering.
- Ensure the new helper follows the same pattern (ordering, limit support).

### 4.3 Stage Rows

- Add `ingest_salesforce_<object>()` function in `flask_app/importer/pipeline/salesforce.py`.
- Load mapping using `get_active_salesforce_mapping()` (Sprint 7 will generalize to `get_salesforce_mapping(object_name)`).
- Transform each payload; stage into appropriate table:
  - For volunteers: `StagingVolunteer`.
  - Future entities: define `StagingEvent`, `StagingSignup`, etc. (see Sprint 8 backlog).
- Track unmapped fields and transform errors per run.

### 4.4 Load into Core

- Implement a loader similar to `SalesforceContactLoader` but targeting the appropriate domain model (e.g., `Event`, `EventVolunteer`).
- Follow the two-phase commit approach:
  1. Snapshot clean rows.
  2. Apply create/update/delete logic with idempotency using `ExternalIdMap` (`entity_type` distinguishes objects).
  3. Advance watermark only after successful commit.
- Update run counters (`rows_created`, `rows_updated`, `rows_deleted`, `rows_unchanged`).

### 4.5 Wire Up Tasks & UI

- Add Celery task entry in `flask_app/importer/tasks.py` to orchestrate extract → stage → load for the new object.
- Expose CLI command (`flask importer run-salesforce --object campaign-member`).
- Update Admin Importer UI to surface the new object (toggle, mapping link, status cards).
- Ensure `ImporterWatermark` stores per-object cursors (`adapter="salesforce"`, `object_name="campaign_members"`).

### 4.6 Considerations

- **Canonical contracts**: align with ingest contract definitions (e.g., `SignupIngest`).
- **Staging schema**: design new staging/clean tables mirroring volunteer flow.
- **DQ rules**: extend rule sets per entity (reference Sprint 8 backlog for cross-entity DQ).
- **External ID map**: use consistent `entity_type` naming scheme (`volunteer`, `event`, `signup`).

## 5. Advanced Patterns

### 5.1 Conditional Mappings

- Use transforms to encode conditional logic (e.g., map `Preferred_Email__c` to `email.preferred_type` only when value present).
- For complex branching, create custom transform that returns a dict and update canonical payload inside the transform.

### 5.2 Combining Fields

- Combine first/last names for derived fields (if needed) via a transform: `combine_names` returning `"{first} {last}"`.
- For addresses, group components into nested dicts or use transforms to call normalization services (future enhancement).

### 5.3 Handling Managed Package Fields

- Managed packages add namespace prefixes (e.g., `npsp__`). Treat them like standard fields; ensure field name matches API case.
- Document field sources in YAML comments for clarity.

### 5.4 Performance Tips

- Include only necessary fields in SOQL to reduce payload size.
- Avoid heavy string manipulations in transforms (pre-compile regex if needed).
- Batch size controlled via `IMPORTER_SALESFORCE_BATCH_SIZE` (default `5000`). Monitor run duration metrics when adjusting.
- Mapping spec cached per Flask app context—changing file requires app restart or cache invalidation.

## 6. Testing & Validation

### 6.1 Unit Tests

- `tests/test_salesforce_mapping_loader.py` verifies YAML loading behavior.
- `tests/test_salesforce_mapping_transformer.py` covers field mapping semantics.
- Add new tests for custom transforms to prevent regressions.

### 6.2 Integration Tests

- Salesforce pipeline tests simulate Bulk batches and ensure staging rows persist normalized payloads.
- Extend tests with golden dataset scenarios for new fields/objects.

### 6.3 Manual Validation Checklist

1. Mapping loads via `flask importer mappings show`.
2. Dry-run import completes; inspect `metrics_json` for unmapped fields/errors.
3. DQ violations align with expectations (no false positives due to mapping issues).
4. Core loader inserts/updates the correct records; check `ImportRun.counts_json` for `rows_created` vs `rows_updated`.
5. Monitor Prometheus counters for mapping errors and staging counts.

## 7. Troubleshooting

| Symptom | Possible Causes | Mitigations |
|---------|-----------------|-------------|
| Mapping file fails to load | `IMPORTER_SALESFORCE_MAPPING_PATH` misconfigured; YAML syntax error | Verify env var; run `yamllint`; check app logs for `MappingLoadError`. |
| Transform error in run summary | Missing transform registration; transform raising exception | Ensure transform name matches registry; wrap logic in try/except; add logging. |
| High unmapped field count | Salesforce schema drift; typos in field names | Inspect `metrics_json["salesforce"]["unmapped_fields"]`; add mappings; coordinate with schema owners. |
| Required field missing | Source data null; incorrect field path | Revisit `required` flag; consider defaults; confirm Salesforce field is populated. |
| Nested fields missing in canonical payload | Incorrect target path (typo); transform returning `None` | Validate via staging `normalized_json`; adjust path or transform. |

### Debugging Tips

- Inspect individual staging rows: `flask importer debug-staging --run-id <id> --record <sequence>`.
- Dump full mapping: `flask importer mappings show > /tmp/sf_mapping.yaml`.
- Re-run specific step: `flask importer run-salesforce --run-id <existing> --inline` (for development).
- Collect metrics snapshot via `/importer/runs/<id>` API.

## 8. Versioning & Migration

### 8.1 When to Bump Version

- **Breaking changes** (rename/remove targets, altered semantics) ⇒ increment `version` and publish new YAML (`_v2`).
- **Additive changes** (new optional fields, new transforms) ⇒ can stay on current version but update checksum.

### 8.2 Migration Workflow

1. Draft new mapping file (`salesforce_contact_v2.yaml`).
2. Run unit/integration tests; update golden datasets.
3. Deploy new file; update `IMPORTER_SALESFORCE_MAPPING_PATH` via config management.
4. Perform dry-run; monitor metrics, DQ, and loaders.
5. If issues arise, rollback by pointing env var back to previous file.

### 8.3 Audit & Observability

- Mapping checksum recorded on `ImportRun`; use this to verify which version processed each run.
- Admin UI should display mapping version (ensure string surfaced via API).
- Document changes in git history and commit messages for traceability.

## 9. Roadmap Alignment

- **Sprint 5**: Focus on fuzzy dedupe & merge UI, but mapping guide supports ongoing refinements.
- **Sprint 7**: Versioned mappings, config UI, backfills—this guide aligns with upcoming work.
- **Sprint 8**: Events/Signups ingestion—horizontal scaling section prepares engineering teams.

## 10. Field-Specific Notes

### 10.1 `is_local` Field

The `is_local` field on volunteers uses a `LocalStatus` enum with the following values:

- **UNKNOWN** (default): Status is not yet determined. This is the default for newly imported volunteers.
- **LOCAL**: Volunteer is in the local area and can volunteer/do work in person.
- **NON_LOCAL**: Volunteer is not in the local area.

**Current behavior:**
- Not currently imported from Salesforce (defaults to `UNKNOWN`)
- Can be manually set via volunteer forms/UI
- Future plans include determining this automatically based on:
  - Address/postal code analysis
  - Geographic proximity to organization locations
  - Other location-based signals

**Implementation:**
- Defined in `flask_app/models/contact/enums.py` as `LocalStatus` enum
- Stored in `contacts.is_local` column as enum type
- Default value is `LocalStatus.UNKNOWN`

## 11. References

- `config/mappings/salesforce_contact_v1.yaml`
- `flask_app/importer/mapping/__init__.py`
- `flask_app/importer/adapters/salesforce/extractor.py`
- `flask_app/importer/pipeline/salesforce.py`
- `flask_app/importer/pipeline/salesforce_loader.py`
- `docs/data-integration-platform-tech-doc.md`
- `docs/sprint4-retrospective.md`
- `docs/importer-feature-flag.md`
