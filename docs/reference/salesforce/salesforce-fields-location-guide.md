# Where Your Salesforce Fields Are Stored

This document explains where each Salesforce field is stored in the database and whether it appears in the Data Quality Dashboard.

## Fields Stored in Contact/Volunteer Models (Visible in Dashboard)

These fields are stored directly in the `contacts` or `volunteers` tables and **WILL appear** in the Data Quality Dashboard:

| Salesforce Field | Database Location | Dashboard Field Name | Status |
|-----------------|-------------------|---------------------|--------|
| `Age_Group__c` | `contacts.age_group` | **age_group** | ✅ Now visible |
| `Contact_Type__c` | `contacts.type` | **type** | ✅ Now visible |
| `FirstName` | `contacts.first_name` | first_name | ✅ Visible |
| `LastName` | `contacts.last_name` | last_name | ✅ Visible |
| `MiddleName` | `contacts.middle_name` | middle_name | ✅ Visible |
| `Birthdate` | `contacts.birthdate` | birthdate | ✅ Visible |
| `Gender__c` | `contacts.gender` | gender | ✅ Visible |
| `Racial_Ethnic_Background__c` | `contacts.race` | race | ✅ Visible |
| `Highest_Level_of_Educational__c` | `contacts.education_level` | education_level | ✅ Visible |
| `First_Volunteer_Date__c` | `volunteers.first_volunteer_date` | first_volunteer_date | ✅ Visible (in Volunteer dashboard) |
| `Last_Volunteer_Date__c` | `volunteers.last_volunteer_date` | last_volunteer_date | ✅ Visible (in Volunteer dashboard) |
| `Title` | `volunteers.title` | title | ✅ Visible (in Volunteer dashboard) |
| `Department` | `volunteers.department` or `contacts.notes` | department | ✅ Visible (in Volunteer dashboard) |

## Fields Stored in Metadata (NOT in Dashboard)

These fields are stored in `external_id_map.metadata_json` and **DO NOT appear** in the Data Quality Dashboard. They are stored for reference and can be accessed programmatically:

| Salesforce Field | Storage Location | How to Access |
|-----------------|------------------|---------------|
| `AccountId` | `external_id_map.metadata_json["account_id"]` | Via ExternalIdMap query |
| `npsp__Primary_Affiliation__c` | `external_id_map.metadata_json["primary_organization_id"]` | Via ExternalIdMap query |
| `Last_Email_Message__c` | `external_id_map.metadata_json["last_email_message_at"]` | Via ExternalIdMap query |
| `Last_Non_Internal_Email_Activity__c` | `external_id_map.metadata_json["last_external_email_activity_at"]` | Via ExternalIdMap query |
| `EmailBouncedDate` | `external_id_map.metadata_json["email_bounced_date"]` | Via ExternalIdMap query |
| `Last_Mailchimp_Email_Date__c` | `external_id_map.metadata_json["last_mailchimp_email_at"]` | Via ExternalIdMap query |
| `Last_Activity_Date__c` | `external_id_map.metadata_json["last_activity_date"]` | Via ExternalIdMap query |
| `SystemModstamp` | `external_id_map.metadata_json["source_modstamp"]` | Via ExternalIdMap query |
| `LastModifiedDate` | `external_id_map.metadata_json["source_last_modified"]` | Via ExternalIdMap query |
| `Number_of_Attended_Volunteer_Sessions__c` | `external_id_map.metadata_json["attended_sessions_count"]` | Via ExternalIdMap query |

## Why Metadata Fields Aren't in the Dashboard

The Data Quality Dashboard is designed to track **core business data** that users interact with regularly. Metadata fields like:
- Source system timestamps (SystemModstamp, LastModifiedDate)
- External system IDs (AccountId, Primary_Affiliation__c)
- Engagement tracking dates (Last_Email_Message__c, etc.)

Are stored in `ExternalIdMap.metadata_json` because:
1. They're **import tracking data**, not core business data
2. They're **Salesforce-specific** and may not apply to other data sources
3. They're **reference data** used for debugging, auditing, and future integrations

## How to Access Metadata Fields

### In Python Code

```python
from flask_app.models.importer import ExternalIdMap

# Get metadata for a specific Salesforce contact
entry = ExternalIdMap.query.filter_by(
    external_system="salesforce",
    external_id="0015f00000JU6EwAAL"  # Salesforce Contact ID
).first()

if entry and entry.metadata_json:
    metadata = entry.metadata_json
    account_id = metadata.get("account_id")
    last_email_message = metadata.get("last_email_message_at")
    email_bounced_date = metadata.get("email_bounced_date")
    source_modstamp = metadata.get("source_modstamp")
```

### In Volunteer View Template

The volunteer detail page already displays some metadata fields. See `templates/volunteers/view.html` for examples.

### Via SQL Query

```sql
SELECT 
    e.external_id,
    e.metadata_json->>'account_id' as account_id,
    e.metadata_json->>'last_email_message_at' as last_email_message,
    e.metadata_json->>'email_bounced_date' as email_bounced,
    e.metadata_json->>'source_modstamp' as system_modstamp
FROM external_id_map e
WHERE e.external_system = 'salesforce'
  AND e.metadata_json IS NOT NULL;
```

## Viewing All Imported Data

To see ALL imported data (including metadata), check:

1. **Importer Runs Dashboard** (`/admin/importer/runs`)
   - Shows import run status, counts, and errors
   - Links to staging data

2. **Staging Data** (via Importer Runs detail view)
   - `staging_volunteers.payload_json` - Original Salesforce data
   - `staging_volunteers.normalized_json` - Transformed data

3. **ExternalIdMap Table**
   - `external_id_map.metadata_json` - All metadata fields
   - Query via SQL or Python code

## Recent Changes

✅ **Added to Dashboard:**
- `age_group` - Now visible in Contact dashboard
- `type` - Now visible in Contact dashboard

These fields will appear after you:
1. Click "Refresh" on the Data Quality Dashboard
2. Wait for cache to expire (5 minutes)
3. Run a new import (if data wasn't previously loaded)

## Summary

- **Core fields** (age_group, type, demographics, etc.) → `contacts`/`volunteers` tables → **Visible in Dashboard** ✅
- **Metadata fields** (timestamps, external IDs, engagement dates) → `external_id_map.metadata_json` → **Not in Dashboard** (but accessible via code/SQL) 📊

The dashboard focuses on **data completeness for business use**, while metadata is stored separately for **import tracking and auditing**.

