# Salesforce Mapping Testing Checklist

## Current Status

The implementation is **functionally complete** but **needs test coverage** before production use. Based on the documentation and code review:

### ✅ Ready for Testing
- All fields added to extractor
- All mappings added to YAML
- All transforms implemented
- Loader updated to handle new fields
- No linter errors

### ⚠️ Needs Test Coverage
The following new functionality needs test coverage before running a full import:

## Required Test Updates

### 1. Transform Tests (`tests/test_salesforce_mapping_transformer.py`)

**Add tests for:**
- `split_semicolon` transform:
  ```python
  def test_split_semicolon_transform():
      """Test that split_semicolon splits semicolon-separated values into arrays."""
      spec = MappingSpec(
          version=1,
          adapter="salesforce",
          object_name="Contact",
          fields=(
              MappingField(source="Volunteer_Skills__c", target="skills.volunteer_skills", transform="split_semicolon"),
          ),
          transforms={"split_semicolon": MappingTransform(name="split_semicolon")},
          checksum="fake",
          path=None,
      )
      transformer = SalesforceMappingTransformer(spec)
      
      # Test with semicolon-separated values
      result = transformer.transform({"Volunteer_Skills__c": "Teaching;Tutoring;Mentoring"})
      assert result.canonical["skills"]["volunteer_skills"] == ["Teaching", "Tutoring", "Mentoring"]
      
      # Test with empty string
      result2 = transformer.transform({"Volunteer_Skills__c": ""})
      assert result2.canonical["skills"]["volunteer_skills"] == []
      
      # Test with None
      result3 = transformer.transform({"Volunteer_Skills__c": None})
      assert result3.canonical["skills"]["volunteer_skills"] == []
  ```

- Nested field mappings (skills, interests, engagement, demographics, address):
  ```python
  def test_nested_field_mappings():
      """Test that nested fields are correctly mapped."""
      spec = MappingSpec(
          version=1,
          adapter="salesforce",
          object_name="Contact",
          fields=(
              MappingField(source="Id", target="external_id", required=True),
              MappingField(source="Volunteer_Skills__c", target="skills.volunteer_skills", transform="split_semicolon"),
              MappingField(source="First_Volunteer_Date__c", target="engagement.first_volunteer_date", transform="parse_date"),
              MappingField(source="Racial_Ethnic_Background__c", target="demographics.racial_ethnic_background"),
              MappingField(source="MailingStreet", target="address.mailing.street"),
              MappingField(source="MailingCity", target="address.mailing.city"),
          ),
          transforms={"split_semicolon": MappingTransform(name="split_semicolon"), "parse_date": MappingTransform(name="parse_date")},
          checksum="fake",
          path=None,
      )
      transformer = SalesforceMappingTransformer(spec)
      
      result = transformer.transform({
          "Id": "001",
          "Volunteer_Skills__c": "Teaching;Tutoring",
          "First_Volunteer_Date__c": "2024-01-15",
          "Racial_Ethnic_Background__c": "Asian",
          "MailingStreet": "123 Main St",
          "MailingCity": "Springfield",
      })
      
      assert result.canonical["skills"]["volunteer_skills"] == ["Teaching", "Tutoring"]
      assert result.canonical["engagement"]["first_volunteer_date"] == "2024-01-15"
      assert result.canonical["demographics"]["racial_ethnic_background"] == "Asian"
      assert result.canonical["address"]["mailing"]["street"] == "123 Main St"
      assert result.canonical["address"]["mailing"]["city"] == "Springfield"
  ```

### 2. Loader Tests (`tests/test_salesforce_loader.py`)

