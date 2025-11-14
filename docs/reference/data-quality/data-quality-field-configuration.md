# Data Quality Field Configuration Feature

## Executive Summary

Allow administrators to disable fields in the Data Quality Dashboard that aren't used by their organization. This will:
- Filter disabled fields from metrics calculation and display (improving health score accuracy)
- Improve dashboard clarity by hiding unused fields (e.g., Clearance Status, Availability, Hours Logged)
- Provide foundation for future expansion to create and map custom fields via UI
- Support system-wide configuration initially, with architecture extensible to organization-specific settings

**Target**: Flask app with optional field configuration system
**Style**: Configuration-driven, database-backed, UI/API/CLI accessible
**Approach**: Robust, complete plan broken into implementation phases (similar to data-integration-platform architecture)

## Goals, Non-Goals, and Guiding Principles

### Goals

1. **Field Visibility Control**: Administrators can disable fields that aren't used, improving dashboard clarity and health score accuracy
2. **System-Wide Configuration**: Start with system-wide settings (simpler implementation), design extensible to organization-specific (future)
3. **Full Stack Implementation**: UI, API, CLI, and database components from the start
4. **Performance**: Excluded fields don't impact calculation performance
5. **Future-Proof**: Architecture supports custom field creation and mapping (future expansion)

### Non-Goals

- Organization-specific configuration in v1 (designed for future, but not implemented)
- Custom field creation in v1 (foundation only, implementation deferred)
- Field-level permissions (deferred to RBAC epic)
- Historical data migration (fresh start, no legacy migration needed)

### Principles

- **Configuration-Driven**: Settings stored in database, accessible via UI/API/CLI
- **Backward Compatible**: Existing dashboards continue to work with all fields enabled by default
- **Extensible Design**: Architecture supports future org-specific settings and custom fields
- **Performance First**: Filtering happens at service layer, not in queries
- **Auditability**: Configuration changes logged for compliance

## Architecture Overview

### High-Level Components

- **Configuration Service**: Manages field visibility settings (get/set/validate)
- **Data Quality Service**: Filters disabled fields from metrics calculation
- **API Layer**: REST endpoints for configuration management
- **UI Layer**: Admin interface for field configuration
- **CLI Layer**: Command-line interface for configuration management
- **Database Layer**: Configuration storage (new table for explicit schema)

### Data Flow

1. **Configuration Storage**: Field visibility settings stored in `data_quality_field_config` table
2. **Service Layer**: Configuration service reads settings, validates against entity definitions
3. **Metrics Calculation**: Data quality service filters disabled fields before calculating metrics
4. **UI/API/CLI**: All access configuration through service layer (single source of truth)

### Configuration Storage Design

**Decision**: New `DataQualityFieldConfig` table (not `OrganizationFeatureFlag`)
- **Rationale**: Explicit schema, better for future expansion, clearer semantics
- **Schema**: System-wide configuration (organization_id = NULL), extensible to org-specific (organization_id = <id>)
- **Migration Path**: Start with system-wide, add org-specific later without breaking changes

## Data Model & Schema

### Database Tables

#### `data_quality_field_config`

```sql
CREATE TABLE data_quality_field_config (
    id INTEGER PRIMARY KEY,
    organization_id INTEGER NULL,  -- NULL for system-wide, <id> for org-specific (future)
    entity_type VARCHAR(50) NOT NULL,  -- 'volunteer', 'contact', 'student', etc.
    field_name VARCHAR(100) NOT NULL,  -- 'clearance_status', 'availability', etc.
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_system_field BOOLEAN NOT NULL DEFAULT TRUE,  -- System fields vs custom fields (future)
    display_name VARCHAR(200) NULL,  -- Custom display name (future)
    description TEXT NULL,  -- Field description for UI (future)
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    created_by_user_id INTEGER NULL,
    updated_by_user_id INTEGER NULL,
    UNIQUE(organization_id, entity_type, field_name)
);
```

