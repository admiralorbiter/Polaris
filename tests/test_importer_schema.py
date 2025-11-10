import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from flask_app.models import (
    ChangeLogEntry,
    DataQualitySeverity,
    DataQualityStatus,
    DataQualityViolation,
    DedupeDecision,
    DedupeSuggestion,
    ExternalIdMap,
    ImportRun,
    ImportRunStatus,
    MergeLog,
    StagingRecordStatus,
    StagingVolunteer,
    Volunteer,
    db,
)


def test_importer_tables_created(app):
    """Ensure importer tables are part of the base schema creation."""
    inspector = inspect(db.engine)
    expected_tables = {
        "import_runs",
        "staging_volunteers",
        "clean_volunteers",
        "dq_violations",
        "dedupe_suggestions",
        "external_id_map",
        "merge_log",
        "change_log",
    }
    missing = {table for table in expected_tables if not inspector.has_table(table)}
    assert not missing, f"Importer tables missing: {missing}"


def test_importer_model_roundtrip(app):
    """Insert sample importer records and verify relationships and constraints."""
    run = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.PENDING,
        dry_run=True,
    )
    volunteer_primary = Volunteer(first_name="Alex", last_name="Primary")
    volunteer_candidate = Volunteer(first_name="Casey", last_name="Candidate")

    db.session.add_all([run, volunteer_primary, volunteer_candidate])
    db.session.commit()

    staging_row = StagingVolunteer(
        import_run=run,
        sequence_number=1,
        source_record_id="row-1",
        external_system="csv",
        external_id="ext-1",
        payload_json={"raw": {"first_name": "Alex"}},
        normalized_json={"first_name": "Alex"},
        checksum="abc123",
        status=StagingRecordStatus.LANDED,
    )

    db.session.add(staging_row)
    db.session.flush()

    violation = DataQualityViolation(
        run_id=run.id,
        staging_volunteer_id=staging_row.id,
        rule_code="REQ-001",
        severity=DataQualitySeverity.ERROR,
        status=DataQualityStatus.OPEN,
        message="Email required",
        details_json={"field": "email"},
    )

    suggestion = DedupeSuggestion(
        run_id=run.id,
        staging_volunteer_id=staging_row.id,
        primary_contact_id=volunteer_primary.id,
        candidate_contact_id=volunteer_candidate.id,
        score=0.95,
        match_type="email",
        confidence_score=0.95,
        features_json={"email": 1.0},
        decision=DedupeDecision.PENDING,
    )

    id_map = ExternalIdMap(
        run_id=run.id,
        entity_type="volunteer",
        entity_id=volunteer_primary.id,
        external_system="csv",
        external_id="ext-1",
    )

    merge = MergeLog(
        run_id=run.id,
        primary_contact_id=volunteer_primary.id,
        merged_contact_id=volunteer_candidate.id,
        decision_type="manual",
        reason="Exact email match",
        snapshot_before={"candidate": {"email": "old@example.com"}},
        snapshot_after={"primary": {"email": "new@example.com"}},
    )

    change = ChangeLogEntry(
        run_id=run.id,
        entity_type="volunteer",
        entity_id=volunteer_primary.id,
        field_name="email",
        old_value=None,
        new_value="new@example.com",
        change_source="importer",
    )

    db.session.add(violation)
    db.session.add(suggestion)
    db.session.add(id_map)
    db.session.add(merge)
    db.session.add(change)
    db.session.commit()

    db.session.refresh(run)
    db.session.refresh(id_map)
    db.session.refresh(staging_row)

    # Relationships resolve correctly
    assert run.staging_rows[0] is staging_row
    assert staging_row.import_run is run
    assert run.dq_violations[0].rule_code == "REQ-001"
    assert staging_row.dq_violations[0].rule_code == "REQ-001"
    assert run.dedupe_suggestions[0].primary_contact_id == volunteer_primary.id
    assert run.external_ids[0].external_id == "ext-1"
    assert run.merge_events[0].primary_contact_id == volunteer_primary.id
    assert run.change_events[0].field_name == "email"

    # Unique constraint enforcement on external_id_map
    duplicate_id_map = ExternalIdMap(
        run_id=run.id,
        entity_type="volunteer",
        entity_id=volunteer_primary.id,
        external_system="csv",
        external_id="ext-1",
    )
    db.session.add(duplicate_id_map)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    # Soft delete lifecycle keeps history without hard deletes
    assert id_map.is_active
    assert id_map.deactivated_at is None
    assert id_map.upstream_deleted_reason is None

    id_map.soft_delete(reason="Removed upstream")
    db.session.commit()

    assert not id_map.is_active
    assert id_map.deactivated_at is not None
    assert id_map.upstream_deleted_reason == "Removed upstream"

    id_map.mark_seen(run_id=run.id)
    db.session.commit()

    assert id_map.is_active
    assert id_map.deactivated_at is None
    assert id_map.upstream_deleted_reason is None

    # Check constraint on change logs (field_name cannot be empty)
    empty_field_change = ChangeLogEntry(
        run_id=run.id,
        entity_type="volunteer",
        entity_id=volunteer_primary.id,
        field_name="",
        old_value="old@example.com",
        new_value="new@example.com",
    )
    db.session.add(empty_field_change)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
