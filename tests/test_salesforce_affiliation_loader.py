from __future__ import annotations

from datetime import date, datetime, timezone

from flask_app.importer.pipeline.salesforce_affiliation_loader import SalesforceAffiliationLoader
from flask_app.models import Contact, ExternalIdMap, Organization
from flask_app.models.base import db
from flask_app.models.contact.relationships import ContactOrganization
from flask_app.models.importer.schema import (
    CleanAffiliation,
    ImporterWatermark,
    ImportRun,
    ImportRunStatus,
    ImportSkip,
    ImportSkipType,
    StagingAffiliation,
    StagingRecordStatus,
)


def _create_run() -> ImportRun:
    run = ImportRun(
        source="salesforce",
        adapter="salesforce",
        status=ImportRunStatus.RUNNING,
        ingest_params_json={"entity_type": "affiliations"},
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _ensure_watermark():
    if not ImporterWatermark.query.filter_by(adapter="salesforce", object_name="affiliations").first():
        watermark = ImporterWatermark(adapter="salesforce", object_name="affiliations")
        db.session.add(watermark)
        db.session.commit()


def _create_contact_and_map(contact_external_id: str) -> tuple[Contact, ExternalIdMap]:
    """Create a Contact and ExternalIdMap entry for testing."""
    from flask_app.models import ContactEmail
    from flask_app.models.contact.enums import EmailType
    
    contact = Contact(
        first_name="Test",
        last_name="Contact",
    )
    db.session.add(contact)
    db.session.flush()
    
    # Create email via ContactEmail relationship
    email = ContactEmail(
        contact_id=contact.id,
        email=f"test{contact_external_id}@example.com",
        email_type=EmailType.PERSONAL,
        is_primary=True,
    )
    db.session.add(email)

    map_entry = ExternalIdMap(
        entity_type="salesforce_contact",
        entity_id=contact.id,
        external_system="salesforce",
        external_id=contact_external_id,
        is_active=True,
    )
    db.session.add(map_entry)
    db.session.commit()
    return contact, map_entry


def _create_organization_and_map(org_external_id: str) -> tuple[Organization, ExternalIdMap]:
    """Create an Organization and ExternalIdMap entry for testing."""
    from flask_app.models.contact.enums import OrganizationType

    org = Organization(
        name=f"Test Org {org_external_id}",
        slug=f"test-org-{org_external_id}",
        organization_type=OrganizationType.BUSINESS,
        is_active=True,
    )
    db.session.add(org)
    db.session.flush()

    map_entry = ExternalIdMap(
        entity_type="salesforce_organization",
        entity_id=org.id,
        external_system="salesforce",
        external_id=org_external_id,
        is_active=True,
    )
    db.session.add(map_entry)
    db.session.commit()
    return org, map_entry


def _make_payload(
    external_id: str,
    contact_external_id: str,
    organization_external_id: str,
    is_primary: bool = False,
    status: str = "Current",
    deleted: bool = False,
) -> dict:
    metadata = {
        "source_system": "salesforce",
        "source_object": "npe5__Affiliation__c",
        "source_modstamp": "2024-01-01T00:00:00.000Z",
        "source_last_modified": "2024-01-01T00:00:00.000Z",
        "status": status,
        "role": "Member",
    }
    if deleted:
        metadata["core_state"] = "IsDeleted"
    return {
        "external_id": external_id,
        "contact_external_id": contact_external_id,
        "organization_external_id": organization_external_id,
        "is_primary": is_primary,
        "start_date": "2022-01-27",
        "end_date": None if status == "Current" else "2024-01-01",
        "metadata": metadata,
    }


def _add_staging_row(run: ImportRun, seq: int, payload: dict) -> StagingAffiliation:
    row = StagingAffiliation(
        run_id=run.id,
        sequence_number=seq,
        source_record_id=f"SF-{payload['external_id']}",
        external_system="salesforce",
        external_id=payload["external_id"],
        payload_json={
            "Id": payload["external_id"],
            "npe5__Contact__c": payload["contact_external_id"],
            "npe5__Organization__c": payload["organization_external_id"],
            "npe5__Primary__c": payload.get("is_primary", False),
            "npe5__Status__c": payload.get("metadata", {}).get("status", "Current"),
            "npe5__StartDate__c": payload.get("start_date"),
            "npe5__EndDate__c": payload.get("end_date"),
            "SystemModstamp": "2024-01-01T00:00:00.000Z",
        },
        normalized_json=payload,
        status=StagingRecordStatus.LANDED,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _add_clean_row(run: ImportRun, staging_row: StagingAffiliation, payload: dict) -> CleanAffiliation:
    import json
    from hashlib import sha256

    checksum = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    clean_row = CleanAffiliation(
        run_id=run.id,
        staging_affiliation_id=staging_row.id,
        external_system="salesforce",
        external_id=payload["external_id"],
        contact_external_id=payload["contact_external_id"],
        organization_external_id=payload["organization_external_id"],
        checksum=checksum,
        payload_json=payload,
        promoted_at=datetime.now(timezone.utc),
    )
    clean_row.staging_row = staging_row
    db.session.add(clean_row)
    db.session.commit()
    return clean_row


def test_loader_creates_affiliation(app):
    """Test that loader creates ContactOrganization record."""
    _ensure_watermark()
    run = _create_run()

    # Create contact and organization with ExternalIdMap entries
    contact, _ = _create_contact_and_map("0035f00000HYEfOAAX")
    org, _ = _create_organization_and_map("0015f00000JUL8sAAH")

    payload = _make_payload(
        "a0H5f000006S0G4EAK",
        "0035f00000HYEfOAAX",
        "0015f00000JUL8sAAH",
        is_primary=True,
    )
    staging_row = _add_staging_row(run, 1, payload)
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    clean_row = _add_clean_row(run, staging_row, payload)

    loader = SalesforceAffiliationLoader(run)
    counters = loader.execute()

    assert counters.created == 1
    assert counters.updated == 0
    assert counters.unchanged == 0

    # Verify ContactOrganization was created
    contact_org = ContactOrganization.query.filter_by(
        contact_id=contact.id,
        organization_id=org.id,
    ).first()
    assert contact_org is not None
    assert contact_org.is_primary is True
    assert contact_org.start_date == date(2022, 1, 27)
    assert contact_org.end_date is None

    # Verify ExternalIdMap entry
    map_entry = ExternalIdMap.query.filter_by(
        external_system="salesforce",
        external_id="a0H5f000006S0G4EAK",
        entity_type="salesforce_affiliation",
    ).first()
    assert map_entry is not None
    assert map_entry.entity_id == contact_org.id


def test_loader_skips_missing_contact(app):
    """Test that loader skips affiliation when contact is missing."""
    _ensure_watermark()
    run = _create_run()

    # Create organization but not contact
    org, _ = _create_organization_and_map("0015f00000JUL8sAAH")

    payload = _make_payload(
        "a0H5f000006S0G4EAK",
        "0035f00000MISSING",  # Contact doesn't exist
        "0015f00000JUL8sAAH",
    )
    staging_row = _add_staging_row(run, 1, payload)
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    clean_row = _add_clean_row(run, staging_row, payload)

    loader = SalesforceAffiliationLoader(run)
    counters = loader.execute()

    assert counters.skipped == 1
    assert counters.created == 0

    # Verify ImportSkip was created
    skip = ImportSkip.query.filter_by(
        run_id=run.id,
        skip_type=ImportSkipType.MISSING_REFERENCE,
    ).first()
    assert skip is not None
    assert "Contact not found" in skip.skip_reason


def test_loader_skips_missing_organization(app):
    """Test that loader skips affiliation when organization is missing."""
    _ensure_watermark()
    run = _create_run()

    # Create contact but not organization
    contact, _ = _create_contact_and_map("0035f00000HYEfOAAX")

    payload = _make_payload(
        "a0H5f000006S0G4EAK",
        "0035f00000HYEfOAAX",
        "0015f00000MISSING",  # Organization doesn't exist
    )
    staging_row = _add_staging_row(run, 1, payload)
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    clean_row = _add_clean_row(run, staging_row, payload)

    loader = SalesforceAffiliationLoader(run)
    counters = loader.execute()

    assert counters.skipped == 1
    assert counters.created == 0

    # Verify ImportSkip was created
    skip = ImportSkip.query.filter_by(
        run_id=run.id,
        skip_type=ImportSkipType.MISSING_REFERENCE,
    ).first()
    assert skip is not None
    assert "Organization not found" in skip.skip_reason


def test_loader_updates_existing_affiliation(app):
    """Test that loader updates existing ContactOrganization record."""
    _ensure_watermark()
    run = _create_run()

    contact, _ = _create_contact_and_map("0035f00000HYEfOAAX")
    org, _ = _create_organization_and_map("0015f00000JUL8sAAH")

    # Create existing ContactOrganization
    contact_org = ContactOrganization(
        contact_id=contact.id,
        organization_id=org.id,
        is_primary=False,
        start_date=date(2020, 1, 1),
    )
    db.session.add(contact_org)
    db.session.flush()

    # Create ExternalIdMap entry
    map_entry = ExternalIdMap(
        entity_type="salesforce_affiliation",
        entity_id=contact_org.id,
        external_system="salesforce",
        external_id="a0H5f000006S0G4EAK",
        is_active=True,
        metadata_json={"payload_hash": "old_hash"},
    )
    db.session.add(map_entry)
    db.session.commit()

    # Create new payload with changes
    payload = _make_payload(
        "a0H5f000006S0G4EAK",
        "0035f00000HYEfOAAX",
        "0015f00000JUL8sAAH",
        is_primary=True,  # Changed
    )
    staging_row = _add_staging_row(run, 1, payload)
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    clean_row = _add_clean_row(run, staging_row, payload)

    loader = SalesforceAffiliationLoader(run)
    counters = loader.execute()

    assert counters.updated == 1
    assert counters.created == 0

    # Verify ContactOrganization was updated
    db.session.refresh(contact_org)
    assert contact_org.is_primary is True


def test_loader_handles_primary_flag(app):
    """Test that loader deactivates other primary affiliations when setting one as primary."""
    _ensure_watermark()
    run = _create_run()

    contact, _ = _create_contact_and_map("0035f00000HYEfOAAX")
    org1, _ = _create_organization_and_map("0015f00000JUL8sAAH")
    org2, _ = _create_organization_and_map("0015f00000JUL8tAAH")

    # Create existing primary affiliation
    existing_primary = ContactOrganization(
        contact_id=contact.id,
        organization_id=org1.id,
        is_primary=True,
        start_date=date(2020, 1, 1),
    )
    db.session.add(existing_primary)
    db.session.commit()

    # Create new primary affiliation
    payload = _make_payload(
        "a0H5f000006S0G5EAK",
        "0035f00000HYEfOAAX",
        "0015f00000JUL8tAAH",
        is_primary=True,
    )
    staging_row = _add_staging_row(run, 1, payload)
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    clean_row = _add_clean_row(run, staging_row, payload)

    loader = SalesforceAffiliationLoader(run)
    counters = loader.execute()

    assert counters.created == 1

    # Verify old primary was deactivated
    db.session.refresh(existing_primary)
    assert existing_primary.is_primary is False

    # Verify new one is primary
    new_contact_org = ContactOrganization.query.filter_by(
        contact_id=contact.id,
        organization_id=org2.id,
    ).first()
    assert new_contact_org.is_primary is True


def test_loader_handles_status_change(app):
    """Test that loader sets end_date when status changes from Current to Past."""
    _ensure_watermark()
    run = _create_run()

    contact, _ = _create_contact_and_map("0035f00000HYEfOAAX")
    org, _ = _create_organization_and_map("0015f00000JUL8sAAH")

    # Create existing affiliation with Current status
    contact_org = ContactOrganization(
        contact_id=contact.id,
        organization_id=org.id,
        is_primary=False,
        start_date=date(2022, 1, 27),
        end_date=None,  # Current
    )
    db.session.add(contact_org)
    db.session.flush()

    map_entry = ExternalIdMap(
        entity_type="salesforce_affiliation",
        entity_id=contact_org.id,
        external_system="salesforce",
        external_id="a0H5f000006S0G4EAK",
        is_active=True,
        metadata_json={"payload_hash": "old_hash", "status": "Current"},
    )
    db.session.add(map_entry)
    db.session.commit()

    # Update with Past status (without end_date so loader sets it to today)
    payload = _make_payload(
        "a0H5f000006S0G4EAK",
        "0035f00000HYEfOAAX",
        "0015f00000JUL8sAAH",
        status="Past",
    )
    # Remove end_date from payload to test that loader sets it automatically
    payload["end_date"] = None
    # Also update the normalized_json in staging row
    staging_row = _add_staging_row(run, 1, payload)
    staging_row.normalized_json = payload
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()

    clean_row = _add_clean_row(run, staging_row, payload)

    loader = SalesforceAffiliationLoader(run)
    counters = loader.execute()

    assert counters.updated == 1

    # Verify end_date was set
    db.session.refresh(contact_org)
    assert contact_org.end_date is not None
    assert contact_org.end_date == date.today()
