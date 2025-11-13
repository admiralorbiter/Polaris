from __future__ import annotations

from datetime import datetime, timezone

from flask_app.importer.pipeline.salesforce_loader import SalesforceContactLoader
from flask_app.models import ContactEmail, EmailType, ExternalIdMap, Volunteer
from flask_app.models.base import db
from flask_app.models.importer.schema import (
    CleanVolunteer,
    ImportRun,
    ImportRunStatus,
    ImportSkip,
    ImportSkipType,
    ImporterWatermark,
    StagingVolunteer,
)


def _create_run() -> ImportRun:
    run = ImportRun(
        source="salesforce",
        adapter="salesforce",
        status=ImportRunStatus.RUNNING,
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _ensure_watermark():
    if not ImporterWatermark.query.filter_by(adapter="salesforce", object_name="contacts").first():
        watermark = ImporterWatermark(adapter="salesforce", object_name="contacts")
        db.session.add(watermark)
        db.session.commit()


def _make_payload(external_id: str, first_name: str = "Ada", deleted: bool = False) -> dict:
    metadata = {
        "source_system": "salesforce",
        "source_object": "Contact",
        "source_modstamp": "2024-01-01T00:00:00.000Z",
        "source_last_modified": "2024-01-01T00:00:00.000Z",
    }
    if deleted:
        metadata["core_state"] = "deleted"
    return {
        "external_id": external_id,
        "first_name": first_name,
        "metadata": metadata,
    }


def _add_staging_row(run: ImportRun, sequence: int, payload: dict) -> None:
    from flask_app.models.importer.schema import StagingRecordStatus
    staging = StagingVolunteer(
        run_id=run.id,
        sequence_number=sequence,
        external_system="salesforce",
        payload_json=payload,
        normalized_json=payload,
        status=StagingRecordStatus.VALIDATED,
    )
    db.session.add(staging)
    db.session.commit()


def test_loader_creates_entries(app):
    _ensure_watermark()
    run = _create_run()
    _add_staging_row(run, 1, _make_payload("001"))
    loader = SalesforceContactLoader(run)
    counters = loader.execute()

    assert counters.created == 1
    assert counters.updated == 0
    assert counters.deleted == 0
    assert counters.unchanged == 0
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="001").first()
    assert entry is not None and entry.is_active


def test_loader_detects_updates_and_unchanged(app):
    _ensure_watermark()
    run = _create_run()
    _add_staging_row(run, 1, _make_payload("002"))
    loader = SalesforceContactLoader(run)
    loader.execute()

    # same payload -> unchanged
    run2 = _create_run()
    _add_staging_row(run2, 1, _make_payload("002"))
    loader2 = SalesforceContactLoader(run2)
    counters = loader2.execute()
    assert counters.unchanged == 1

    # modified payload -> updated
    run3 = _create_run()
    _add_staging_row(run3, 1, _make_payload("002", first_name="Grace"))
    loader3 = SalesforceContactLoader(run3)
    counters2 = loader3.execute()
    assert counters2.updated == 1
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="002").first()
    assert entry is not None and entry.is_active


def test_loader_handles_deletes(app):
    _ensure_watermark()
    run = _create_run()
    _add_staging_row(run, 1, _make_payload("003"))
    SalesforceContactLoader(run).execute()

    run_delete = _create_run()
    _add_staging_row(run_delete, 1, _make_payload("003", deleted=True))
    counters = SalesforceContactLoader(run_delete).execute()

    assert counters.deleted == 1
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="003").first()
    assert entry is not None
    assert not entry.is_active


def test_loader_applies_contact_preferences(app):
    """Test that contact preferences are applied to volunteer records."""
    from flask_app.models import Volunteer
    
    _ensure_watermark()
    run = _create_run()
    
    # Create payload with contact preferences
    payload = _make_payload("004")
    payload["contact_preferences"] = {
        "do_not_call": True,
        "do_not_email": False,
        "do_not_contact": True,
    }
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    loader.execute()
    
    # Verify contact preferences were applied
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="004").first()
    assert entry is not None
    volunteer = db.session.get(Volunteer, entry.entity_id)
    assert volunteer is not None
    assert volunteer.do_not_call is True
    assert volunteer.do_not_email is False
    assert volunteer.do_not_contact is True


