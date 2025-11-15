# Adding New Entity Types to the Importer

This guide documents the process and learnings from adding Organization (Account) and Event (Session) imports to the Polaris importer. Use this as a reference when adding new entity types (Signups, etc.) to the system.

## Overview

The importer follows an **E-L-T-L** (Extract → Load → Transform → Load) pattern that is consistent across all entity types. This guide walks through the complete implementation process using Organizations as a concrete example. Events (Sessions) have also been implemented and follow the same pattern.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Implementation Checklist](#implementation-checklist)
3. [Step-by-Step Implementation](#step-by-step-implementation)
4. [Key Learnings](#key-learnings)
5. [Common Pitfalls](#common-pitfalls)
6. [Testing Strategy](#testing-strategy)

## Architecture Overview

### Data Flow

```
Salesforce → Extract → Stage → Transform → DQ → Clean → Load → Core Tables
```

1. **Extract**: Query Salesforce and stream raw records
2. **Stage**: Write raw and normalized records to staging tables
3. **Transform**: Apply YAML mapping to convert to canonical format
4. **DQ**: Validate canonical payloads against business rules
5. **Clean**: Promote validated rows to clean tables
6. **Load**: Idempotent upsert into core domain tables

### Database Schema Layers

- **Staging Layer**: `staging_<entity_type>` - Raw and normalized payloads
- **Clean Layer**: `clean_<entity_type>` - Validated canonical payloads
- **Core Layer**: Domain models (e.g., `organizations`, `volunteers`)

### Key Components

- **Extractor**: Builds SOQL queries and streams batches
- **Mapping Transformer**: Applies YAML mapping specs
- **DQ Rules**: Validates canonical payloads
- **Loader**: Idempotent upsert with ExternalIdMap tracking
- **Watermark**: Tracks incremental import state

## Implementation Checklist

Use this checklist when adding a new entity type:

- [ ] **Mapping File**: Create YAML mapping spec
- [ ] **Extractor**: Add SOQL query builder function
- [ ] **Staging Model**: Create `Staging<EntityType>` model
- [ ] **Ingestion Function**: Add `ingest_salesforce_<entity>()` function
- [ ] **Transform Function**: Add entity-specific transforms (if needed)
- [ ] **DQ Rules**: Add entity-specific DQ rules
- [ ] **Clean Model**: Create `Clean<EntityType>` model
- [ ] **Clean Promotion**: Add `promote_clean_<entity>()` function
- [ ] **Loader**: Create `Salesforce<EntityType>Loader` class
- [ ] **Celery Task**: Add `ingest_salesforce_<entity>` task
- [ ] **CLI Support**: Update CLI to support new entity type
- [ ] **UI Updates**: Add entity type selector to admin UI
- [ ] **Tests**: Write comprehensive test suite
- [ ] **Documentation**: Update mapping guide and field summaries

## Step-by-Step Implementation

### Step 1: Create Mapping File

**File**: `config/mappings/salesforce_<object>_v1.yaml`

**Example** (Organizations):
```yaml
version: 1
adapter: salesforce
object: Account
fields:
  - source: Id
    target: external_id
    required: true
  - source: Name
    target: name
    required: true
  - source: Type
    target: organization_type
    transform: normalize_organization_type
  - source: Description
    target: description
  - source: LastActivityDate
    target: metadata.last_activity_date
    transform: parse_date
  - source: SystemModstamp
    target: metadata.source_modstamp
    transform: parse_datetime
  - target: metadata.source_system
    default: salesforce
  - target: metadata.source_object
    default: Account
transforms:
  normalize_organization_type:
    description: Normalize Salesforce Account Type values to OrganizationType enum values.
```

**Key Points**:
- Always include `external_id` (required) for idempotency
- Include `SystemModstamp` and `LastModifiedDate` for watermarking
- Add metadata fields (`source_system`, `source_object`) as defaults
- Document transforms in the `transforms` section

### Step 2: Add Extractor Function

**File**: `flask_app/importer/adapters/salesforce/extractor.py`

**Example** (Organizations):
```python
DEFAULT_ACCOUNT_FIELDS = [
    "Id",
    "Name",
    "Type",
    "Description",
    "LastActivityDate",
    "SystemModstamp",
    "LastModifiedDate",
]

def build_accounts_soql(
    *,
    fields: Sequence[str] | None = None,
    last_modstamp: datetime | None = None,
    limit: int | None = None,
) -> str:
    """Construct the SOQL used for incremental Account exports."""
    field_list = tuple(dict.fromkeys(fields or DEFAULT_ACCOUNT_FIELDS))
    select_clause = ", ".join(field_list)
    where_clauses: List[str] = []

    # Add filtering logic (e.g., exclude certain types)
    where_clauses.append("Type NOT IN ('Household', 'School District', 'School')")

    if last_modstamp is not None:
        where_clauses.append(f"SystemModstamp > {_format_modstamp(last_modstamp)}")

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    limit_sql = f" LIMIT {int(limit)}" if limit is not None else ""
    order_sql = " ORDER BY Name ASC"
    return f"SELECT {select_clause} FROM Account{where_sql}{order_sql}{limit_sql}"
```

**Key Points**:
- Include all fields referenced in the mapping file
- Always include `SystemModstamp` for watermarking
- Add appropriate WHERE clauses for filtering
- Use consistent ordering (e.g., by Name)

### Step 3: Create Staging Model

**File**: `flask_app/models/importer/schema.py`

**Example** (Organizations):
```python
class StagingOrganization(BaseModel):
    __tablename__ = "staging_organizations"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    normalized_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    status: Mapped[StagingRecordStatus] = mapped_column(
        Enum(StagingRecordStatus, name="staging_organization_status_enum"),
        default=StagingRecordStatus.LANDED,
        nullable=False,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    landed_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    processed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))

    import_run = relationship("ImportRun", back_populates="staging_organizations")
    dq_violations = relationship(
        "DataQualityViolation",
        back_populates="staging_organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    clean_record = relationship(
        "CleanOrganization",
        back_populates="staging_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    import_skips = relationship(
        "ImportSkip",
        back_populates="staging_organization",
        primaryjoin="StagingOrganization.id == ImportSkip.staging_organization_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index(
            "idx_staging_organizations_external_key",
            "external_system",
            "external_id",
        ),
        UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_staging_organizations_run_sequence",
        ),
    )
```

**Key Points**:
- Follow the same structure as `StagingVolunteer`
- Add relationships to `ImportRun`, `DataQualityViolation`, `Clean<EntityType>`, and `ImportSkip`
- **Important**: Use `primaryjoin` for `import_skips` relationship if `ImportSkip` has multiple foreign keys
- Add indexes on `external_system`/`external_id` for lookups
- Add unique constraint on `run_id`/`sequence_number`

### Step 4: Add Ingestion Function

**File**: `flask_app/importer/pipeline/salesforce.py`

**Example** (Organizations):
```python
def ingest_salesforce_accounts(
    *,
    import_run: ImportRun,
    extractor: SalesforceExtractor,
    watermark: ImporterWatermark,
    staging_batch_size: int,
    dry_run: bool,
    logger: logging.Logger,
    record_limit: int | None = None,
) -> SalesforceIngestSummary:
    """Stream Salesforce Accounts into staging and update watermark metadata."""

    last_modstamp = watermark.last_successful_modstamp
    if last_modstamp is not None and last_modstamp.tzinfo is None:
        last_modstamp = last_modstamp.replace(tzinfo=timezone.utc)

    soql = build_accounts_soql(last_modstamp=last_modstamp, limit=record_limit)
    mapping_spec = get_active_salesforce_account_mapping()
    transformer = SalesforceMappingTransformer(mapping_spec)

    # Process batches, transform, and stage records
    # ... (see full implementation in codebase)
```

**Key Points**:
- Load the entity-specific mapping using `get_active_salesforce_<entity>_mapping()`
- Handle timezone-aware datetime comparisons
- Track field statistics and unmapped fields
- Update watermark after successful staging

### Step 5: Add Transform Functions

**File**: `flask_app/importer/mapping/__init__.py`

**Example** (Organizations):
```python
def normalize_organization_type(value: Any) -> str | None:
    """Normalize Salesforce Account Type values to OrganizationType enum values."""
    if not value:
        return None
    text = str(value).strip().lower()
    if not text:
        return None

    mapping = {
        "business": "business",
        "non-profit": "non_profit",
        "nonprofit": "non_profit",
        "government": "government",
        # ... more mappings
    }

    normalized = mapping.get(text)
    if normalized:
        return normalized

    # Fuzzy matching for partial matches
    for key, enum_value in mapping.items():
        if key in text or text in key:
            return enum_value

    return "other"  # Default

def _build_transform_registry() -> Dict[str, Any]:
    return {
        # ... existing transforms ...
        "normalize_organization_type": normalize_organization_type,
    }
```

**Key Points**:
- Handle None/empty values defensively
- Use case-insensitive matching
- Provide sensible defaults
- Document in mapping YAML file

### Step 6: Add DQ Rules

**File**: `flask_app/importer/pipeline/dq.py`

**Example** (Organizations):
```python
class OrganizationNameRequiredRule(DQRule):
    """Organization name is required."""

    code = "ORG_NAME_REQUIRED"
    severity = DQSeverity.ERROR

    def evaluate(self, payload: MutableMapping[str, object | None]) -> DQResult | None:
        name = payload.get("name")
        if not name or not str(name).strip():
            return DQResult(
                rule_code=self.code,
                severity=self.severity,
                message="Organization name is required",
            )
        return None

def evaluate_organization_rules(
    payload: MutableMapping[str, object | None],
) -> Iterable[DQResult]:
    """Apply organization-specific DQ rules."""
    rules = [
        OrganizationNameRequiredRule(),
        # Add more rules as needed
    ]
    for rule in rules:
        result = rule.evaluate(payload)
        if result:
            yield result

def run_minimal_dq(import_run, *, dry_run: bool = False, csv_rows=None) -> DQProcessingSummary:
    # ... existing volunteer processing ...

    # Process organizations
    org_rows = (
        session.query(StagingOrganization)
        .filter(
            StagingOrganization.run_id == import_run.id,
            StagingOrganization.status == StagingRecordStatus.LANDED,
        )
        .order_by(StagingOrganization.sequence_number)
    )

    for row in org_rows:
        rows_evaluated += 1
        payload = _compose_organization_payload(row)
        violations = list(evaluate_organization_rules(payload))
        if violations:
            rows_quarantined += 1
            all_violations.extend(violations)
        else:
            rows_validated += 1
            row.status = StagingRecordStatus.VALIDATED
```

**Key Points**:
- Create entity-specific rule classes
- Add entity-specific evaluation function
- Update `run_minimal_dq` to process both entity types
- Mark rows as `VALIDATED` when they pass DQ

### Step 7: Create Clean Model

**File**: `flask_app/models/importer/schema.py`

**Example** (Organizations):
```python
class CleanOrganization(BaseModel):
    __tablename__ = "clean_organizations"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staging_organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True, index=True)
    name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    load_action: Mapped[str | None] = mapped_column(db.String(50), nullable=True)
    core_organization_id: Mapped[int | None] = mapped_column(db.Integer, nullable=True, index=True)

    import_run = relationship("ImportRun", back_populates="clean_organizations")
    staging_row = relationship("StagingOrganization", back_populates="clean_record")
    import_skips = relationship(
        "ImportSkip",
        back_populates="clean_organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "staging_organization_id",
            name="uq_clean_organizations_run_staging",
        ),
    )
```

**Key Points**:
- Link to staging row via foreign key
- Store key fields (e.g., `name`) for deduplication
- Track `load_action` for audit
- Link to core entity via `core_<entity>_id`

### Step 8: Add Clean Promotion

**File**: `flask_app/importer/pipeline/clean.py`

**Example** (Organizations):
```python
def promote_clean_organizations(import_run, *, dry_run: bool = False) -> CleanPromotionSummary:
    """Promote validated staging organizations into the clean layer."""

    session = db.session
    rows = (
        session.query(StagingOrganization)
        .filter(
            StagingOrganization.run_id == import_run.id,
            StagingOrganization.status == StagingRecordStatus.VALIDATED,
        )
        .order_by(StagingOrganization.sequence_number)
    )

    # ... create CleanOrganization records ...
```

**Key Points**:
- Only promote rows with `status == VALIDATED`
- Compute checksum for change detection
- Link to staging row

### Step 9: Create Loader

**File**: `flask_app/importer/pipeline/salesforce_<entity>_loader.py`

**Example** (Organizations):
```python
class SalesforceOrganizationLoader:
    """Two-phase loader that reconciles Salesforce Accounts into core Organization tables."""

    def __init__(self, run: ImportRun, session: Session | None = None):
        self.run = run
        self.session = session or db.session

    def execute(self) -> LoaderCounters:
        clean_rows = self._snapshot_clean_rows()
        counters = LoaderCounters()

        with self._transaction():
            for clean_row in clean_rows:
                action = self._apply_row(clean_row)
                # ... update counters ...

            self._advance_watermark(all_staging_rows)
            self.run.status = ImportRunStatus.SUCCEEDED
            self._persist_counters(counters)

        return counters

    def _apply_row(self, clean_row: CleanOrganization) -> str:
        # 1. Get ExternalIdMap entry
        # 2. Check for duplicates (name-based for organizations)
        # 3. Create or update Organization
        # 4. Update ExternalIdMap
        # 5. Return action ("created", "updated", "unchanged", "deleted")
```

**Key Points**:
- Use `ExternalIdMap` with unique `entity_type` for idempotency
- Implement name-based deduplication (if applicable)
- Handle create, update, delete, and unchanged cases
- Advance watermark after successful commit
- Use two-phase commit pattern

### Step 10: Add Celery Task

**File**: `flask_app/importer/tasks.py`

**Example** (Organizations):
```python
@shared_task(name="importer.pipeline.ingest_salesforce_accounts", bind=True)
def ingest_salesforce_accounts(
    self,
    *,
    run_id: int,
    dry_run: bool = False,
    record_limit: int | None = None,
) -> dict[str, object]:
    """Execute the Salesforce Account (Organization) ingest pipeline."""

    run = db.session.get(ImportRun, run_id)
    # ... orchestrate full pipeline ...
    # 1. Extract and stage
    # 2. Run DQ
    # 3. Promote to clean
    # 4. Load into core
```

**Key Points**:
- Orchestrate all pipeline stages
- Handle errors and update run status
- Return summary with counters

### Step 11: Update CLI

**File**: `flask_app/importer/cli.py`

**Example**:
```python
@importer_cli.command("run-salesforce")
@click.option("--entity-type", type=click.Choice(["contacts", "organizations"]))
def run_salesforce(entity_type: str | None = None):
    # Detect entity type from ImportRun or parameter
    # Route to appropriate task
```

**Key Points**:
- Support entity type selection
- Store entity type in `ImportRun.ingest_params_json`
- Route to correct task based on entity type

### Step 12: Update UI

**Files**:
- `templates/admin/importer.html`
- `static/js/importer.js`
- `flask_app/routes/admin_importer.py`

**Example**:
```html
<!-- Add entity type selector -->
<div class="form-group">
    <label>Entity Type</label>
    <input type="radio" name="entity_type" value="contacts" checked> Contacts (Volunteers)
    <input type="radio" name="entity_type" value="organizations"> Organizations (Accounts)
</div>
```

**Key Points**:
- Add entity type selector to form
- Include `entity_type` in form submission
- Update route handler to route to correct task
- Update status display to show entity-specific metrics

## Key Learnings

### 1. Relationship Configuration

**Problem**: SQLAlchemy couldn't determine join conditions when `ImportSkip` has multiple foreign keys.

**Solution**: Use `primaryjoin` in relationships:
```python
import_skips = relationship(
    "ImportSkip",
    back_populates="staging_organization",
    primaryjoin="StagingOrganization.id == ImportSkip.staging_organization_id",
    cascade="all, delete-orphan",
    passive_deletes=True,
)
```

**Also**: Specify `foreign_keys` in the reverse relationship:
```python
staging_organization = relationship(
    "StagingOrganization",
    back_populates="import_skips",
    foreign_keys=[staging_organization_id],
)
```

### 2. Mapping File Path Resolution

**Problem**: Using `current_app.root_path` didn't resolve correctly.

**Solution**: Use `current_app.instance_path`:
```python
instance_path = Path(current_app.instance_path)
# instance_path is typically <project_root>/instance, so parent is project root
config_path = (instance_path.parent / "config" / "mappings" / "salesforce_account_v1.yaml").resolve()
```

### 3. Entity Type in ImportRun

**Problem**: Need to track which entity type an import run is processing.

**Solution**: Store in `ImportRun.ingest_params_json`:
```python
run.ingest_params_json = {"entity_type": "organizations"}
```

### 4. Name-Based Deduplication

**Problem**: Organizations don't have emails, so need name-based deduplication.

**Solution**: Implement exact name matching:
```python
def _name_exists_exact_organization(name: str) -> Organization | None:
    """Check if an organization with the same name already exists (case-insensitive)."""
    if not name:
        return None
    return (
        db.session.query(Organization)
        .filter(func.lower(Organization.name) == name.lower())
        .first()
    )
```

### 5. Watermark Object Name

**Problem**: Need separate watermarks for different entity types.

**Solution**: Use `object_name` in `ImporterWatermark`:
```python
watermark = ImporterWatermark(adapter="salesforce", object_name="accounts")
```

### 6. DQ Rules Processing

**Problem**: Need to process multiple entity types in the same DQ run.

**Solution**: Process both entity types in `run_minimal_dq`:
```python
# Process volunteers
for row in volunteer_rows:
    # ... evaluate rules ...

# Process organizations
for row in org_rows:
    # ... evaluate organization rules ...
```

## Common Pitfalls

1. **Forgetting to add foreign key column**: When adding relationships, ensure the foreign key column exists in the target table (e.g., `staging_organization_id` in `ImportSkip`).

2. **Missing primaryjoin**: If a relationship target has multiple foreign keys, specify `primaryjoin` to disambiguate.

3. **Incorrect path resolution**: Use `instance_path` instead of `root_path` for finding config files.

4. **Timezone-aware datetime comparisons**: Always ensure datetimes are timezone-aware before comparing:
   ```python
   if last_modstamp.tzinfo is None:
       last_modstamp = last_modstamp.replace(tzinfo=timezone.utc)
   ```

5. **Forgetting to update DQ processing**: When adding a new entity type, update `run_minimal_dq` to process it.

6. **Missing entity type in ImportRun**: Store entity type in `ingest_params_json` for routing.

7. **Incorrect watermark object_name**: Use consistent naming (e.g., "accounts" not "organizations").

## Testing Strategy

### Unit Tests

1. **Mapping Tests**: Verify YAML loading and field mapping
2. **Transform Tests**: Test transform functions with various inputs
3. **DQ Rule Tests**: Test entity-specific DQ rules
4. **Loader Tests**: Test create, update, delete, and unchanged scenarios

### Integration Tests

1. **Pipeline Tests**: Test full E-L-T-L pipeline
2. **Deduplication Tests**: Test name-based and email-based deduplication
3. **Watermark Tests**: Test incremental import behavior
4. **Error Handling Tests**: Test error scenarios and recovery

### Test File Structure

```
tests/
├── test_salesforce_<entity>_pipeline.py  # Pipeline integration tests
├── test_salesforce_<entity>_loader.py    # Loader unit tests
└── test_importer_pipeline_dq.py          # DQ tests (shared)
```

### Example Test

```python
def test_loader_creates_organization(app):
    """Test that loader creates Organization record."""
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("001")
    payload["name"] = "Test Org"
    _add_staging_row(run, 1, payload)

    # Promote to clean
    promote_clean_organizations(run, dry_run=False)

    # Execute loader
    loader = SalesforceOrganizationLoader(run)
    counters = loader.execute()

    assert counters.created == 1
    entry = ExternalIdMap.query.filter_by(
        external_system="salesforce",
        external_id="001"
    ).first()
    assert entry is not None
    org = db.session.get(Organization, entry.entity_id)
    assert org.name == "Test Org"
```

## References

- [Salesforce Mapping Guide](salesforce-mapping-guide.md) - General mapping documentation
- [Salesforce Field Mapping Summary](salesforce-field-mapping-summary.md) - Field-level documentation
- `config/mappings/salesforce_account_v1.yaml` - Organization mapping example
- `config/mappings/salesforce_session_v1.yaml` - Event mapping example
- `flask_app/importer/pipeline/salesforce_organization_loader.py` - Organization loader implementation example
- `flask_app/importer/pipeline/salesforce_event_loader.py` - Event loader implementation example
