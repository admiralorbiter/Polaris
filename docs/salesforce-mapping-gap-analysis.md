# Salesforce Contact Mapping Gap Analysis

## Overview

This document analyzes the current Salesforce Contact mapping (`config/mappings/salesforce_contact_v1.yaml`) against the actual Salesforce data fields being queried, identifies missing fields, and organizes them into prioritized implementation batches.

## Current Mapping Status

### Currently Mapped Fields (29 fields)

#### Identity & Basic Info

- `Id` → `external_id` (required)
- `FirstName` → `first_name`
- `LastName` → `last_name`
- `MiddleName` → `middle_name`

#### Email Fields

- `Email` → `email.primary`
- `npe01__HomeEmail__c` → `email.home`
- `npe01__WorkEmail__c` → `email.work`
- `npe01__AlternateEmail__c` → `email.alternate`
- `npe01__Preferred_Email__c` → `email.preferred_type`

#### Phone Fields

- `MobilePhone` → `phone.mobile` (with normalize_phone transform)
- `HomePhone` → `phone.home` (with normalize_phone transform)
- `npe01__WorkPhone__c` → `phone.work` (with normalize_phone transform)
- `Phone` → `phone.primary` (with normalize_phone transform)
- `npe01__PreferredPhone__c` → `phone.preferred_type`

#### Employment

- `Title` → `employment.title`
- `Department` → `employment.department`

#### Demographics

- `Gender__c` → `demographics.gender`
- `Birthdate` → `demographics.birthdate` (with parse_date transform)

#### Affiliations

- `npsp__Primary_Affiliation__c` → `affiliations.primary_organization_id`

#### Engagement

- `Last_Mailchimp_Email_Date__c` → `engagement.last_mailchimp_email_at` (with parse_datetime transform)
- `Last_Volunteer_Date__c` → `engagement.last_volunteer_date` (with parse_date transform)

#### Contact Preferences

- `DoNotCall` → `contact_preferences.do_not_call` (default: false)
- `HasOptedOutOfEmail` → `contact_preferences.do_not_email` (default: false)
- `npsp__Do_Not_Contact__c` → `contact_preferences.do_not_contact` (default: false)

#### Metadata

- `EmailBouncedDate` → `metadata.email_bounced_date` (with parse_datetime transform)
- `SystemModstamp` → `metadata.source_modstamp` (with parse_datetime transform)
- `LastModifiedDate` → `metadata.source_last_modified` (with parse_datetime transform)
- `IsDeleted` → `metadata.core_state`
- `metadata.source_system` (default: salesforce)
- `metadata.source_object` (default: Contact)

## Missing Fields Analysis

### Fields in Salesforce Query but Not Mapped (47 fields)

#### High Priority - Core Volunteer Data

**Volunteer Skills & Interests**

- `Volunteer_Skills__c` - Multi-select picklist of volunteer skills
- `Volunteer_Skills_Text__c` - Text field for volunteer skills
- `Volunteer_Interests__c` - Multi-select picklist of volunteer interests

**Volunteer Engagement Metrics**

- `Number_of_Attended_Volunteer_Sessions__c` - Count of attended sessions
- `First_Volunteer_Date__c` - First volunteer engagement date
- `Last_Email_Message__c` - Last email message date/activity
- `Last_Non_Internal_Email_Activity__c` - Last external email activity

**Volunteer Notes**

- `Volunteer_Recruitment_Notes__c` - Recruitment and volunteer notes
- `Description` - General description/notes field

**Account Relationship**

- `AccountId` - Primary account/organization ID (in extractor but not mapped)

#### Medium Priority - Demographics & Education

**Demographics**

- `Racial_Ethnic_Background__c` - Race/ethnicity information
- `Age_Group__c` - Age group classification

**Education**

- `Highest_Level_of_Educational__c` - Highest education level

**Activity Tracking**

- `Last_Activity_Date__c` - Last activity date (general)

#### Medium Priority - Address Fields

**Address Types**

- `MailingAddress` - Compound address field (requires component mapping)
- `npe01__Home_Address__c` - Home address compound field
- `npe01__Work_Address__c` - Work address compound field
- `npe01__Other_Address__c` - Other address compound field
- `npe01__Primary_Address_Type__c` - Primary address type preference
- `npe01__Secondary_Address_Type__c` - Secondary address type preference

**Note**: Address fields in Salesforce are compound fields. To map them properly, we need to query individual components:

- `MailingStreet`, `MailingCity`, `MailingState`, `MailingPostalCode`, `MailingCountry`
- `npe01__Home_Street__c`, `npe01__Home_City__c`, `npe01__Home_State__c`, `npe01__Home_Postal_Code__c`, `npe01__Home_Country__c`
- Similar for Work and Other addresses

#### Lower Priority - Connector Fields

These appear to be from a separate "Connector" system/integration:

- `Connector_Active_Subscription__c` - Active subscription status
- `Connector_Active_Subscription_Name__c` - Subscription name
- `Connector_Affiliations__c` - Connector affiliations
- `Connector_Industry__c` - Industry from Connector
- `Connector_Joining_Date__c` - Joining date in Connector
- `Connector_Last_Login_Date_Time__c` - Last login timestamp
- `Connector_Last_Update_Date__c` - Last update date
- `Connector_Profile_Link__c` - Profile link URL
- `Connector_Role__c` - Role in Connector system
- `Connector_SignUp_Role__c` - Signup role
- `Connector_User_ID__c` - User ID in Connector system

**Recommendation**: These should be stored in metadata or a separate connector-specific structure, not core volunteer fields.

## Implementation Batches

### Batch 1: Core Volunteer Engagement Data (High Priority)

**Estimated Effort**: Medium

**Business Value**: High

**Fields**:

- `Volunteer_Skills__c` → `skills.volunteer_skills` (multi-select, needs split transform)
- `Volunteer_Skills_Text__c` → `skills.volunteer_skills_text`
- `Volunteer_Interests__c` → `interests.volunteer_interests` (multi-select, needs split transform)
- `Number_of_Attended_Volunteer_Sessions__c` → `engagement.attended_sessions_count`
- `First_Volunteer_Date__c` → `engagement.first_volunteer_date` (with parse_date transform)
- `Volunteer_Recruitment_Notes__c` → `notes.recruitment_notes`
- `Description` → `notes.description`
- `AccountId` → `affiliations.account_id` (already in extractor)

**Tasks**:

1. Add fields to extractor `DEFAULT_CONTACT_FIELDS`
2. Add mappings to YAML file
3. Create `split_semicolon` transform for multi-select picklists
4. Update loader to apply skills/interests/notes
5. Update core models if new columns needed

### Batch 2: Enhanced Engagement & Activity Tracking (High-Medium Priority)

**Estimated Effort**: Low-Medium

**Business Value**: Medium-High

**Fields**:

- `Last_Email_Message__c` → `engagement.last_email_message_at` (with parse_datetime transform)
- `Last_Non_Internal_Email_Activity__c` → `engagement.last_external_email_activity_at` (with parse_datetime transform)
- `Last_Activity_Date__c` → `engagement.last_activity_date` (with parse_date transform)

**Tasks**:

1. Add fields to extractor
2. Add mappings to YAML
3. Update loader if special handling needed

### Batch 3: Demographics & Education (Medium Priority)

**Estimated Effort**: Low

**Business Value**: Medium

**Fields**:

- `Racial_Ethnic_Background__c` → `demographics.racial_ethnic_background`
- `Age_Group__c` → `demographics.age_group`
- `Highest_Level_of_Educational__c` → `demographics.highest_education_level`

**Tasks**:

1. Add fields to extractor
2. Add mappings to YAML
3. Consider picklist normalization transforms if needed
4. Update loader

### Batch 4: Address Fields (Medium Priority)

**Estimated Effort**: High

**Business Value**: Medium

**Fields**: Address components (see note above)

**Tasks**:

1. Update extractor to include address component fields (not compound fields)
2. Create address normalization transforms
3. Map primary address (MailingAddress components) to `address.*`
4. Map home/work/other addresses to nested structures
5. Map address type preferences
6. Update loader with address handling logic
7. May require core schema changes for multiple addresses

**Note**: This is complex because Salesforce uses compound address fields. We need to query individual components and potentially normalize/validate addresses.

### Batch 5: Connector Integration Fields (Lower Priority)

**Estimated Effort**: Low

**Business Value**: Low (unless Connector system is actively used)

**Fields**: All `Connector_*` fields

**Tasks**:

1. Add fields to extractor
2. Map to `metadata.connector.*` structure (not core volunteer fields)
3. Store in `ExternalIdMap.metadata_json` or similar
4. Document that these are connector-specific metadata

**Recommendation**: Defer until Connector integration requirements are clear.

## Field Mapping Recommendations

### Multi-Select Picklist Handling

For fields like `Volunteer_Skills__c` and `Volunteer_Interests__c`, create a transform:

```python
def split_semicolon(value: Any) -> list[str] | None:
    """Split semicolon-separated values into list."""
    if not value:
        return []
    return [v.strip() for v in str(value).split(';') if v.strip()]
```

### Address Field Handling

For compound address fields, query individual components:

- `MailingStreet`, `MailingCity`, `MailingState`, `MailingPostalCode`, `MailingCountry`
- Map to nested structure: `address.mailing.street`, `address.mailing.city`, etc.

### Notes Field Handling

Consider combining `Description` and `Volunteer_Recruitment_Notes__c` into a structured notes object or separate fields based on business requirements.

## Next Steps

1. **Review with stakeholders**: Confirm priority and business value of each batch
2. **Batch 1 implementation**: Start with core volunteer engagement data
3. **Schema review**: Determine if core models need new columns for skills/interests
4. **Address strategy**: Decide on address storage approach (single vs. multiple addresses)
5. **Connector fields**: Clarify requirements for Connector integration fields

## References

- Current mapping: `config/mappings/salesforce_contact_v1.yaml`
- Extractor: `flask_app/importer/adapters/salesforce/extractor.py`
- Mapping guide: `docs/salesforce-mapping-guide.md`
- Examples: `docs/salesforce-mapping-examples.md`