**Indexes**:
- `idx_dq_field_config_entity` on `(entity_type, is_enabled)`
- `idx_dq_field_config_org` on `(organization_id, entity_type)` (for future org-specific)

**Notes**:
- `organization_id = NULL` means system-wide configuration
- Future: `organization_id = <id>` means organization-specific override
- `is_system_field = TRUE` means standard field (cannot be deleted, can be disabled)
- Future: `is_system_field = FALSE` means custom field (can be created/deleted via UI)

### Entity Field Definitions

#### Volunteer Fields (from `_get_volunteer_metrics`)

| Field Name | Type | Default Enabled | Description |
|------------|------|-----------------|-------------|
| `title` | direct | true | Job title/position |
| `industry` | direct | true | Industry/field they work in |
| `clearance_status` | direct | **false** | Background check/clearance status |
| `first_volunteer_date` | direct | true | First volunteer date |
| `last_volunteer_date` | direct | true | Last volunteer date |
| `total_volunteer_hours` | direct | true | Cumulative hours volunteered |
| `skills` | relationship | true | Volunteer skills |
| `interests` | relationship | true | Volunteer interests |
| `availability` | relationship | **false** | Availability slots |
| `hours_logged` | relationship | **false** | Hours logged records |

#### Contact Fields (from `_get_contact_metrics`)

All fields enabled by default (no fields to disable initially).

#### Student, Teacher, Event, Organization, User Fields

All fields enabled by default (no fields to disable initially).

## Implementation Phases

### Phase 1: Foundation & Database Schema

**Goal**: Establish database schema and configuration service layer

**Tasks**:
1. Create `data_quality_field_config` table (Alembic migration)
2. Create `DataQualityFieldConfig` SQLAlchemy model
3. Create field definitions registry (hardcoded list of available fields per entity)
4. Create `DataQualityFieldConfigService` with basic get/set methods
5. Seed default configuration (disabled fields: `clearance_status`, `availability`, `hours_logged`)
6. Unit tests for service layer

**Files**:
- `flask_app/models/data_quality.py` - New model file
- `flask_app/services/data_quality_field_config_service.py` - Configuration service
- `alembic/versions/XXXX_add_data_quality_field_config.py` - Migration
- `tests/test_data_quality_field_config_service.py` - Unit tests

**Acceptance Criteria**:
- Database table created with correct schema
- Service can get/set field configuration
- Default configuration seeded (disabled fields)
- Unit tests pass

### Phase 2: Data Quality Service Integration

**Goal**: Filter disabled fields from metrics calculation

**Tasks**:
1. Update `DataQualityService` to accept field configuration
2. Filter disabled fields before calculating metrics
3. Update health score calculation to exclude disabled fields
4. Update entity metrics calculation to exclude disabled fields
5. Cache field configuration (5-minute TTL, same as metrics cache)
6. Integration tests for metrics calculation with disabled fields

**Files**:
- `flask_app/services/data_quality_service.py` - Update metrics calculation
- `tests/test_data_quality_service.py` - Update tests

**Acceptance Criteria**:
- Disabled fields excluded from metrics calculation
- Health score excludes disabled fields
- Entity metrics exclude disabled fields
- Performance: No significant impact on calculation time
- Integration tests pass

### Phase 3: API Endpoints

**Goal**: REST API for field configuration management

**Tasks**:
1. Create API routes for field configuration
2. GET `/admin/data-quality/api/field-config` - Get current configuration
3. GET `/admin/data-quality/api/field-config/<entity_type>` - Get configuration for entity
4. POST `/admin/data-quality/api/field-config` - Update configuration
5. POST `/admin/data-quality/api/field-config/<entity_type>/<field_name>/toggle` - Toggle field
6. GET `/admin/data-quality/api/field-definitions` - Get available field definitions
7. API validation and error handling
8. API tests

