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

The complete pipeline follows an **E-L-T-L** (Extract → Load → Transform → Load) pattern:

1. **Extract**: Salesforce extractor builds SOQL (Bulk API 2.0) with watermark filtering (`SystemModstamp`) and volunteer filtering (`Contact_Type__c`). Raw records are written to `staging_volunteers` with `payload_json` containing the original Salesforce data.
2. **Transform**: Transformer applies YAML specification, creating canonical payloads (`normalized_json`) and collecting unmapped fields/errors. Records without email/phone are flagged with `metadata.missing_contact_info = True`.
3. **DQ (Data Quality)**: Minimal rules (`VOL_EMAIL_FORMAT`, `VOL_PHONE_E164`) run against canonical payloads. Missing contact info creates metadata flags by default; optional DQ warnings can be enabled via `IMPORTER_WARN_ON_MISSING_CONTACT`. Valid rows are promoted to `clean_volunteers`.
4. **Load**: `SalesforceContactLoader` performs idempotent upsert with survivorship, writing to core `volunteers` and `contacts` tables. Uses `ExternalIdMap` for tracking and watermark advancement.

### Complete Pipeline Stages

For a comprehensive understanding of how to build new mappings, here's the full pipeline breakdown:

#### Stage 1: Extract (Adapter Layer)
- **File**: `flask_app/importer/adapters/salesforce/extractor.py`
- **Purpose**: Query external system and stream raw records
- **Output**: Raw payloads written to `staging_*` tables
- **Key Components**:
  - SOQL query builder (`build_contacts_soql()`)
  - Bulk API 2.0 job execution
  - Watermark-based incremental filtering
  - Field selection (must include all fields referenced in mapping)

#### Stage 2: Stage (Staging Layer)
- **File**: `flask_app/importer/pipeline/salesforce.py`
- **Purpose**: Write raw records to staging tables for audit/replay
- **Output**: `StagingVolunteer` records with `payload_json` and `normalized_json`
- **Key Components**:
  - Mapping spec loading (`get_active_salesforce_mapping()`)
  - Transformer application (`SalesforceMappingTransformer.transform()`)
  - Batch commits for performance
  - Metadata flagging (e.g., `missing_contact_info`)

#### Stage 3: Transform (Mapping Layer)
- **File**: `flask_app/importer/mapping/__init__.py`
- **Purpose**: Convert source-specific data to canonical format
- **Input**: Raw Salesforce payload from `payload_json`
- **Output**: Canonical dictionary in `normalized_json`
- **Key Components**:
  - YAML mapping spec parsing
  - Field mapping with defaults and transforms
  - Nested structure creation
  - Error collection for missing required fields

#### Stage 4: DQ (Data Quality Layer)
- **File**: `flask_app/importer/pipeline/dq.py`
- **Purpose**: Validate canonical payloads against business rules
- **Output**: Valid rows → `clean_volunteers`, invalid rows → quarantine
- **Key Components**:
  - Rule evaluation (`EmailOrPhoneRule`, `EmailFormatRule`, etc.)
  - Severity levels (ERROR vs WARNING)
  - Quarantine vs logging decisions

#### Stage 5: Clean (Clean Layer)
- **File**: `flask_app/importer/pipeline/clean.py`
- **Purpose**: Promote validated rows to clean tables
- **Output**: `CleanVolunteer` records ready for loading
- **Key Components**:
  - DQ validation pass
  - Checksum computation for change detection
  - Load action assignment (`inserted`, `updated`, `unchanged`)

#### Stage 6: Load (Core Layer)
- **File**: `flask_app/importer/pipeline/salesforce_loader.py`
- **Purpose**: Idempotent upsert into core domain tables
- **Output**: Core `volunteer` and `contact` records
- **Key Components**:
  - `ExternalIdMap` lookup for existing records
  - Create vs update decision
  - Survivorship policy application
  - Watermark advancement
  - Contact preference application (bypasses survivorship)

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

### 3.1 Adding a New Field: Complete Workflow

When adding a new field to the pipeline, you must touch multiple stages. Here's the complete checklist:

#### Step 1: Add Field to Extractor (Extract Stage)
**File**: `flask_app/importer/adapters/salesforce/extractor.py`

Add the Salesforce field to the SOQL query:
```python
# In DEFAULT_CONTACT_FIELDS or build_contacts_soql()
"Custom_Field__c",  # Add to field list
```

**Why**: The extractor must fetch the field from Salesforce before it can be mapped.

#### Step 2: Add Mapping Entry (Transform Stage)
**File**: `config/mappings/salesforce_contact_v1.yaml`

Add the field mapping:
```yaml
- source: Custom_Field__c
  target: engagement.last_touchpoint
  # Optional:
  # required: false
  # default: null
  # transform: parse_datetime
```

