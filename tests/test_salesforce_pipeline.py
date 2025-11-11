from __future__ import annotations

from datetime import datetime, timezone
from flask_app.importer.adapters.salesforce.extractor import SalesforceBatch
from flask_app.importer.pipeline.salesforce import ingest_salesforce_contacts
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
    db.session.commit()

    assert summary.records_received == 3
    staged = StagingVolunteer.query.order_by(StagingVolunteer.sequence_number).all()
    assert len(staged) == 3
    assert staged[0].normalized_json["first_name"] == "Ada"
    stored_modstamp = watermark.last_successful_modstamp
    assert stored_modstamp is not None
    assert stored_modstamp.replace(tzinfo=timezone.utc) == datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc)
    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_staged"] == 3
    metrics = run.metrics_json["salesforce"]
    assert metrics["records_received"] == 3


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

    assert summary.records_staged == 0
    assert StagingVolunteer.query.count() == 0
    assert watermark.last_successful_modstamp is None
    counts = run.counts_json["staging"]["volunteers"]
    assert counts["rows_staged"] == 0
    assert counts["dry_run"] is True