def test_loader_contact_preferences_defaults_to_false(app):
    """Test that contact preferences default to False when not provided."""
    from flask_app.models import Volunteer
    
    _ensure_watermark()
    run = _create_run()
    
    # Create payload without contact preferences
    payload = _make_payload("005")
    # No contact_preferences key
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    loader.execute()
    
    # Verify defaults are False
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="005").first()
    assert entry is not None
    volunteer = db.session.get(Volunteer, entry.entity_id)
    assert volunteer is not None
    assert volunteer.do_not_call is False
    assert volunteer.do_not_email is False
    assert volunteer.do_not_contact is False


def test_loader_contact_preferences_string_normalization(app):
    """Test that string boolean values in contact preferences are normalized."""
    from flask_app.models import Volunteer
    
    _ensure_watermark()
    run = _create_run()
    
    # Create payload with string boolean values
    payload = _make_payload("006")
    payload["contact_preferences"] = {
        "do_not_call": "true",  # String, not bool
        "do_not_email": "false",
        "do_not_contact": "1",  # Should be treated as True
    }
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    loader.execute()
    
    # Verify string values were normalized to booleans
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="006").first()
    assert entry is not None
    volunteer = db.session.get(Volunteer, entry.entity_id)
    assert volunteer is not None
    assert volunteer.do_not_call is True
    assert volunteer.do_not_email is False
    assert volunteer.do_not_contact is True


def test_loader_stores_email_bounced_date_in_metadata(app):
    """Test that EmailBouncedDate is stored in ExternalIdMap metadata."""
    from datetime import datetime
    
    _ensure_watermark()
    run = _create_run()
    
    # Create payload with email bounced date
    payload = _make_payload("007")
    payload["metadata"] = {
        **payload["metadata"],
        "email_bounced_date": "2024-01-15T10:30:00.000Z",
    }
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    loader.execute()
    
    # Verify email_bounced_date is stored in ExternalIdMap metadata
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="007").first()
    assert entry is not None
    metadata = entry.metadata_json or {}
    assert "email_bounced_date" in metadata.get("last_payload", {}).get("metadata", {})


def test_loader_creates_skills_and_interests(app):
    """Test that loader creates VolunteerSkill and VolunteerInterest records."""
    from flask_app.models import Volunteer
    from flask_app.models.contact.volunteer import VolunteerSkill, VolunteerInterest
    
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("008")
    payload["last_name"] = "Lovelace"
    payload["skills"] = {
        "volunteer_skills": ["Teaching", "Tutoring"],
    }
    payload["interests"] = {
        "volunteer_interests": ["Education", "Technology"],
    }
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    counters = loader.execute()
    
    assert counters.created == 1
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="008").first()
    assert entry is not None
    volunteer = db.session.get(Volunteer, entry.entity_id)
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


def test_loader_creates_addresses(app):
    """Test that loader creates ContactAddress records."""
    from flask_app.models import Volunteer
    from flask_app.models.contact.info import ContactAddress
    from flask_app.models.contact.enums import AddressType
    
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("009")
    payload["last_name"] = "Lovelace"
    payload["address"] = {
        "mailing": {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62701",
            "country": "US",
        },
    }
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    counters = loader.execute()
    
    assert counters.created == 1
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="009").first()
    assert entry is not None
    volunteer = db.session.get(Volunteer, entry.entity_id)
    assert volunteer is not None
    
    addresses = ContactAddress.query.filter_by(contact_id=volunteer.id).all()
    assert len(addresses) == 1  # Only mailing address available
    
    mailing = next((a for a in addresses if a.address_type == AddressType.MAILING), None)
    assert mailing is not None
    assert mailing.street_address_1 == "123 Main St"
    assert mailing.city == "Springfield"
    assert mailing.state == "IL"
    assert mailing.postal_code == "62701"
    assert mailing.country == "US"
    assert mailing.is_primary is True