**Why**: The mapping spec defines how source fields become canonical fields.

#### Step 3: Apply Field in Loader (Load Stage)
**File**: `flask_app/importer/pipeline/salesforce_loader.py`

If the field needs special handling (beyond default survivorship), update `_handle_create()` and `_handle_update()`:

```python
# In _handle_create() or _handle_update()
if "engagement" in payload:
    engagement = payload.get("engagement", {})
    if "last_touchpoint" in engagement:
        volunteer.last_touchpoint = engagement["last_touchpoint"]
```

**Why**: Some fields need custom logic (e.g., contact preferences bypass survivorship, dates need parsing, etc.).

#### Step 4: Update Core Model (If New Column Needed)
**File**: `flask_app/models/contact/base.py` or `flask_app/models/volunteer.py`

If the field doesn't exist in the core schema:
```python
# Add column to model
last_touchpoint = db.Column(db.DateTime, nullable=True)
```

**Why**: The core model must have a place to store the data.

#### Step 5: Test & Validate
1. **Dry-run**: `flask importer run-salesforce --dry-run`
2. **Check staging**: Verify `normalized_json` contains the new field
3. **Check clean**: Verify `clean_volunteers.payload_json` has the field
4. **Check core**: Verify the field appears in the final `volunteer` record
5. **Monitor metrics**: Check for unmapped fields or transform errors

#### Quick Reference: Field Addition Checklist

- [ ] Field added to extractor SOQL query
- [ ] Field mapped in YAML mapping spec
- [ ] Field applied in loader (if special handling needed)
- [ ] Core model updated (if new column needed)
- [ ] Tests updated (if applicable)
- [ ] Dry-run executed and verified
- [ ] Production import tested

### 3.1.1 Common Field Patterns

**Boolean with Default**:
```yaml
- source: DoNotCall
  target: contact_preferences.do_not_call
  default: false  # Ensures field is always present, even if Salesforce returns None
```

**Nested Structure**:
```yaml
- source: Email
  target: email.primary
- source: HomePhone
  target: phone.home
```

**Date/Datetime**:
```yaml
- source: LastModifiedDate
  target: metadata.last_modified
  transform: parse_datetime
```

**Metadata Only** (not stored in core):
```yaml
- source: EmailBouncedDate
  target: metadata.email_bounced_date
  transform: parse_datetime
# Then in loader, store in ExternalIdMap.metadata_json instead of volunteer record
```

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
- **Contact preferences**: map boolean flags to nested `contact_preferences.*` structure (e.g., `DoNotCall` → `contact_preferences.do_not_call`).
- **Dates and timestamps**: use `parse_date` for `YYYY-MM-DD`, `parse_datetime` for ISO 8601 (appends `Z` if missing timezone).
- **Lookup IDs**: map raw IDs into `metadata` or canonical references (further resolution handled downstream).
- **Multi-select picklists**: create custom transform that splits values (`value.split(';')`) into arrays.
- **Formula fields**: treat as read-only strings; transforms can parse or split values if needed.

## 4. Horizontal Scaling: Adding Salesforce Objects

While Sprint 4 implemented Contacts, the architecture supports additional objects (Campaign, CampaignMember, Event). To onboard a new object, you must implement the full pipeline.

### 4.1 Complete Workflow: Adding a New Salesforce Object

#### Step 1: Create Mapping File
**File**: `config/mappings/salesforce_<object>_v1.yaml`

1. Copy the existing mapping: `cp config/mappings/salesforce_contact_v1.yaml config/mappings/salesforce_campaign_member_v1.yaml`.
2. Update metadata:
   ```yaml
   version: 1
   adapter: salesforce
   object: CampaignMember
   ```
3. Define `fields` for the new canonical contract (e.g., `signup` entity).
4. Place file under version control. Reference via `IMPORTER_SALESFORCE_MAPPING_PATH` (per object support is a Sprint 7 goal; for now single mapping active per environment).

#### Step 2: Extend Extractor
**File**: `flask_app/importer/adapters/salesforce/extractor.py`

Add SOQL builder function:
```python
def build_campaign_member_soql(
    last_modstamp: datetime | None = None,
    limit: int | None = None,
) -> str:
    """Build SOQL query for CampaignMember objects."""
    fields = [
        "Id", "CampaignId", "ContactId", "Status",
        "SystemModstamp", "CreatedDate", "LastModifiedDate",
        # ... add all fields needed
    ]
    base_query = f"SELECT {', '.join(fields)} FROM CampaignMember"
    # Add WHERE clauses for watermark filtering
    # ...
    return base_query
```

**Why**: Each object needs its own query builder with appropriate field selection and filtering.

