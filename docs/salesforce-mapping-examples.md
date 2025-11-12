# Salesforce Mapping Examples & Recipes

This document provides practical snippets for Salesforce mapping work. Copy/paste these patterns into your mapping YAML files or transform registry when extending the importer.

## 1. Field Mapping Examples

### 1.1 Simple Field Copy

```yaml
- source: FirstName
  target: first_name
- source: LastName
  target: last_name
```

### 1.2 Nested Email Mapping

```yaml
- source: Email
  target: email.primary
- source: npe01__HomeEmail__c
  target: email.home
- source: npe01__Preferred_Email__c
  target: email.preferred_type
```

### 1.3 Default Values

```yaml
- target: metadata.source_system
  default: salesforce
- target: metadata.source_object
  default: Contact
```

### 1.4 Required Field with Transform

```yaml
- source: MobilePhone
  target: phone.mobile
  required: true
  transform: normalize_phone
```

### 1.5 Conditional Mapping Pattern

```yaml
- source: npe01__PreferredPhone__c
  target: phone.preferred_type
  transform: normalize_phone_preference
```

Where `normalize_phone_preference` is a custom transform returning canonical values (e.g. `mobile`, `home`, `work`).

## 2. Transform Examples

### 2.1 Picklist Normalization

```python
def normalize_preferred_email(value: Any) -> str | None:
    if not value:
        return None
    lookup = {
        "Home": "home",
        "Work": "work",
        "Other": "other",
    }
    return lookup.get(str(value).strip(), "primary")
```

### 2.2 Multi-select Picklist Splitter

```python
def split_interest_codes(value: Any) -> list[str] | None:
    if not value:
        return None
    return [code.strip() for code in str(value).split(";") if code.strip()]
```

### 2.3 Date Parsing with Fallback

```python
def parse_partial_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 4:  # year only
        return f"{text}-01-01"
    return text[:10]
```

### 2.4 Boolean Conversion

```python
def to_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    return str(value).strip().lower() in {"true", "1", "yes"}
```

### 2.5 Relationship Wrapper

```python
def wrap_account_reference(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    return {"account": {"salesforce_id": value}}
```

## 3. Complete Mapping Recipes

### 3.1 Minimal Contact Mapping (Required Fields Only)

```yaml
version: 1
adapter: salesforce
object: Contact
fields:
  - source: Id
    target: external_id
    required: true
  - source: FirstName
    target: first_name
    required: true
  - source: LastName
    target: last_name
    required: true
  - source: Email
    target: email.primary
  - source: Phone
    target: phone.primary
    transform: normalize_phone
  - target: metadata.source_system
    default: salesforce
  - target: metadata.source_object
    default: Contact
```

### 3.2 Full Contact Mapping (Extended Fields)

```yaml
fields:
  - source: Id
    target: external_id
    required: true
  - source: AccountId
    target: affiliations.primary_organization_id
  - source: FirstName
    target: first_name
  - source: LastName
    target: last_name
  - source: MiddleName
    target: middle_name
  - source: Email
    target: email.primary
  - source: npe01__HomeEmail__c
    target: email.home
  - source: npe01__WorkEmail__c
    target: email.work
  - source: npe01__Preferred_Email__c
    target: email.preferred_type
    transform: normalize_preferred_email
  - source: HomePhone
    target: phone.home
    transform: normalize_phone
  - source: MobilePhone
    target: phone.mobile
    transform: normalize_phone
  - source: npe01__WorkPhone__c
    target: phone.work
    transform: normalize_phone
  - source: Phone
    target: phone.primary
    transform: normalize_phone
  - source: npe01__PreferredPhone__c
    target: phone.preferred_type
    transform: normalize_phone_preference
  - source: Birthdate
    target: demographics.birthdate
    transform: parse_date
  - source: Gender__c
    target: demographics.gender
  - source: Last_Mailchimp_Email_Date__c
    target: engagement.last_mailchimp_email_at
    transform: parse_datetime
  - source: SystemModstamp
    target: metadata.source_modstamp
    transform: parse_datetime
  - target: metadata.source_system
    default: salesforce
  - target: metadata.source_object
    default: Contact
```

### 3.3 Campaign Member Mapping (Signup Concept)

```yaml
version: 1
adapter: salesforce
object: CampaignMember
fields:
  - source: Id
    target: external_id
    required: true
  - source: ContactId
    target: links.volunteer.salesforce_id
    required: true
  - source: CampaignId
    target: links.event.salesforce_id
    required: true
  - source: Status
    target: signup.status
    transform: normalize_signup_status
  - source: LastModifiedDate
    target: metadata.source_last_modified
    transform: parse_datetime
  - target: metadata.source_system
    default: salesforce
  - target: metadata.source_object
    default: CampaignMember
```

Combine this with a custom transform `normalize_signup_status` to map Salesforce-specific statuses into canonical enumerations.

## 4. Common Field Type Notes

| Field Type | Notes |
|------------|-------|
| Standard Fields (`Email`, `Phone`) | Case-sensitive names; transforms handle normalization. |
| Custom Fields (`__c`) | Always copy API names exactly (`My_Field__c`). |
| Lookup Fields (`AccountId`) | Typically mapped into metadata or linked entity references. |
| Picklists | Use transforms to map values; consider providing fallback defaults. |
| Multi-select Picklists | Values separated by semicolon (`;`). Split into arrays. |
| Formula Fields | Treated as read-only; consider transforms for formatting. |
| Dates/Datetimes | Use `parse_date`/`parse_datetime` to normalize. |
| Compound Addresses | Access via individual components (e.g., `MailingStreet`, `MailingCity`). |

## 5. Workflow Checklist

1. Update mapping YAML with new fields or objects.
2. Add transforms where required; register them in `_build_transform_registry()`.
3. Run unit tests (`pytest tests/test_salesforce_mapping_transformer.py`).
4. Execute dry-run import for validation.
5. Review run metrics, DQ violations, and loader counters.
6. Document changes for stakeholders and plan deployment (version bump if breaking).

## 6. References

- `docs/salesforce-mapping-guide.md`
- `docs/salesforce-transforms-reference.md`
- `config/mappings/salesforce_contact_v1.yaml`
- `flask_app/importer/mapping/__init__.py`
- `tests/test_salesforce_mapping_transformer.py`