def test_loader_applies_notes(app):
    """Test that loader applies notes fields."""
    from flask_app.models import Volunteer
    
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("010")
    payload["last_name"] = "Lovelace"
    payload["notes"] = {
        "description": "General description",
        "recruitment_notes": "Recruited at event",
    }
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    counters = loader.execute()
    
    assert counters.created == 1
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="010").first()
    assert entry is not None
    volunteer = db.session.get(Volunteer, entry.entity_id)
    assert volunteer is not None
    assert volunteer.notes == "General description"
    assert volunteer.internal_notes == "Recruited at event"


def test_loader_applies_engagement_fields(app):
    """Test that loader applies engagement fields."""
    from datetime import date
    from flask_app.models import Volunteer
    
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("011")
    payload["last_name"] = "Lovelace"
    payload["engagement"] = {
        "first_volunteer_date": "2024-01-15",
        "attended_sessions_count": 5,
    }
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    counters = loader.execute()
    
    assert counters.created == 1
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="011").first()
    assert entry is not None
    volunteer = db.session.get(Volunteer, entry.entity_id)
    assert volunteer is not None
    assert volunteer.first_volunteer_date == date(2024, 1, 15)
    
    # Check metadata
    metadata = entry.metadata_json or {}
    assert metadata.get("attended_sessions_count") == 5


def test_loader_handles_duplicate_skills(app):
    """Test that loader doesn't create duplicate skills."""
    from flask_app.models import Volunteer
    from flask_app.models.contact.volunteer import VolunteerSkill
    
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("012")
    payload["last_name"] = "Lovelace"
    payload["skills"] = {
        "volunteer_skills": ["Teaching"],
    }
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    loader.execute()
    
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="012").first()
    volunteer = db.session.get(Volunteer, entry.entity_id)
    
    # Verify skill was created
    skills_before = VolunteerSkill.query.filter_by(volunteer_id=volunteer.id).all()
    assert len(skills_before) == 1
    assert skills_before[0].skill_name == "Teaching"
    
    # Run loader again with same skill plus a new one
    run2 = _create_run()
    payload2 = _make_payload("012")
    payload2["last_name"] = "Lovelace"
    payload2["skills"] = {
        "volunteer_skills": ["Teaching", "Tutoring"],  # Teaching already exists, Tutoring is new
    }
    _add_staging_row(run2, 1, payload2)
    
    loader2 = SalesforceContactLoader(run2)
    loader2.execute()
    
    # Should only have 2 skills (Teaching already existed, Tutoring added)
    skills = VolunteerSkill.query.filter_by(volunteer_id=volunteer.id).all()
    assert len(skills) == 2
    skill_names = [s.skill_name for s in skills]
    assert "Teaching" in skill_names
    assert "Tutoring" in skill_names


def test_loader_updates_addresses(app):
    """Test that loader updates existing addresses instead of creating duplicates."""
    from flask_app.models import Volunteer
    from flask_app.models.contact.info import ContactAddress
    from flask_app.models.contact.enums import AddressType
    
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("013")
    payload["last_name"] = "Lovelace"
    payload["address"] = {
        "mailing": {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62701",
            "country": "US",
        },
    }
    _add_staging_row(run, 1, payload)
    
    loader = SalesforceContactLoader(run)
    loader.execute()
    
    entry = ExternalIdMap.query.filter_by(external_system="salesforce", external_id="013").first()
    volunteer = db.session.get(Volunteer, entry.entity_id)
    
    # Update address
    run2 = _create_run()
    payload2 = _make_payload("013")
    payload2["last_name"] = "Lovelace"
    payload2["address"] = {
        "mailing": {
            "street": "789 New St",  # Updated street
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62701",
            "country": "US",
        },
    }
    _add_staging_row(run2, 1, payload2)
    
    loader2 = SalesforceContactLoader(run2)
    loader2.execute()
    
    # Should still have only one mailing address, but updated
    addresses = ContactAddress.query.filter_by(contact_id=volunteer.id, address_type=AddressType.MAILING).all()
    assert len(addresses) == 1
    assert addresses[0].street_address_1 == "789 New St"


