# Salesforce Field Mapping Summary

This document summarizes the mapping of Salesforce Contact fields to Polaris database models and where each field is stored.

## Overview

All Salesforce Contact data flows through the import pipeline:
1. **Extract**: Raw Salesforce data → `staging_volunteers.payload_json`
2. **Transform**: Normalized data → `staging_volunteers.normalized_json` and `clean_volunteers.payload_json`
3. **Load**: Core database models (`contacts`, `volunteers`, `contact_emails`, `contact_phones`, etc.)

## Field Mappings

### Identity & Basic Information

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `Id` | `external_id` | Used for `ExternalIdMap.external_id` |
| `FirstName` | `first_name` | `Contact.first_name` |
| `LastName` | `last_name` | `Contact.last_name` |
| `MiddleName` | `middle_name` | `Contact.middle_name` |
| `Contact_Type__c` | `type` | `Contact.type` (string field) |

### Contact Information

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `Email` | `email.primary` | `ContactEmail` record (primary) |
| `npe01__HomeEmail__c` | `email.home` | `ContactEmail` record |
| `npe01__WorkEmail__c` | `email.work` | `ContactEmail` record |
| `npe01__AlternateEmail__c` | `email.alternate` | `ContactEmail` record |
| `npe01__Preferred_Email__c` | `email.preferred_type` | Used to determine primary email |
| `MobilePhone` | `phone.mobile` | `ContactPhone` record |
| `HomePhone` | `phone.home` | `ContactPhone` record |
| `npe01__WorkPhone__c` | `phone.work` | `ContactPhone` record |
| `Phone` | `phone.primary` | `ContactPhone` record (primary) |
| `npe01__PreferredPhone__c` | `phone.preferred_type` | Used to determine primary phone |

### Demographics

| Salesforce Field | Target Location | Storage | Transform |
|-----------------|----------------|---------|-----------|
| `Gender__c` | `demographics.gender` | `Contact.gender` (enum) | Direct mapping |
| `Birthdate` | `demographics.birthdate` | `Contact.birthdate` (date) | `parse_date` |
| `Racial_Ethnic_Background__c` | `demographics.racial_ethnic_background` | `Contact.race` (enum) | `normalize_race_ethnicity` |
| `Age_Group__c` | `demographics.age_group` | `Contact.age_group` (enum) | `normalize_age_group` |
| `Highest_Level_of_Educational__c` | `demographics.highest_education_level` | `Contact.education_level` (enum) | `normalize_education_level` |

**Age Group Transform**: Maps Salesforce values like "60-69", "18-64" to enum values:
- `child` (0-12)
- `teen` (13-17)
- `adult` (18-64)
- `senior` (65+)

### Employment

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `Title` | `employment.title` | `Volunteer.title` |
| `Department` | `employment.department` | `Volunteer.department` (if exists) or appended to `Contact.notes` |

### Affiliations (Contact-Organization Relationships)

**Note**: Affiliations are imported from the `npe5__Affiliation__c` object as a separate import type. This is distinct from the `AccountId` and `npsp__Primary_Affiliation__c` fields on Contact records.

**Import Prerequisites**: Affiliations import requires contacts and organizations to be imported first, as it needs to resolve `contact_external_id` and `organization_external_id` via `ExternalIdMap`.

**Volunteer Filtering**: By default, the affiliation import only includes affiliations for contacts where `Contact_Type__c = 'Volunteer'`. This can be disabled by setting `IMPORTER_SALESFORCE_FILTER_VOLUNTEERS=false` in your `.env` file.

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `Id` | `external_id` | Used for `ExternalIdMap.external_id` (entity_type="salesforce_affiliation") |
| `npe5__Contact__c` | `contact_external_id` | Used to lookup Contact via ExternalIdMap |
| `npe5__Organization__c` | `organization_external_id` | Used to lookup Organization via ExternalIdMap |
| `npe5__Primary__c` | `is_primary` | `ContactOrganization.is_primary` |
| `npe5__StartDate__c` | `start_date` | `ContactOrganization.start_date` |
| `npe5__EndDate__c` | `end_date` | `ContactOrganization.end_date` (null if current) |
| `npe5__Status__c` | `metadata.status` | Stored in `ExternalIdMap.metadata_json["status"]` |
| `npe5__Role__c` | `metadata.role` | Stored in `ExternalIdMap.metadata_json["role"]` |

**Contact-Level Affiliation Fields** (from Contact object):

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `AccountId` | `affiliations.account_id` | `ExternalIdMap.metadata_json["account_id"]` |
| `npsp__Primary_Affiliation__c` | `affiliations.primary_organization_id` | `ExternalIdMap.metadata_json["primary_organization_id"]` |

**Note**: These are Salesforce IDs. To link to Polaris Organizations, you would need to:
1. Import Organization data from Salesforce Account object
2. Create an `ExternalIdMap` entry mapping Salesforce Account ID → Polaris Organization ID
3. Use that mapping to create `ContactOrganization` records

