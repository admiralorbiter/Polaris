# Salesforce Organization (Account) Field Mapping Summary

This document summarizes the mapping of Salesforce Account fields to Polaris database models and where each field is stored.

## Overview

All Salesforce Account data flows through the import pipeline:
1. **Extract**: Raw Salesforce data → `staging_organizations.payload_json`
2. **Transform**: Normalized data → `staging_organizations.normalized_json` and `clean_organizations.payload_json`
3. **Load**: Core database models (`organizations`, `organization_addresses`, etc.)

## Field Mappings

### Identity & Basic Information

| Salesforce Field | Target Location | Storage | Notes |
|-----------------|----------------|---------|-------|
| `Id` | `external_id` | Used for `ExternalIdMap.external_id` | Required field for idempotency |
| `Name` | `name` | `Organization.name` | Required field |
| `Type` | `organization_type` | `Organization.organization_type` (enum) | Transformed via `normalize_organization_type` |
| `Description` | `description` | `Organization.description` | Optional field |

### Metadata Fields

| Salesforce Field | Target Location | Storage | Notes |
|-----------------|----------------|---------|-------|
| `SystemModstamp` | `metadata.source_modstamp` | `ExternalIdMap.metadata_json` | Used for watermarking |
| `LastModifiedDate` | `metadata.source_last_modified` | `ExternalIdMap.metadata_json` | Audit tracking |
| `LastActivityDate` | `metadata.last_activity_date` | `ExternalIdMap.metadata_json` | Activity tracking |
| `source_system` | `metadata.source_system` | `ExternalIdMap.metadata_json` | Default: "salesforce" |
| `source_object` | `metadata.source_object` | `ExternalIdMap.metadata_json` | Default: "Account" |

## Organization Type Mapping

The `normalize_organization_type` transform maps Salesforce Account Type values to Polaris `OrganizationType` enum values:

### Enum Values

- `SCHOOL` - Educational institutions
- `BUSINESS` - For-profit businesses
- `NON_PROFIT` - Non-profit organizations
- `GOVERNMENT` - Government entities
- `OTHER` - Other organization types

### Transform Logic

The transform performs case-insensitive matching with fuzzy fallback:

```python
# Direct mappings
"business" → "business"
"non-profit" → "non_profit"
"nonprofit" → "non_profit"
"government" → "government"
"school" → "school"

# Default
Unmapped values → "other"
```

### Filtered Types

The following Account Types are **excluded** from import:
- `Household`
- `School District`
- `School`

These are filtered in the SOQL query via `WHERE Type NOT IN ('Household', 'School District', 'School')`.

## Data Flow

### Stage 1: Extract
- SOQL query filters out excluded types
- Orders by `Name ASC`
- Includes watermark filtering via `SystemModstamp`

### Stage 2: Transform
- Maps Salesforce fields to canonical format
- Applies `normalize_organization_type` transform
- Stores metadata fields

### Stage 3: DQ Validation
- **ORG_NAME_REQUIRED**: Organization name must be present
- Validated rows promoted to `clean_organizations`

### Stage 4: Load
- Idempotent upsert using `ExternalIdMap`
- Name-based deduplication (exact match, case-insensitive)
- Creates/updates `Organization` records
- Stores metadata in `ExternalIdMap.metadata_json`

## Deduplication Strategy

Organizations use **name-based deduplication** (unlike volunteers which use email-based):

- Exact name match (case-insensitive)
- If duplicate found, record is skipped and `ImportSkip` is created
- No fuzzy matching (deferred to future phase)

## Watermarking

- Watermark stored in `ImporterWatermark` with:
  - `adapter = "salesforce"`
  - `object_name = "accounts"`
- Tracks `last_successful_modstamp` for incremental imports
- Advanced only after successful load commit

## External ID Mapping

Each imported organization has an `ExternalIdMap` entry:
- `entity_type = "salesforce_organization"`
- `external_system = "salesforce"`
- `external_id = <Salesforce Account Id>`
- `metadata_json` contains:
  - `payload_hash` - For change detection
  - `last_payload` - Full canonical payload
  - `source_modstamp` - Salesforce modification timestamp
  - `source_last_modified` - Salesforce last modified date
  - `last_activity_date` - Last activity date

## Core Model Fields

The `Organization` model stores:
- `name` - Organization name (required)
- `slug` - URL-friendly slug (auto-generated from name)
- `description` - Organization description
- `organization_type` - Type enum (SCHOOL, BUSINESS, NON_PROFIT, GOVERNMENT, OTHER)
- `website` - Organization website URL
- `phone` - Primary phone number
- `email` - Primary email address
- `tax_id` - Tax identification number
- `logo_url` - Logo image URL
- `contact_person_name` - Primary contact name
- `contact_person_title` - Primary contact title
- `founded_date` - Date organization was founded
- `is_active` - Active status flag

## Future Enhancements

Planned but not yet implemented:
- Address import (mapping to `OrganizationAddress`)
- Contact person details (separate contact records)
- Organization relationships (linking to individuals)
- Fuzzy deduplication for organizations

## References

- [Salesforce Mapping Guide](salesforce-mapping-guide.md) - General mapping documentation
- [Adding Entity Types Guide](adding-entity-types-guide.md) - Implementation guide
- `config/mappings/salesforce_account_v1.yaml` - Mapping specification
- `flask_app/models/organization.py` - Organization model definition