#### Step 3: Create Staging Table (If Needed)
**File**: `flask_app/models/importer/schema.py`

If the new object needs a different staging table:
```python
class StagingEvent(db.Model):
    __tablename__ = "staging_events"
    # Similar structure to StagingVolunteer
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("import_runs.id"), nullable=False)
    external_id = db.Column(db.String(255), nullable=False)
    external_system = db.Column(db.String(50), nullable=False)
    payload_json = db.Column(db.JSON, nullable=False)
    normalized_json = db.Column(db.JSON, nullable=True)
    # ...
```

**Why**: Staging tables store raw and normalized data per entity type.

#### Step 4: Create Ingestion Function
**File**: `flask_app/importer/pipeline/salesforce.py`

Add ingestion function:
```python
def ingest_salesforce_events(
    *,
    import_run: ImportRun,
    extractor: SalesforceExtractor,
    watermark: ImporterWatermark,
    staging_batch_size: int,
    dry_run: bool,
    logger: logging.Logger,
    record_limit: int | None = None,
) -> SalesforceIngestSummary:
    """Stream Salesforce Events into staging."""
    # Similar structure to ingest_salesforce_contacts()
    # 1. Build SOQL
    # 2. Load mapping spec
    # 3. Transform and stage records
    # 4. Return summary
```

**Why**: Each object needs its own ingestion orchestration.

#### Step 5: Create Clean Table (If Needed)
**File**: `flask_app/models/importer/schema.py`

```python
class CleanEvent(db.Model):
    __tablename__ = "clean_events"
    # Similar to CleanVolunteer
    # Links to StagingEvent
    # Stores validated canonical payloads
```

#### Step 6: Create Loader
**File**: `flask_app/importer/pipeline/salesforce_loader.py` (or new file)

```python
class SalesforceEventLoader:
    """Two-phase loader for Salesforce Events."""
    
    def __init__(self, run: ImportRun, session: Session | None = None):
        self.run = run
        self.session = session or db.session
    
    def execute(self) -> LoaderCounters:
        # 1. Snapshot clean rows
        # 2. Apply create/update/delete logic
        # 3. Use ExternalIdMap with entity_type="event"
        # 4. Advance watermark
        # 5. Return counters
```

**Why**: Each entity type needs its own loader with appropriate upsert logic.

#### Step 7: Create Core Model (If Needed)
**File**: `flask_app/models/event.py` or similar

```python
class Event(db.Model):
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    # ... core fields
```

#### Step 8: Wire Up Task
**File**: `flask_app/importer/tasks.py`

Add Celery task:
```python
@shared_task(name="importer.pipeline.ingest_salesforce_events", bind=True)
def ingest_salesforce_events(self, *, run_id: int, dry_run: bool = False) -> dict[str, Any]:
    # Orchestrate: extract → stage → DQ → clean → load
    # Similar to ingest_salesforce_contacts()
```

#### Step 9: Add CLI Command
**File**: `flask_app/importer/cli.py`

```python
@importer_cli.command("run-salesforce-events")
@click.option("--dry-run", is_flag=True)
def run_salesforce_events(dry_run: bool):
    # Create ImportRun
    # Execute task
    # Display results
```

#### Step 10: Update UI (If Needed)
**File**: `flask_app/routes/importer.py` and templates

Add UI for the new object type in the Admin Importer interface.

### 4.1.1 Quick Reference: New Object Checklist

- [ ] Mapping file created (`config/mappings/salesforce_<object>_v1.yaml`)
- [ ] Extractor function added (`build_<object>_soql()`)
- [ ] Staging table created (if new entity type)
- [ ] Ingestion function created (`ingest_salesforce_<object>()`)
- [ ] Clean table created (if new entity type)
- [ ] Loader class created (`Salesforce<Object>Loader`)
- [ ] Core model created/updated
- [ ] Celery task added
- [ ] CLI command added
- [ ] UI updated (if needed)
- [ ] Tests written
- [ ] Documentation updated

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

### 10.2 Contact Preference Fields

Contact preference fields control how volunteers can be contacted and are imported from Salesforce:

- **`do_not_call`**: Maps from Salesforce `DoNotCall` field. When `true`, indicates the volunteer should not be called.
- **`do_not_email`**: Maps from Salesforce `HasOptedOutOfEmail` field. When `true`, indicates the volunteer has opted out of email communications.
- **`do_not_contact`**: Maps from Salesforce `npsp__Do_Not_Contact__c` field (NPSP managed package). When `true`, indicates the volunteer should not be contacted via any method.

**Current behavior:**
- Imported from Salesforce during contact sync
- Stored in `contact_preferences` nested structure in normalized payload
- Applied directly to volunteer records during load phase (bypasses survivorship)
- Default to `False` if not present in Salesforce
- Incoming Salesforce values override existing values during imports