### Engagement

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `First_Volunteer_Date__c` | `engagement.first_volunteer_date` | `Volunteer.first_volunteer_date` (date) |
| `Last_Volunteer_Date__c` | `engagement.last_volunteer_date` | `Volunteer.last_volunteer_date` (date) |
| `Number_of_Attended_Volunteer_Sessions__c` | `engagement.attended_sessions_count` | `ExternalIdMap.metadata_json["attended_sessions_count"]` |
| `Last_Email_Message__c` | `engagement.last_email_message_at` | `ExternalIdMap.metadata_json["last_email_message_at"]` (datetime) |
| `Last_Non_Internal_Email_Activity__c` | `engagement.last_external_email_activity_at` | `ExternalIdMap.metadata_json["last_external_email_activity_at"]` (datetime) |
| `Last_Mailchimp_Email_Date__c` | `engagement.last_mailchimp_email_at` | `ExternalIdMap.metadata_json["last_mailchimp_email_at"]` (datetime) |
| `Last_Activity_Date__c` | `engagement.last_activity_date` | `ExternalIdMap.metadata_json["last_activity_date"]` (date) |

### Skills & Interests

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `Volunteer_Skills__c` | `skills.volunteer_skills` | `VolunteerSkill` records (split by semicolon) |
| `Volunteer_Skills_Text__c` | `skills.volunteer_skills_text` | Appended to `Contact.notes` |
| `Volunteer_Interests__c` | `interests.volunteer_interests` | `VolunteerInterest` records (split by semicolon) |

### Notes

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `Description` | `notes.description` | `Contact.notes` |
| `Volunteer_Recruitment_Notes__c` | `notes.recruitment_notes` | `Contact.internal_notes` |

### Address

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `MailingStreet` | `address.mailing.street` | `ContactAddress` record (type: MAILING) |
| `MailingCity` | `address.mailing.city` | `ContactAddress` record |
| `MailingState` | `address.mailing.state` | `ContactAddress` record |
| `MailingPostalCode` | `address.mailing.postal_code` | `ContactAddress` record |
| `MailingCountry` | `address.mailing.country` | `ContactAddress` record |

### Contact Preferences

| Salesforce Field | Target Location | Storage | Default |
|-----------------|----------------|---------|---------|
| `DoNotCall` | `contact_preferences.do_not_call` | `Contact.do_not_call` (boolean) | `false` |
| `HasOptedOutOfEmail` | `contact_preferences.do_not_email` | `Contact.do_not_email` (boolean) | `false` |
| `npsp__Do_Not_Contact__c` | `contact_preferences.do_not_contact` | `Contact.do_not_contact` (boolean) | `false` |

### Metadata

| Salesforce Field | Target Location | Storage |
|-----------------|----------------|---------|
| `EmailBouncedDate` | `metadata.email_bounced_date` | `ExternalIdMap.metadata_json["email_bounced_date"]` |
| `SystemModstamp` | `metadata.source_modstamp` | `ExternalIdMap.metadata_json["source_modstamp"]` |
| `LastModifiedDate` | `metadata.source_last_modified` | `ExternalIdMap.metadata_json["source_last_modified"]` |
| `IsDeleted` | `metadata.core_state` | `ExternalIdMap.metadata_json["core_state"]` |
| (default) | `metadata.source_system` | Always set to `"salesforce"` |
| (default) | `metadata.source_object` | Always set to `"Contact"` |

## Data Storage Locations

### Core Tables

1. **`contacts`** - Base contact information
   - Name, demographics, preferences, notes
   - Inherited by `volunteers` table

2. **`volunteers`** - Volunteer-specific information
   - Volunteer dates, title, department, status

3. **`contact_emails`** - Email addresses (one-to-many)
   - Type, primary flag, verification status

4. **`contact_phones`** - Phone numbers (one-to-many)
   - Type, primary flag

5. **`contact_addresses`** - Addresses (one-to-many)
   - Type, primary flag

6. **`volunteer_skills`** - Skills (one-to-many)
   - Skill name, category, proficiency, verified status

7. **`volunteer_interests`** - Interests (one-to-many)
   - Interest name, category

### Import Tracking Tables

1. **`external_id_map`** - Maps Salesforce IDs to Polaris IDs
   - `external_system`: "salesforce"
   - `external_id`: Salesforce Contact ID
   - `entity_id`: Polaris Contact/Volunteer ID
   - `metadata_json`: Stores engagement dates, account IDs, and other metadata

2. **`staging_volunteers`** - Raw imported data
   - `payload_json`: Original Salesforce record
   - `normalized_json`: Transformed canonical format

3. **`clean_volunteers`** - Validated data ready for core load
   - `payload_json`: Normalized payload
   - Links to staging and core records

## Accessing Metadata

To access metadata stored in `ExternalIdMap`:

```python
from flask_app.models.importer import ExternalIdMap

# Get the mapping entry
entry = ExternalIdMap.query.filter_by(
    external_system="salesforce",
    external_id="0015f00000JU6EwAAL"
).first()

# Access metadata
metadata = entry.metadata_json or {}
account_id = metadata.get("account_id")
last_email_message = metadata.get("last_email_message_at")
email_bounced_date = metadata.get("email_bounced_date")
```

## Recent Changes

1. **Added `normalize_age_group` transform** - Maps Salesforce age group values (e.g., "60-69") to AgeGroup enum
2. **Enhanced metadata storage** - All engagement datetime fields and source timestamps are now stored in `ExternalIdMap.metadata_json`
3. **Verified field mappings** - All fields from your Salesforce query are now properly mapped and stored

## Questions or Issues?

If you find that any Salesforce field is not being mapped correctly, or if you need to add new fields:

1. Update `config/mappings/salesforce_contact_v1.yaml` to add the field mapping
2. If needed, add a transform function in `flask_app/importer/mapping/__init__.py`
3. Update the loader in `flask_app/importer/pipeline/salesforce_loader.py` to store the field in the appropriate location