**Files**:
- `flask_app/routes/admin_data_quality.py` - New route file (or extend existing)
- `tests/routes/test_admin_data_quality_fields.py` - API tests

**Acceptance Criteria**:
- API endpoints return correct configuration
- API endpoints update configuration correctly
- API validation works (invalid field names rejected)
- API tests pass
- API documentation updated

### Phase 4: Admin UI

**Goal**: User interface for field configuration management

**Tasks**:
1. Create field configuration page (`/admin/data-quality/fields`)
2. Entity type selector (Contacts, Volunteers, Students, etc.)
3. Field list with toggle switches for each field
4. Save button to persist configuration
5. Visual indicators (disabled fields grayed out, enabled fields highlighted)
6. Confirmation dialogs for bulk changes
7. Link from data quality dashboard to configuration page
8. UI tests (manual testing, automated tests deferred)

**Files**:
- `templates/admin/data_quality_fields.html` - Configuration UI
- `static/js/data_quality_fields.js` - JavaScript for UI
- `static/css/data_quality_fields.css` - Styles for UI
- `templates/admin/data_quality.html` - Add link to configuration page

**Acceptance Criteria**:
- UI displays current configuration correctly
- UI updates configuration correctly
- UI validates field names
- UI provides clear feedback (success/error messages)
- UI accessible and responsive
- Link from dashboard to configuration page works

### Phase 5: CLI Interface

**Goal**: Command-line interface for field configuration management

**Tasks**:
1. Create CLI commands for field configuration
2. `flask data-quality fields list` - List current configuration
3. `flask data-quality fields show <entity_type>` - Show configuration for entity
4. `flask data-quality fields enable <entity_type> <field_name>` - Enable field
5. `flask data-quality fields disable <entity_type> <field_name>` - Disable field
6. `flask data-quality fields reset <entity_type>` - Reset to defaults
7. CLI tests

**Files**:
- `flask_app/cli/data_quality.py` - CLI commands (or extend existing CLI)
- `tests/test_data_quality_cli.py` - CLI tests

**Acceptance Criteria**:
- CLI commands work correctly
- CLI validation works (invalid field names rejected)
- CLI tests pass
- CLI documentation updated

### Phase 6: Documentation & Testing

**Goal**: Complete documentation and comprehensive testing

**Tasks**:
1. Update data quality dashboard documentation
2. Create field configuration guide
3. Update API documentation
4. Update CLI documentation
5. Integration tests (end-to-end)
6. Performance tests (ensure no degradation)
7. User acceptance testing

**Files**:
- `docs/reference/data-quality/data-quality-field-configuration.md` - This document
- `docs/reference/data-quality/data-quality-dashboard.md` - Update existing documentation
- `tests/integration/test_data_quality_field_config.py` - Integration tests

**Acceptance Criteria**:
- Documentation complete and accurate
- Integration tests pass
- Performance tests pass (no degradation)
- User acceptance testing complete

## Default Configuration

### System-Wide Defaults

For initial implementation, default disabled fields:
- **Volunteer**: `clearance_status`, `availability`, `hours_logged`

All other fields enabled by default.

### Configuration Seed Script

```python
# scripts/seed_data_quality_field_config.py
DEFAULT_DISABLED_FIELDS = {
    "volunteer": ["clearance_status", "availability", "hours_logged"]
}
```

## API Reference

### GET `/admin/data-quality/api/field-config`

Get current field configuration (system-wide).

**Response**:
```json
{
    "entity_types": {
        "volunteer": {
            "title": {"enabled": true, "display_name": "Title"},
            "industry": {"enabled": true, "display_name": "Industry"},
            "clearance_status": {"enabled": false, "display_name": "Clearance Status"},
            ...
        },
        "contact": {
            "first_name": {"enabled": true, "display_name": "First Name"},
            ...
        }
    }
}
```

### POST `/admin/data-quality/api/field-config`

Update field configuration.

