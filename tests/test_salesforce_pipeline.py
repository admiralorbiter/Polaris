from __future__ import annotations

from datetime import datetime, timezone
from flask_app.importer.adapters.salesforce.extractor import SalesforceBatch
from flask_app.importer.pipeline.salesforce import ingest_salesforce_contacts
from flask_app.importer.pipeline.salesforce_loader import SalesforceContactLoader
from flask_app.models import ExternalIdMap
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus, ImporterWatermark, StagingVolunteer


class DummyExtractor:
    def __init__(self, batches):
        self._batches = batches

    def extract_batches(self, _soql):
        for batch in self._batches:
            yield batch


def _make_batch(sequence: int, rows: list[dict[str, str]]) -> SalesforceBatch:
    return SalesforceBatch(job_id="JOB123", sequence=sequence, records=rows, locator=None)


def _create_run(*, dry_run: bool = False) -> ImportRun:
    run = ImportRun(
        source="salesforce",
        adapter="salesforce",
        status=ImportRunStatus.PENDING,
        dry_run=dry_run,
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _create_watermark() -> ImporterWatermark:
    watermark = ImporterWatermark(adapter="salesforce", object_name="contacts")
    db.session.add(watermark)
    db.session.commit()
    return db.session.get(ImporterWatermark, watermark.id)


def test_ingest_salesforce_contacts_persists_rows(app):
    run = _create_run()
    watermark = _create_watermark()
    batches = [
        _make_batch(
            1,
            [
                {"Id": "001", "FirstName": "Ada", "SystemModstamp": "2024-01-01T00:00:00.000Z"},
                {"Id": "002", "FirstName": "Grace", "SystemModstamp": "2024-01-02T00:00:00.000Z"},
            ],
        ),
        _make_batch(
            2,
            [
                {"Id": "003", "FirstName": "Katherine", "SystemModstamp": "2024-01-03T00:00:00.000Z"},
            ],
        ),
    ]
    extractor = DummyExtractor(batches)

    summary = ingest_salesforce_contacts(
        import_run=run,
        extractor=extractor,
        watermark=watermark,
        staging_batch_size=2,
        dry_run=False,
        logger=app.logger,
        record_limit=None,
    )
    loader = SalesforceContactLoader(run)
    counters = loader.execute()
    assert counters.created == 3
    db.session.commit()
    db.session.refresh(run)

    assert summary.records_received == 3
    staged = StagingVolunteer.query.order_by(StagingVolunteer.sequence_number).all()
    assert len(staged) == 3
    normalized = staged[0].normalized_json
    assert normalized["external_id"] == "001"
    assert normalized["first_name"] == "Ada"
    assert normalized["metadata"]["source_system"] == "salesforce"
    assert normalized["metadata"]["source_object"] == "Contact"
    stored_modstamp = watermark.last_successful_modstamp
    assert stored_modstamp is not None
    assert stored_modstamp.replace(tzinfo=timezone.utc) == datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc)
    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_staged"] == 3
    metrics = run.metrics_json["salesforce"]
    assert metrics["records_received"] == 3
    assert metrics["unmapped_fields"] == {}
    assert metrics["transform_errors"] == []
    assert summary.unmapped_counts == {}
    refreshed = db.session.get(ImportRun, run.id)
    assert refreshed is not None
    core_counts = (refreshed.counts_json or {}).get("core", {}).get("volunteers", {}).get("salesforce")
    assert core_counts is not None
    assert core_counts["created"] == 3
    assert core_counts["updated"] == 0
    assert core_counts["deleted"] == 0
    assert core_counts["unchanged"] == 0
    assert run.max_source_updated_at is not None
    active_maps = ExternalIdMap.query.filter_by(entity_type="salesforce_contact", is_active=True).all()
    assert len(active_maps) == 3


def test_ingest_salesforce_contacts_dry_run(app):
    run = _create_run(dry_run=True)
    watermark = _create_watermark()
    batches = [
        _make_batch(
            1,
            [
                {"Id": "001", "FirstName": "Ada", "SystemModstamp": "2024-01-01T00:00:00.000Z"},
            ],
        )
    ]
    extractor = DummyExtractor(batches)

    summary = ingest_salesforce_contacts(
        import_run=run,
        extractor=extractor,
        watermark=watermark,
        staging_batch_size=2,
        dry_run=True,
        logger=app.logger,
        record_limit=None,
    )
    db.session.commit()
    db.session.refresh(run)

    assert summary.records_staged == 0
    assert StagingVolunteer.query.count() == 0
    assert watermark.last_successful_modstamp is None
    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_staged"] == 0
    assert counts["dry_run"] is True
    assert summary.unmapped_counts == {}
    refreshed = db.session.get(ImportRun, run.id)
    assert refreshed is not None
    assert "core" not in (refreshed.counts_json or {})
    assert ExternalIdMap.query.filter_by(entity_type="salesforce_contact").count() == 0


