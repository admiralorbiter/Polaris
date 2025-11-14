from __future__ import annotations

from datetime import datetime, timezone

from flask_app.importer.pipeline.salesforce_organization_loader import SalesforceOrganizationLoader
from flask_app.models import ExternalIdMap, Organization
from flask_app.models.base import db
from flask_app.models.importer.schema import (
    CleanOrganization,
    ImportRun,
    ImportRunStatus,
    ImportSkip,
    ImportSkipType,
    ImporterWatermark,
    StagingOrganization,
    StagingRecordStatus,
)


def _create_run() -> ImportRun:
    run = ImportRun(
        source="salesforce",
        adapter="salesforce",
        status=ImportRunStatus.RUNNING,
        ingest_params_json={"entity_type": "organizations"},
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _ensure_watermark():
    if not ImporterWatermark.query.filter_by(adapter="salesforce", object_name="accounts").first():
        watermark = ImporterWatermark(adapter="salesforce", object_name="accounts")
        db.session.add(watermark)
        db.session.commit()


def _make_payload(external_id: str, name: str = "Test Org", deleted: bool = False) -> dict:
    metadata = {
        "source_system": "salesforce",
        "source_object": "Account",
        "source_modstamp": "2024-01-01T00:00:00.000Z",
        "source_last_modified": "2024-01-01T00:00:00.000Z",
    }
    if deleted:
        metadata["core_state"] = "deleted"
    return {
        "external_id": external_id,
        "name": name,
        "organization_type": "business",
        "description": "Test description",
        "metadata": metadata,
    }


def _add_staging_row(run: ImportRun, seq: int, payload: dict) -> StagingOrganization:
    row = StagingOrganization(
        run_id=run.id,
        sequence_number=seq,
        source_record_id=f"SF-{payload['external_id']}",
        external_system="salesforce",
        external_id=payload["external_id"],
        payload_json={"Id": payload["external_id"], "Name": payload["name"]},
        normalized_json=payload,
        status=StagingRecordStatus.LANDED,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _add_clean_row(run: ImportRun, staging_row: StagingOrganization, payload: dict) -> CleanOrganization:
    from hashlib import sha256
    import json
    
    checksum = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    clean_row = CleanOrganization(
        run_id=run.id,
        staging_organization_id=staging_row.id,
        external_system="salesforce",
        external_id=payload["external_id"],
        name=payload["name"],
        checksum=checksum,
        payload_json=payload,
        promoted_at=datetime.now(timezone.utc),
    )
    clean_row.staging_row = staging_row
    db.session.add(clean_row)
    db.session.commit()
    return clean_row


def test_loader_creates_organization(app):
    """Test that loader creates Organization record."""
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("001", "Test Organization")
    staging_row = _add_staging_row(run, 1, payload)
    
    # Validate staging row (DQ would do this, but for tests we set it directly)
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()
    
    # Promote to clean
    from flask_app.importer.pipeline.clean import promote_clean_organizations
    promote_clean_organizations(run, dry_run=False)
    db.session.commit()
    
    # Execute loader
    loader = SalesforceOrganizationLoader(run)
    counters = loader.execute()
    
    assert counters.created == 1
    entry = ExternalIdMap.query.filter_by(
        external_system="salesforce",
        external_id="001",
        entity_type="salesforce_organization",
    ).first()
    assert entry is not None
    assert entry.is_active is True
    org = db.session.get(Organization, entry.entity_id)
    assert org is not None
    assert org.name == "Test Organization"
    assert org.organization_type.value == "business"
    assert org.description == "Test description"


def test_loader_updates_existing_organization(app):
    """Test that loader updates existing organization."""
    _ensure_watermark()
    
    # Create existing organization
    existing = Organization(name="Existing Org", slug="existing-org")
    db.session.add(existing)
    db.session.flush()
    
    # Create ExternalIdMap entry
    entry = ExternalIdMap(
        entity_type="salesforce_organization",
        entity_id=existing.id,
        external_system="salesforce",
        external_id="001",
        is_active=True,
    )
    db.session.add(entry)
    db.session.commit()
    
    # Create run with updated data
    run = _create_run()
    payload = _make_payload("001", "Updated Org Name")
    payload["description"] = "Updated description"
    staging_row = _add_staging_row(run, 1, payload)
    
    # Validate staging row
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()
    
    # Promote to clean
    from flask_app.importer.pipeline.clean import promote_clean_organizations
    promote_clean_organizations(run, dry_run=False)
    db.session.commit()
    
    # Execute loader
    loader = SalesforceOrganizationLoader(run)
    counters = loader.execute()
    
    assert counters.updated == 1
    db.session.refresh(existing)
    assert existing.name == "Updated Org Name"
    assert existing.description == "Updated description"


def test_loader_skips_duplicate_name(app):
    """Test that loader skips organizations with duplicate names."""
    _ensure_watermark()
    
    # Create existing organization
    existing = Organization(name="Duplicate Org", slug="duplicate-org")
    db.session.add(existing)
    db.session.commit()
    
    # Create run with duplicate name
    run = _create_run()
    payload = _make_payload("002", "Duplicate Org")  # Same name, different external_id
    staging_row = _add_staging_row(run, 1, payload)
    
    # Validate staging row
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()
    
    # Promote to clean
    from flask_app.importer.pipeline.clean import promote_clean_organizations
    promote_clean_organizations(run, dry_run=False)
    db.session.commit()
    
    # Execute loader
    loader = SalesforceOrganizationLoader(run)
    counters = loader.execute()
    
    assert counters.unchanged == 1
    skip = ImportSkip.query.filter_by(
        run_id=run.id,
        skip_type=ImportSkipType.DUPLICATE_NAME,
    ).first()
    assert skip is not None
    assert skip.skip_type == ImportSkipType.DUPLICATE_NAME
    assert "Duplicate Org" in skip.skip_reason
    assert skip.details_json["name"] == "Duplicate Org"
    assert skip.details_json["matched_organization_id"] == existing.id
    assert skip.staging_organization_id is not None


def test_loader_handles_missing_name(app):
    """Test that loader skips organizations with missing names."""
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("001", "")
    payload["name"] = ""  # Empty name
    staging_row = _add_staging_row(run, 1, payload)
    
    # Note: Empty name should fail DQ, but for this test we'll validate it anyway
    # to test the loader's handling of missing names
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()
    
    # Promote to clean (will skip due to missing name)
    from flask_app.importer.pipeline.clean import promote_clean_organizations
    promote_clean_organizations(run, dry_run=False)
    db.session.commit()
    
    # Execute loader
    loader = SalesforceOrganizationLoader(run)
    counters = loader.execute()
    
    assert counters.unchanged == 1
    skip = ImportSkip.query.filter_by(
        run_id=run.id,
        skip_type=ImportSkipType.MISSING_REQUIRED_FIELD,
    ).first()
    assert skip is not None
    assert "name" in skip.skip_reason.lower()


def test_loader_normalizes_organization_type(app):
    """Test that loader correctly maps organization type enum values."""
    _ensure_watermark()
    run = _create_run()
    
    test_cases = [
        ("001", "business", "business"),
        ("002", "non_profit", "non_profit"),
        ("003", "government", "government"),
        ("004", "school", "school"),
        ("005", "other", "other"),
    ]
    
    staging_rows = []
    for external_id, org_type, expected_enum in test_cases:
        payload = _make_payload(external_id, f"Org {external_id}")
        payload["organization_type"] = org_type
        staging_row = _add_staging_row(run, int(external_id), payload)
        staging_row.status = StagingRecordStatus.VALIDATED
        staging_rows.append(staging_row)
    db.session.commit()
    
    # Promote to clean
    from flask_app.importer.pipeline.clean import promote_clean_organizations
    promote_clean_organizations(run, dry_run=False)
    db.session.commit()
    
    # Execute loader
    loader = SalesforceOrganizationLoader(run)
    counters = loader.execute()
    
    assert counters.created == 5
    
    # Verify organization types
    for external_id, _, expected_enum in test_cases:
        entry = ExternalIdMap.query.filter_by(
            external_system="salesforce",
            external_id=external_id,
        ).first()
        assert entry is not None
        org = db.session.get(Organization, entry.entity_id)
        assert org is not None
        assert org.organization_type.value == expected_enum


def test_loader_advances_watermark(app):
    """Test that loader advances watermark after successful load."""
    _ensure_watermark()
    run = _create_run()
    payload = _make_payload("001", "Test Org")
    staging_row = _add_staging_row(run, 1, payload)
    
    # Validate staging row
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()
    
    # Promote to clean
    from flask_app.importer.pipeline.clean import promote_clean_organizations
    promote_clean_organizations(run, dry_run=False)
    db.session.commit()
    
    # Execute loader
    loader = SalesforceOrganizationLoader(run)
    counters = loader.execute()
    
    # Verify watermark was advanced
    watermark = ImporterWatermark.query.filter_by(
        adapter="salesforce",
        object_name="accounts",
    ).first()
    assert watermark is not None
    assert watermark.last_successful_modstamp is not None
    assert watermark.last_run_id == run.id


def test_loader_handles_no_change(app):
    """Test that loader detects when organization hasn't changed."""
    _ensure_watermark()
    
    # Create existing organization
    existing = Organization(name="Existing Org", slug="existing-org")
    db.session.add(existing)
    db.session.flush()
    
    # Create ExternalIdMap with payload hash
    from hashlib import sha256
    import json
    
    payload = _make_payload("001", "Existing Org")
    payload_hash = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    
    entry = ExternalIdMap(
        entity_type="salesforce_organization",
        entity_id=existing.id,
        external_system="salesforce",
        external_id="001",
        is_active=True,
        metadata_json={"payload_hash": payload_hash},
    )
    db.session.add(entry)
    db.session.commit()
    
    # Create run with same payload (no change)
    run = _create_run()
    staging_row = _add_staging_row(run, 1, payload)
    
    # Validate staging row
    staging_row.status = StagingRecordStatus.VALIDATED
    db.session.commit()
    
    # Promote to clean
    from flask_app.importer.pipeline.clean import promote_clean_organizations
    promote_clean_organizations(run, dry_run=False)
    db.session.commit()
    
    # Execute loader
    loader = SalesforceOrganizationLoader(run)
    counters = loader.execute()
    
    assert counters.unchanged == 1