**Implementation:**
- Mapped in `config/mappings/salesforce_contact_v1.yaml` under `contact_preferences.*` targets
- Applied in `SalesforceContactLoader._handle_create()` and `_handle_update()` methods
- Stored as boolean columns on `contacts` table: `do_not_call`, `do_not_email`, `do_not_contact`

### 10.3 Email Bounce Tracking

The `EmailBouncedDate` field from Salesforce tracks when an email address bounced:

- **Source**: Salesforce `EmailBouncedDate` field (datetime)
- **Target**: `metadata.email_bounced_date` in normalized payload
- **Storage**: Stored in `ExternalIdMap.metadata_json` for audit/tracking purposes

**Current behavior:**
- Imported and parsed as datetime using `parse_datetime` transform
- Stored in metadata, not as a core field on the Contact model
- Available for tracking and reporting purposes
- Can be accessed via `ExternalIdMap.metadata_json["email_bounced_date"]`

**Implementation:**
- Mapped in `config/mappings/salesforce_contact_v1.yaml` to `metadata.email_bounced_date`
- Stored in `ExternalIdMap.metadata_json` during load phase
- Not displayed in UI by default (metadata field)

## 11. Quick Start: Adding a New Field End-to-End

This section provides a concrete example of adding a new field through the entire pipeline.

### Example: Adding `Volunteer_Skills__c` Field

**Goal**: Import volunteer skills from Salesforce and store in core database.

#### Step 1: Add to Extractor
```python
# flask_app/importer/adapters/salesforce/extractor.py
DEFAULT_CONTACT_FIELDS = [
    # ... existing fields ...
    "Volunteer_Skills__c",  # Add this
]
```

#### Step 2: Add to Mapping
```yaml
# config/mappings/salesforce_contact_v1.yaml
fields:
  # ... existing fields ...
  - source: Volunteer_Skills__c
    target: skills.volunteer_skills
    # Optional: transform if it's a multi-select picklist
    # transform: split_semicolon
```

#### Step 3: Add Transform (If Needed)
```python
# flask_app/importer/mapping/__init__.py
def _build_transform_registry() -> Dict[str, Any]:
    def split_semicolon(value: Any) -> list[str]:
        """Split semicolon-separated values into list."""
        if not value:
            return []
        return [v.strip() for v in str(value).split(';') if v.strip()]
    
    return {
        # ... existing transforms ...
        "split_semicolon": split_semicolon,
    }
```

#### Step 4: Update Core Model
```python
# flask_app/models/volunteer.py
class Volunteer(Contact):
    # ... existing fields ...
    volunteer_skills = db.Column(db.JSON, nullable=True)  # Store as JSON array
```

#### Step 5: Apply in Loader
```python
# flask_app/importer/pipeline/salesforce_loader.py
def _handle_update(self, entry, payload, payload_hash, clean_row):
    # ... existing code ...
    
    # Apply skills
    if "skills" in payload:
        skills = payload.get("skills", {})
        if "volunteer_skills" in skills:
            volunteer.volunteer_skills = skills["volunteer_skills"]
```

#### Step 6: Test
```bash
# Dry-run to verify
flask importer run-salesforce --dry-run

# Check staging records
flask importer debug-staging --run-id <id> --record <sequence>

# Verify in database
# Check staging_volunteers.normalized_json for "skills"
# Check clean_volunteers.payload_json for "skills"
# Check volunteers.volunteer_skills for final value
```

### Common Pitfalls

1. **Field not in SOQL**: If you forget Step 1, the field won't be extracted from Salesforce.
2. **Missing default**: Boolean fields should have `default: false` to ensure they're always present.
3. **Transform not registered**: If you use a transform, make sure it's in `_build_transform_registry()`.
4. **Loader not applying**: If the field needs special handling, don't forget Step 5.
5. **Cache not cleared**: After changing mapping YAML, restart the app/worker to clear cache.

## 12. References

- `config/mappings/salesforce_contact_v1.yaml` - Example mapping file
- `flask_app/importer/mapping/__init__.py` - Mapping transformer and registry
- `flask_app/importer/adapters/salesforce/extractor.py` - SOQL query builder
- `flask_app/importer/pipeline/salesforce.py` - Staging orchestration
- `flask_app/importer/pipeline/salesforce_loader.py` - Core loading logic
- `flask_app/importer/pipeline/dq.py` - Data quality rules
- `flask_app/importer/pipeline/clean.py` - Clean promotion
- `docs/data-integration-platform-tech-doc.md` - Technical deep dive
- `docs/data-integration-platform-overview.md` - High-level architecture
- `docs/sprint4-retrospective.md` - Implementation history
- `docs/importer-feature-flag.md` - Feature flag documentation