def test_loader_records_skip_for_duplicate_email(app):
    """Test that loader records ImportSkip when skipping duplicate email."""
    _ensure_watermark()
    
    # Create existing volunteer with email
    existing = Volunteer(first_name="Existing", last_name="Person")
    db.session.add(existing)
    db.session.flush()
    db.session.add(
        ContactEmail(
            contact_id=existing.id,
            email="duplicate@example.org",
            email_type=EmailType.PERSONAL,
            is_primary=True,
            is_verified=True,
        )
    )
    db.session.commit()
    
    # Create run with duplicate email
    run = _create_run()
    payload = _make_payload("dup-email-001")
    payload["last_name"] = "NewPerson"
    payload["email"] = "duplicate@example.org"
    _add_staging_row(run, 1, payload)
    
    # Promote to clean
    from flask_app.importer.pipeline.clean import promote_clean_volunteers
    promote_clean_volunteers(run, dry_run=False)
    db.session.commit()
    
    # Execute loader
    loader = SalesforceContactLoader(run)
    counters = loader.execute()
    db.session.commit()
    
    # Verify skip was recorded
    assert counters.unchanged == 1
    skip = ImportSkip.query.filter_by(run_id=run.id, skip_type=ImportSkipType.DUPLICATE_EMAIL).first()
    assert skip is not None
    assert skip.skip_type == ImportSkipType.DUPLICATE_EMAIL
    assert "duplicate@example.org" in skip.skip_reason.lower()
    assert skip.details_json["email"] == "duplicate@example.org"
    assert skip.staging_volunteer_id is not None
    # clean_volunteer_id may be None if using SimpleNamespace fallback
    # but should be set if clean volunteer was created
    if skip.clean_volunteer_id is not None:
        clean_vol = db.session.get(CleanVolunteer, skip.clean_volunteer_id)
        assert clean_vol is not None


def test_loader_records_skip_for_duplicate_name(app):
    """Test that loader records ImportSkip when skipping duplicate name."""
    _ensure_watermark()
    
    # Create existing volunteer with exact name
    existing = Volunteer(first_name="John", last_name="Doe")
    db.session.add(existing)
    db.session.commit()
    
    # Create run with duplicate name
    run = _create_run()
    payload = _make_payload("dup-name-001")
    payload["first_name"] = "John"
    payload["last_name"] = "Doe"
    payload["email"] = "newemail@example.org"
    _add_staging_row(run, 1, payload)
    
    # Promote to clean
    from flask_app.importer.pipeline.clean import promote_clean_volunteers
    promote_clean_volunteers(run, dry_run=False)
    db.session.commit()
    
    # Execute loader
    loader = SalesforceContactLoader(run)
    counters = loader.execute()
    db.session.commit()
    
    # Verify skip was recorded
    assert counters.unchanged == 1
    skip = ImportSkip.query.filter_by(run_id=run.id, skip_type=ImportSkipType.DUPLICATE_NAME).first()
    assert skip is not None
    assert skip.skip_type == ImportSkipType.DUPLICATE_NAME
    assert "John Doe" in skip.skip_reason
    assert skip.details_json["first_name"] == "John"
    assert skip.details_json["last_name"] == "Doe"
    assert skip.details_json["matched_volunteer_id"] == existing.id
    assert skip.staging_volunteer_id is not None
    # clean_volunteer_id may be None if using SimpleNamespace fallback
    # but should be set if clean volunteer was created
    if skip.clean_volunteer_id is not None:
        clean_vol = db.session.get(CleanVolunteer, skip.clean_volunteer_id)
        assert clean_vol is not None