**Request**:
```json
{
    "entity_type": "volunteer",
    "field_name": "clearance_status",
    "is_enabled": false
}
```

**Response**:
```json
{
    "success": true,
    "message": "Field configuration updated",
    "config": {
        "entity_type": "volunteer",
        "field_name": "clearance_status",
        "is_enabled": false
    }
}
```

## CLI Reference

### `flask data-quality fields list`

List current field configuration.

**Output**:
```
Entity Type: volunteer
  title: enabled
  industry: enabled
  clearance_status: disabled
  ...
```

### `flask data-quality fields enable volunteer clearance_status`

Enable a field.

### `flask data-quality fields disable volunteer clearance_status`

Disable a field.

## Future Enhancements

### Phase 7: Organization-Specific Configuration (Future)

**Goal**: Support organization-specific field configuration

**Tasks**:
1. Extend `data_quality_field_config` table to support `organization_id`
2. Update service layer to resolve org-specific overrides
3. Update UI to show org-specific settings
4. Update API to support org-specific endpoints
5. Migration path for existing system-wide settings

### Phase 8: Custom Field Creation (Future)

**Goal**: Allow users to create and map custom fields via UI

**Tasks**:
1. Extend `data_quality_field_config` table to support custom fields
2. Create custom field creation UI
3. Create field mapping UI (Salesforce → custom field)
4. Update data quality service to calculate custom field metrics
5. Update dashboard to display custom fields

## Testing Strategy

### Unit Tests

- Configuration service (get/set/validate)
- Data quality service (filtering logic)
- API endpoints (request/response handling)
- CLI commands (argument parsing, validation)

### Integration Tests

- End-to-end configuration flow (UI → API → Database → Service)
- Metrics calculation with disabled fields
- Health score calculation with disabled fields
- Cache invalidation on configuration changes

### Performance Tests

- Metrics calculation performance (no degradation with filtering)
- Configuration service performance (cache effectiveness)
- API response times (acceptable latency)

### User Acceptance Tests

- Configuration UI usability
- Dashboard clarity improvement
- Health score accuracy improvement

## Migration & Deployment

### Database Migration

1. Create `data_quality_field_config` table
2. Seed default configuration (disabled fields)
3. Verify existing dashboards continue to work

### Deployment Steps

1. Deploy database migration
2. Deploy service layer updates
3. Deploy API endpoints
4. Deploy UI components
5. Deploy CLI commands
6. Verify functionality

### Rollback Strategy

1. Revert UI components
2. Revert API endpoints
3. Revert service layer updates
4. Database migration can be kept (backward compatible)

## Risks & Mitigations

### Risk: Performance Degradation

**Mitigation**: Filter at service layer (not in queries), use caching, performance tests

### Risk: Configuration Complexity

**Mitigation**: Simple UI (toggle switches), clear documentation, default configuration

### Risk: Breaking Changes

**Mitigation**: Backward compatible (all fields enabled by default), gradual rollout

## Success Metrics

1. **Dashboard Clarity**: Reduced number of fields displayed (target: 3-5 fewer fields)
2. **Health Score Accuracy**: Improved health scores (target: 5-10% increase)
3. **User Satisfaction**: Positive feedback from administrators
4. **Performance**: No degradation in metrics calculation time
5. **Adoption**: Configuration used by administrators within 1 week of deployment

## Related Documentation

- `docs/reference/data-quality/data-quality-dashboard.md` - Data Quality Dashboard documentation
- `docs/reference/architecture/data-integration-platform-overview.md` - Platform architecture overview
- `docs/reference/architecture/data-integration-platform-tech-doc.md` - Technical documentation

## Support

For issues or questions:
1. Check logs: Review application logs for errors
2. Verify permissions: Ensure user has required permissions
3. Clear cache: Configuration changes may require cache invalidation
4. Check database: Verify database queries are completing successfully
5. Contact support: Reach out to the development team for assistance

