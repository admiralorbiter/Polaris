from __future__ import annotations

from datetime import datetime, timezone
from flask_app.importer.adapters.salesforce.extractor import SalesforceBatch
from flask_app.importer.pipeline.salesforce import ingest_salesforce_accounts
from flask_app.importer.pipeline.salesforce_organization_loader import SalesforceOrganizationLoader
from flask_app.models import ExternalIdMap, Organization
from flask_app.models.base import db
from flask_app.models.importer.schema import (
    ImportRun,
    ImportRunStatus,
    ImporterWatermark,
    StagingOrganization,
)


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
        ingest_params_json={"entity_type": "organizations"},
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _create_watermark() -> ImporterWatermark:
    watermark = ImporterWatermark(adapter="salesforce", object_name="accounts")
    db.session.add(watermark)
    db.session.commit()
    return db.session.get(ImporterWatermark, watermark.id)


def test_ingest_salesforce_accounts_persists_rows(app):
    """Test that organization ingestion persists staging rows correctly."""
    run = _create_run()
    watermark = _create_watermark()
    batches = [
        _make_batch(
            1,
            [
                {
                    "Id": "001",
                    "Name": "Test Org 1",
                    "Type": "Business",
                    "Description": "Test description",
                    "SystemModstamp": "2024-01-01T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-01T00:00:00.000Z",
                },
                {
                    "Id": "002",
                    "Name": "Test Org 2",
                    "Type": "Non-Profit",
                    "SystemModstamp": "2024-01-02T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-02T00:00:00.000Z",
                },
            ],
        ),
        _make_batch(
            2,
            [
                {
                    "Id": "003",
                    "Name": "Test Org 3",
                    "Type": "Government",
                    "SystemModstamp": "2024-01-03T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-03T00:00:00.000Z",
                },
            ],
        ),
    ]
    extractor = DummyExtractor(batches)

    summary = ingest_salesforce_accounts(
        import_run=run,
        extractor=extractor,
        watermark=watermark,
        staging_batch_size=2,
        dry_run=False,
        logger=app.logger,
        record_limit=None,
    )

    db.session.commit()
    db.session.refresh(run)

    assert summary.records_received == 3
    staged = StagingOrganization.query.order_by(StagingOrganization.sequence_number).all()
    assert len(staged) == 3
    
    # Verify first row normalization
    normalized = staged[0].normalized_json
    assert normalized["external_id"] == "001"
    assert normalized["name"] == "Test Org 1"
    assert normalized["organization_type"] == "business"
    assert normalized["description"] == "Test description"
    assert normalized["metadata"]["source_system"] == "salesforce"
    assert normalized["metadata"]["source_object"] == "Account"
    
    # Verify watermark was updated
    stored_modstamp = watermark.last_successful_modstamp
    assert stored_modstamp is not None
    assert stored_modstamp.replace(tzinfo=timezone.utc) == datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc)
    
    # Verify run counts
    counts = run.counts_json["staging"]["organizations"]
    assert counts["rows_staged"] == 3
    metrics = run.metrics_json["salesforce"]
    assert metrics["records_received"] == 3


def test_ingest_salesforce_accounts_dry_run(app):
    """Test that dry-run mode doesn't persist staging rows."""
    run = _create_run(dry_run=True)
    watermark = _create_watermark()
    batches = [
        _make_batch(
            1,
            [
                {
                    "Id": "001",
                    "Name": "Test Org",
                    "Type": "Business",
                    "SystemModstamp": "2024-01-01T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-01T00:00:00.000Z",
                },
            ],
        )
    ]
    extractor = DummyExtractor(batches)

    summary = ingest_salesforce_accounts(
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
    assert StagingOrganization.query.count() == 0
    assert watermark.last_successful_modstamp is None
    counts = run.counts_json["staging"]["organizations"]
    assert counts["rows_staged"] == 0
    assert counts["dry_run"] is True


def test_ingest_salesforce_accounts_normalizes_organization_type(app):
    """Test that organization type is normalized correctly."""
    run = _create_run()
    watermark = _create_watermark()
    batches = [
        _make_batch(
            1,
            [
                {
                    "Id": "001",
                    "Name": "Business Org",
                    "Type": "Business",
                    "SystemModstamp": "2024-01-01T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-01T00:00:00.000Z",
                },
                {
                    "Id": "002",
                    "Name": "Non-Profit Org",
                    "Type": "Non-Profit",
                    "SystemModstamp": "2024-01-01T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-01T00:00:00.000Z",
                },
                {
                    "Id": "003",
                    "Name": "Unknown Org",
                    "Type": "Unknown Type",
                    "SystemModstamp": "2024-01-01T00:00:00.000Z",
                    "LastModifiedDate": "2024-01-01T00:00:00.000Z",
                },
            ],
        ),
    ]
    extractor = DummyExtractor(batches)

    ingest_salesforce_accounts(
        import_run=run,
        extractor=extractor,
        watermark=watermark,
        staging_batch_size=10,
        dry_run=False,
        logger=app.logger,
        record_limit=None,
    )

    staged = StagingOrganization.query.order_by(StagingOrganization.sequence_number).all()
    assert len(staged) == 3
    
    # Verify type normalization
    assert staged[0].normalized_json["organization_type"] == "business"
    assert staged[1].normalized_json["organization_type"] == "non_profit"
    assert staged[2].normalized_json["organization_type"] == "other"  # Unknown type defaults to "other"


def test_ingest_salesforce_accounts_filters_excluded_types(app):
    """Test that excluded Account types are filtered in SOQL."""
    # Note: This test verifies the SOQL query includes the filter
    # The actual filtering happens in Salesforce, so we test by verifying
    # that the SOQL builder includes the WHERE clause
    from flask_app.importer.adapters.salesforce.extractor import build_accounts_soql
    
    soql = build_accounts_soql()
    assert "Type NOT IN ('Household', 'School District', 'School')" in soql
    assert "ORDER BY Name ASC" in soql