**Add tests for:**
- Skills and interests creation:
  ```python
  def test_loader_creates_skills_and_interests(app):
      """Test that loader creates VolunteerSkill and VolunteerInterest records."""
      from flask_app.models.contact.volunteer import VolunteerSkill, VolunteerInterest
      
      _ensure_watermark()
      run = _create_run()
      payload = {
          "external_id": "001",
          "first_name": "Ada",
          "last_name": "Lovelace",
          "skills": {
              "volunteer_skills": ["Teaching", "Tutoring"],
          },
          "interests": {
              "volunteer_interests": ["Education", "Technology"],
          },
          "metadata": {"source_system": "salesforce"},
      }
      _add_staging_row(run, 1, payload)
      
      loader = SalesforceContactLoader(run)
      counters = loader.execute()
      
      assert counters.created == 1
      volunteer = loader.session.query(Volunteer).filter_by(first_name="Ada").first()
      assert volunteer is not None
      
      skills = VolunteerSkill.query.filter_by(volunteer_id=volunteer.id).all()
      assert len(skills) == 2
      skill_names = [s.skill_name for s in skills]
      assert "Teaching" in skill_names
      assert "Tutoring" in skill_names
      
      interests = VolunteerInterest.query.filter_by(volunteer_id=volunteer.id).all()
      assert len(interests) == 2
      interest_names = [i.interest_name for i in interests]
      assert "Education" in interest_names
      assert "Technology" in interest_names
  ```

- Address creation:
  ```python
  def test_loader_creates_addresses(app):
      """Test that loader creates ContactAddress records."""
      from flask_app.models.contact.info import ContactAddress
      from flask_app.models.contact.enums import AddressType
      
      _ensure_watermark()
      run = _create_run()
      payload = {
          "external_id": "001",
          "first_name": "Ada",
          "last_name": "Lovelace",
          "address": {
              "mailing": {
                  "street": "123 Main St",
                  "city": "Springfield",
                  "state": "IL",
                  "postal_code": "62701",
                  "country": "US",
              },
              "home": {
                  "street": "456 Oak Ave",
                  "city": "Springfield",
                  "state": "IL",
                  "postal_code": "62702",
                  "country": "US",
              },
              "primary_type": "mailing",
          },
          "metadata": {"source_system": "salesforce"},
      }
      _add_staging_row(run, 1, payload)
      
      loader = SalesforceContactLoader(run)
      counters = loader.execute()
      
      assert counters.created == 1
      volunteer = loader.session.query(Volunteer).filter_by(first_name="Ada").first()
      assert volunteer is not None
      
      addresses = ContactAddress.query.filter_by(contact_id=volunteer.id).all()
      assert len(addresses) == 2
      
      mailing = next((a for a in addresses if a.address_type == AddressType.MAILING), None)
      assert mailing is not None
      assert mailing.street_address_1 == "123 Main St"
      assert mailing.city == "Springfield"
      assert mailing.is_primary is True
      
      home = next((a for a in addresses if a.address_type == AddressType.HOME), None)
      assert home is not None
      assert home.street_address_1 == "456 Oak Ave"
      assert home.is_primary is False
  ```

- Notes handling:
  ```python
  def test_loader_applies_notes(app):
      """Test that loader applies notes fields."""
      _ensure_watermark()
      run = _create_run()
      payload = {
          "external_id": "001",
          "first_name": "Ada",
          "last_name": "Lovelace",
          "notes": {
              "description": "General description",
              "recruitment_notes": "Recruited at event",
          },
          "metadata": {"source_system": "salesforce"},
      }
      _add_staging_row(run, 1, payload)
      
      loader = SalesforceContactLoader(run)
      counters = loader.execute()
      
      assert counters.created == 1
      volunteer = loader.session.query(Volunteer).filter_by(first_name="Ada").first()
      assert volunteer.notes == "General description"
      assert volunteer.internal_notes == "Recruited at event"
  ```

- Engagement fields:
  ```python
  def test_loader_applies_engagement_fields(app):
      """Test that loader applies engagement fields."""
      from datetime import date
      
      _ensure_watermark()
      run = _create_run()
      payload = {
          "external_id": "001",
          "first_name": "Ada",
          "last_name": "Lovelace",
          "engagement": {
              "first_volunteer_date": "2024-01-15",
              "attended_sessions_count": 5,
          },
          "metadata": {"source_system": "salesforce"},
      }
      _add_staging_row(run, 1, payload)
      
      loader = SalesforceContactLoader(run)
      counters = loader.execute()
      
      assert counters.created == 1
      volunteer = loader.session.query(Volunteer).filter_by(first_name="Ada").first()
      assert volunteer.first_volunteer_date == date(2024, 1, 15)
      
      # Check metadata
      entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="001").first()
      assert entry.metadata_json.get("attended_sessions_count") == 5
  ```

