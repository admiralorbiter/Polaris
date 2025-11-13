"""Tests for ImportSkipService."""

from datetime import datetime, timezone

from flask_app.importer.pipeline.skip_service import ImportSkipService, SkipSummary
from flask_app.models import db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus, ImportSkip, ImportSkipType, StagingVolunteer


def _create_run() -> ImportRun:
    run = ImportRun(
        source="test",
        adapter="test",
        status=ImportRunStatus.SUCCEEDED,
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _create_skip(run: ImportRun, skip_type: ImportSkipType, reason: str) -> ImportSkip:
    skip = ImportSkip(
        run_id=run.id,
        skip_type=skip_type,
        skip_reason=reason,
        entity_type="volunteer",
        record_key="Test Record",
        details_json={"test": "data"},
    )
    db.session.add(skip)
    db.session.commit()
    return skip


def test_skip_service_get_skips_for_run(app):
    """Test getting skips for a specific run."""
    run = _create_run()
    skip1 = _create_skip(run, ImportSkipType.DUPLICATE_EMAIL, "Duplicate email: test@example.com")
    skip2 = _create_skip(run, ImportSkipType.DUPLICATE_NAME, "Duplicate name: John Doe")
    
    service = ImportSkipService(db.session)
    skips = service.get_skips_for_run(run.id)
    
    assert len(skips) == 2
    skip_ids = {s.id for s in skips}
    assert skip1.id in skip_ids
    assert skip2.id in skip_ids


def test_skip_service_get_skips_for_run_with_filter(app):
    """Test getting skips for a run with type filter."""
    run = _create_run()
    _create_skip(run, ImportSkipType.DUPLICATE_EMAIL, "Duplicate email: test@example.com")
    skip2 = _create_skip(run, ImportSkipType.DUPLICATE_NAME, "Duplicate name: John Doe")
    
    service = ImportSkipService(db.session)
    skips = service.get_skips_for_run(run.id, skip_type=ImportSkipType.DUPLICATE_NAME)
    
    assert len(skips) == 1
    assert skips[0].id == skip2.id
    assert skips[0].skip_type == ImportSkipType.DUPLICATE_NAME


def test_skip_service_get_skip(app):
    """Test getting a single skip by ID."""
    run = _create_run()
    skip = _create_skip(run, ImportSkipType.DUPLICATE_EMAIL, "Duplicate email: test@example.com")
    
    service = ImportSkipService(db.session)
    retrieved = service.get_skip(skip.id)
    
    assert retrieved is not None
    assert retrieved.id == skip.id
    assert retrieved.skip_type == ImportSkipType.DUPLICATE_EMAIL


def test_skip_service_get_skip_summary(app):
    """Test getting skip summary for a run."""
    run = _create_run()
    _create_skip(run, ImportSkipType.DUPLICATE_EMAIL, "Duplicate email: test1@example.com")
    _create_skip(run, ImportSkipType.DUPLICATE_EMAIL, "Duplicate email: test2@example.com")
    _create_skip(run, ImportSkipType.DUPLICATE_NAME, "Duplicate name: John Doe")
    _create_skip(run, ImportSkipType.DUPLICATE_FUZZY, "Fuzzy match: Jane Doe")
    
    service = ImportSkipService(db.session)
    summary = service.get_skip_summary(run.id)
    
    assert isinstance(summary, SkipSummary)
    assert summary.total_skips == 4
    assert summary.by_type["duplicate_email"] == 2
    assert summary.by_type["duplicate_name"] == 1
    assert summary.by_type["duplicate_fuzzy"] == 1
    assert len(summary.by_reason) > 0


def test_skip_service_search_skips(app):
    """Test searching skips with filters."""
    run1 = _create_run()
    run2 = _create_run()
    
    skip1 = _create_skip(run1, ImportSkipType.DUPLICATE_EMAIL, "Duplicate email: test@example.com")
    _create_skip(run2, ImportSkipType.DUPLICATE_NAME, "Duplicate name: John Doe")
    
    service = ImportSkipService(db.session)
    skips, total = service.search_skips(run_id=run1.id)
    
    assert total == 1
    assert len(skips) == 1
    assert skips[0].id == skip1.id


def test_skip_service_search_skips_with_type_filter(app):
    """Test searching skips with type filter."""
    run = _create_run()
    _create_skip(run, ImportSkipType.DUPLICATE_EMAIL, "Duplicate email: test@example.com")
    skip2 = _create_skip(run, ImportSkipType.DUPLICATE_NAME, "Duplicate name: John Doe")
    
    service = ImportSkipService(db.session)
    skips, total = service.search_skips(run_id=run.id, skip_type=ImportSkipType.DUPLICATE_NAME)
    
    assert total == 1
    assert len(skips) == 1
    assert skips[0].id == skip2.id


def test_skip_service_search_skips_with_pagination(app):
    """Test searching skips with pagination."""
    run = _create_run()
    for i in range(5):
        _create_skip(run, ImportSkipType.DUPLICATE_EMAIL, f"Duplicate email: test{i}@example.com")
    
    service = ImportSkipService(db.session)
    skips, total = service.search_skips(run_id=run.id, limit=2, offset=0)
    
    assert total == 5
    assert len(skips) == 2
    
    skips_page2, total2 = service.search_skips(run_id=run.id, limit=2, offset=2)
    assert total2 == 5
    assert len(skips_page2) == 2
    # Verify different results
    assert {s.id for s in skips} != {s.id for s in skips_page2}