def test_pipeline_with_new_fields(app):
    """Test full pipeline with new Batch 1-4 fields (skills, interests, engagement, demographics, address)."""
    from flask_app.models import Volunteer
    from flask_app.models.contact.volunteer import VolunteerSkill, VolunteerInterest
    from flask_app.models.contact.info import ContactAddress
    from flask_app.models.contact.enums import AddressType
    
    run = _create_run()
    watermark = _create_watermark()
    batches = [
        _make_batch(
            1,
            [{
                "Id": "014",
                "FirstName": "Ada",
                "LastName": "Lovelace",
                "Volunteer_Skills__c": "Teaching;Tutoring",
                "Volunteer_Skills_Text__c": "Additional skills",
                "Volunteer_Interests__c": "Education;Technology",
                "First_Volunteer_Date__c": "2024-01-15",
                "Number_of_Attended_Volunteer_Sessions__c": "5",
                "Last_Email_Message__c": "2024-01-20T10:30:00.000Z",
                "Racial_Ethnic_Background__c": "Asian",
                "Age_Group__c": "Adult",
                "Highest_Level_of_Educational__c": "Bachelors",
                "MailingStreet": "123 Main St",
                "MailingCity": "Springfield",
                "MailingState": "IL",
                "MailingPostalCode": "62701",
                "MailingCountry": "US",
                "Volunteer_Recruitment_Notes__c": "Recruited at event",
                "Description": "General description",
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
    normalized = staged.normalized_json
    
    # Verify new fields are in normalized JSON
    assert "skills" in normalized
    assert normalized["skills"]["volunteer_skills"] == ["Teaching", "Tutoring"]
    assert normalized["skills"]["volunteer_skills_text"] == "Additional skills"
    
    assert "interests" in normalized
    assert normalized["interests"]["volunteer_interests"] == ["Education", "Technology"]
    
    assert "engagement" in normalized
    assert normalized["engagement"]["first_volunteer_date"] == "2024-01-15"
    assert normalized["engagement"]["attended_sessions_count"] == "5"
    assert normalized["engagement"]["last_email_message_at"] == "2024-01-20T10:30:00.000Z"

    assert "demographics" in normalized
    assert normalized["demographics"]["racial_ethnic_background"] == "asian"
    assert normalized["demographics"]["age_group"] == "adult"
    assert normalized["demographics"]["highest_education_level"] == "bachelors"
    
    assert "address" in normalized
    assert normalized["address"]["mailing"]["street"] == "123 Main St"
    assert normalized["address"]["mailing"]["city"] == "Springfield"
    
    assert "notes" in normalized
    assert normalized["notes"]["recruitment_notes"] == "Recruited at event"
    assert normalized["notes"]["description"] == "General description"
    
    # Verify loader creates records
    loader = SalesforceContactLoader(run)
    counters = loader.execute()
    assert counters.created == 1
    
    # Verify volunteer was created
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="014").first()
    assert entry is not None
    volunteer = db.session.get(Volunteer, entry.entity_id)
    assert volunteer is not None
    assert volunteer.first_name == "Ada"
    assert volunteer.last_name == "Lovelace"
    
    # Verify skills were created
    skills = VolunteerSkill.query.filter_by(volunteer_id=volunteer.id).all()
    assert len(skills) == 2
    skill_names = [s.skill_name for s in skills]
    assert "Teaching" in skill_names
    assert "Tutoring" in skill_names
    
    # Verify interests were created
    interests = VolunteerInterest.query.filter_by(volunteer_id=volunteer.id).all()
    assert len(interests) == 2
    interest_names = [i.interest_name for i in interests]
    assert "Education" in interest_names
    assert "Technology" in interest_names
    
    # Verify addresses were created
    addresses = ContactAddress.query.filter_by(contact_id=volunteer.id).all()
    assert len(addresses) == 1  # Only mailing address available
    
    mailing = next((a for a in addresses if a.address_type == AddressType.MAILING), None)
    assert mailing is not None
    assert mailing.street_address_1 == "123 Main St"
    assert mailing.city == "Springfield"
    assert mailing.is_primary is True
    
    # Verify notes
    # Note: volunteer_skills_text gets appended to notes, so we expect both
    assert volunteer.notes == "General description\nSkills: Additional skills"
    assert volunteer.internal_notes == "Recruited at event"
    
    # Verify engagement fields
    from datetime import date
    assert volunteer.first_volunteer_date == date(2024, 1, 15)
    
    # Verify metadata
    metadata = entry.metadata_json or {}
    assert metadata.get("attended_sessions_count") == "5"