### 3. Integration Tests (`tests/test_salesforce_pipeline.py`)

**Add test with new fields:**
```python
def test_pipeline_with_new_fields(app):
    """Test full pipeline with new Batch 1-4 fields."""
    run = _create_run()
    watermark = _create_watermark()
    batches = [
        _make_batch(
            1,
            [{
                "Id": "001",
                "FirstName": "Ada",
                "LastName": "Lovelace",
                "Volunteer_Skills__c": "Teaching;Tutoring",
                "Volunteer_Interests__c": "Education",
                "First_Volunteer_Date__c": "2024-01-15",
                "MailingStreet": "123 Main St",
                "MailingCity": "Springfield",
                "MailingState": "IL",
                "MailingPostalCode": "62701",
                "SystemModstamp": "2024-01-01T00:00:00.000Z",
            }],
        ),
    ]
    extractor = DummyExtractor(batches)
    
    summary = ingest_salesforce_contacts(
        import_run=run,
        extractor=extractor,
        watermark=watermark,
        staging_batch_size=1,
        dry_run=False,
        logger=app.logger,
        record_limit=None,
    )
    
    # Verify staging has normalized data
    staged = StagingVolunteer.query.first()
    assert staged.normalized_json is not None
    assert "skills" in staged.normalized_json
    assert "address" in staged.normalized_json
    
    # Verify loader creates records
    loader = SalesforceContactLoader(run)
    counters = loader.execute()
    assert counters.created == 1
```

## Pre-Import Checklist

Before running a full import, complete these steps:

### 1. Unit Tests
- [ ] Add `split_semicolon` transform test
- [ ] Add nested field mapping tests (skills, interests, engagement, demographics, address)
- [ ] Run: `pytest tests/test_salesforce_mapping_transformer.py -v`

### 2. Loader Tests
- [ ] Add skills/interests creation test
- [ ] Add address creation test
- [ ] Add notes handling test
- [ ] Add engagement fields test
- [ ] Run: `pytest tests/test_salesforce_loader.py -v`

### 3. Integration Tests
- [ ] Add pipeline test with new fields
- [ ] Run: `pytest tests/test_salesforce_pipeline.py -v`

### 4. Manual Validation (Per Documentation)
- [ ] Verify mapping loads: `flask importer mappings show`
- [ ] Run dry-run import: `flask importer run-salesforce --dry-run`
- [ ] Check `metrics_json` for unmapped fields/errors
- [ ] Verify DQ violations are expected (no false positives)
- [ ] Check `ImportRun.counts_json` for correct row counts
- [ ] Monitor Prometheus counters

### 5. Field Validation
- [ ] Verify all new fields appear in `normalized_json` in staging
- [ ] Verify skills/interests create VolunteerSkill/VolunteerInterest records
- [ ] Verify addresses create ContactAddress records
- [ ] Verify notes populate Contact.notes and Contact.internal_notes
- [ ] Verify engagement fields populate Volunteer.first_volunteer_date
- [ ] Verify metadata fields stored in ExternalIdMap.metadata_json

## Recommended Testing Order

1. **Unit tests first** - Fast feedback on transforms and mappings
2. **Loader tests** - Verify data persistence logic
3. **Integration tests** - End-to-end pipeline validation
4. **Dry-run import** - Real Salesforce data validation
5. **Small production import** - Limited record count test

## Potential Issues to Watch For

1. **Address field validation** - Ensure street and city are required (loader checks this)
2. **Skills/interests deduplication** - Loader checks for existing records before creating
3. **Primary address logic** - Only one primary address per contact
4. **Date parsing** - Verify parse_date handles various formats
5. **Multi-select picklist splitting** - Verify split_semicolon handles edge cases

## Next Steps

1. Add the test cases above
2. Run test suite to ensure no regressions
3. Perform dry-run import with real Salesforce data
4. Review staging table `normalized_json` for all new fields
5. Verify core tables have correct data
6. Monitor for unmapped fields in metrics

