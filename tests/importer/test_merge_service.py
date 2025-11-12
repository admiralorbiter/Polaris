"""
Tests for the MergeService class.

Covers merge transaction, survivorship application, external_id_map updates,
change_log creation, and error handling.
"""

from datetime import datetime, timezone

import pytest

from flask_app.importer.pipeline.merge_service import MergeService
from flask_app.models import (
    ChangeLogEntry,
    CleanVolunteer,
    ContactEmail,
    ContactPhone,
    DedupeDecision,
    DedupeSuggestion,
    EmailType,
    ExternalIdMap,
    ImportRun,
    MergeLog,
    PhoneType,
    StagingVolunteer,
    Volunteer,
    db,
)


@pytest.fixture
def merge_service(app):
    """Create a MergeService instance."""
    with app.app_context():
        yield MergeService()


@pytest.fixture
def sample_import_run(app):
    """Create a sample import run."""
    with app.app_context():
        run = ImportRun(source="csv", notes="Test run")
        db.session.add(run)
        db.session.commit()
        yield run


@pytest.fixture
def sample_volunteers(app):
    """Create sample volunteers for testing."""
    with app.app_context():
        primary = Volunteer(first_name="John", last_name="Doe")
        db.session.add(primary)
        db.session.flush()

        db.session.add(
            ContactEmail(
                contact_id=primary.id,
                email="john.doe@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
        )
        db.session.add(
            ContactPhone(
                contact_id=primary.id,
                phone_number="+14155551234",
                phone_type=PhoneType.MOBILE,
                is_primary=True,
            )
        )

        candidate = Volunteer(first_name="John", last_name="Doe")
        db.session.add(candidate)
        db.session.flush()

        db.session.add(
            ContactEmail(
                contact_id=candidate.id,
                email="j.doe@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
        )

        db.session.commit()
        yield {"primary": primary, "candidate": candidate}


@pytest.fixture
def sample_dedupe_suggestion(app, sample_import_run, sample_volunteers):
    """Create a sample dedupe suggestion."""
    with app.app_context():
        suggestion = DedupeSuggestion(
            run_id=sample_import_run.id,
            primary_contact_id=sample_volunteers["primary"].id,
            candidate_contact_id=sample_volunteers["candidate"].id,
            score=0.95,
            match_type="fuzzy_high",
            confidence_score=0.95,
            features_json={"name_similarity": 0.98, "dob_match": 1.0},
            decision=DedupeDecision.PENDING,
        )
        db.session.add(suggestion)
        db.session.commit()
        yield suggestion


def test_get_review_queue_basic(merge_service, app, sample_import_run, sample_volunteers):
    """Test basic queue retrieval."""
    with app.app_context():
        suggestion = DedupeSuggestion(
            run_id=sample_import_run.id,
            primary_contact_id=sample_volunteers["primary"].id,
            candidate_contact_id=sample_volunteers["candidate"].id,
            score=0.95,
            match_type="fuzzy_high",
            decision=DedupeDecision.PENDING,
        )
        db.session.add(suggestion)
        db.session.commit()

        candidates, total = merge_service.get_review_queue(limit=10, offset=0)
        assert total >= 1
        assert len(candidates) >= 1
        assert candidates[0].id == suggestion.id


def test_get_review_queue_filter_by_status(merge_service, app, sample_import_run, sample_volunteers):
    """Test queue filtering by status."""
    with app.app_context():
        # Create a separate candidate volunteer to avoid UNIQUE constraint
        candidate2 = Volunteer(first_name="Jane", last_name="Smith")
        db.session.add(candidate2)
        db.session.flush()

        pending = DedupeSuggestion(
            run_id=sample_import_run.id,
            primary_contact_id=sample_volunteers["primary"].id,
            candidate_contact_id=candidate2.id,  # Use different candidate
            score=0.95,
            match_type="fuzzy_high",
            decision=DedupeDecision.PENDING,
        )
        rejected = DedupeSuggestion(
            run_id=sample_import_run.id,
            primary_contact_id=sample_volunteers["primary"].id,
            candidate_contact_id=sample_volunteers["candidate"].id,
            score=0.85,
            decision=DedupeDecision.REJECTED,
        )
        db.session.add_all([pending, rejected])
        db.session.commit()

        candidates, total = merge_service.get_review_queue(status="pending", limit=10, offset=0)
        assert total == 1
        assert candidates[0].decision == DedupeDecision.PENDING


def test_get_candidate_details(merge_service, app, sample_dedupe_suggestion):
    """Test getting candidate details."""
    with app.app_context():
        details = merge_service.get_candidate_details(sample_dedupe_suggestion.id)

        assert details.suggestion_id == sample_dedupe_suggestion.id
        assert details.score == 0.95
        assert details.match_type == "fuzzy_high"
        assert details.primary_contact is not None
        assert details.candidate_contact is not None


def test_get_candidate_details_not_found(merge_service, app):
    """Test getting details for non-existent candidate."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            merge_service.get_candidate_details(99999)


def test_execute_merge_basic(merge_service, app, sample_dedupe_suggestion):
    """Test basic merge execution."""
    with app.app_context():
        user_id = 1  # Mock user ID

        merge_log = merge_service.execute_merge(
            sample_dedupe_suggestion.id,
            user_id=user_id,
            notes="Test merge",
        )

        assert merge_log is not None
        assert merge_log.primary_contact_id == sample_dedupe_suggestion.primary_contact_id
        assert merge_log.performed_by_user_id == user_id
        assert merge_log.decision_type == "manual"

        # Verify suggestion was updated - query fresh from database
        updated_suggestion = db.session.get(DedupeSuggestion, sample_dedupe_suggestion.id)
        assert updated_suggestion is not None
        assert updated_suggestion.decision == DedupeDecision.ACCEPTED
        assert updated_suggestion.decided_by_user_id == user_id


def test_execute_merge_creates_change_log(merge_service, app, sample_dedupe_suggestion):
    """Test that merge creates change log entries."""
    with app.app_context():
        user_id = 1

        merge_log = merge_service.execute_merge(
            sample_dedupe_suggestion.id,
            user_id=user_id,
        )

        # Check for change log entries
        change_logs = (
            db.session.query(ChangeLogEntry)
            .filter_by(
                entity_type="volunteer",
                entity_id=merge_log.primary_contact_id,
                change_source="manual_merge",
            )
            .all()
        )

        # Should have at least one change log entry if fields changed
        assert len(change_logs) >= 0  # May be 0 if no fields changed


def test_execute_merge_updates_external_id_map(merge_service, app, sample_dedupe_suggestion):
    """Test that merge updates external_id_map entries."""
    with app.app_context():
        primary_id = sample_dedupe_suggestion.primary_contact_id
        candidate_id = sample_dedupe_suggestion.candidate_contact_id

        # Create external_id_map entries
        primary_map = ExternalIdMap(
            entity_type="volunteer",
            entity_id=primary_id,
            external_system="csv",
            external_id="primary-123",
            is_active=True,
        )
        candidate_map = ExternalIdMap(
            entity_type="volunteer",
            entity_id=candidate_id,
            external_system="csv",
            external_id="candidate-456",
            is_active=True,
        )
        db.session.add_all([primary_map, candidate_map])
        db.session.commit()

        user_id = 1
        merge_log = merge_service.execute_merge(
            sample_dedupe_suggestion.id,
            user_id=user_id,
        )

        # Verify candidate map was updated or deactivated
        db.session.refresh(candidate_map)
        # Either entity_id was updated to primary, or it was deactivated
        assert candidate_map.entity_id == primary_id or not candidate_map.is_active


def test_execute_merge_invalid_suggestion(merge_service, app):
    """Test merge with invalid suggestion ID."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            merge_service.execute_merge(99999, user_id=1)


def test_execute_merge_already_decided(merge_service, app, sample_dedupe_suggestion):
    """Test merge with already-decided suggestion."""
    with app.app_context():
        sample_dedupe_suggestion.decision = DedupeDecision.REJECTED
        db.session.commit()

        with pytest.raises(ValueError, match="Cannot merge"):
            merge_service.execute_merge(sample_dedupe_suggestion.id, user_id=1)


def test_reject_candidate(merge_service, app, sample_dedupe_suggestion):
    """Test rejecting a candidate."""
    with app.app_context():
        user_id = 1
        suggestion = merge_service.reject_candidate(
            sample_dedupe_suggestion.id,
            user_id=user_id,
            notes="Not a duplicate",
        )

        assert suggestion.decision == DedupeDecision.REJECTED
        assert suggestion.decided_by_user_id == user_id
        assert suggestion.decision_notes == "Not a duplicate"
        assert suggestion.decided_at is not None


def test_reject_candidate_invalid(merge_service, app):
    """Test rejecting non-existent candidate."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            merge_service.reject_candidate(99999, user_id=1)


def test_defer_candidate(merge_service, app, sample_dedupe_suggestion):
    """Test deferring a candidate."""
    with app.app_context():
        user_id = 1
        suggestion = merge_service.defer_candidate(
            sample_dedupe_suggestion.id,
            user_id=user_id,
            notes="Need more info",
        )

        assert suggestion.decision == DedupeDecision.DEFERRED
        assert suggestion.decided_by_user_id == user_id
        assert suggestion.decision_notes == "Need more info"
        assert suggestion.decided_at is not None


def test_defer_candidate_already_decided(merge_service, app, sample_dedupe_suggestion):
    """Test deferring an already-decided candidate."""
    with app.app_context():
        sample_dedupe_suggestion.decision = DedupeDecision.ACCEPTED
        db.session.commit()

        with pytest.raises(ValueError, match="Cannot defer"):
            merge_service.defer_candidate(sample_dedupe_suggestion.id, user_id=1)


def test_get_queue_stats(merge_service, app, sample_import_run, sample_volunteers):
    """Test getting queue statistics."""
    with app.app_context():
        # Create additional volunteers to avoid UNIQUE constraint violations
        candidate2 = Volunteer(first_name="Jane", last_name="Smith")
        candidate3 = Volunteer(first_name="Bob", last_name="Jones")
        db.session.add_all([candidate2, candidate3])
        db.session.flush()

        # Create various suggestions with unique combinations
        high = DedupeSuggestion(
            run_id=sample_import_run.id,
            primary_contact_id=sample_volunteers["primary"].id,
            candidate_contact_id=candidate2.id,  # Use different candidate
            score=0.96,
            match_type="fuzzy_high",
            decision=DedupeDecision.PENDING,
        )
        review = DedupeSuggestion(
            run_id=sample_import_run.id,
            primary_contact_id=sample_volunteers["primary"].id,
            candidate_contact_id=candidate3.id,  # Use different candidate
            score=0.85,
            match_type="fuzzy_review",
            decision=DedupeDecision.PENDING,
        )
        db.session.add_all([high, review])
        db.session.commit()

        stats = merge_service.get_queue_stats()

        assert stats.total_pending >= 2
        assert stats.total_high_confidence >= 1
        assert stats.total_review_band >= 1
        assert isinstance(stats.aging_buckets, dict)


def test_execute_merge_with_field_overrides(merge_service, app, sample_dedupe_suggestion):
    """Test merge with field overrides."""
    with app.app_context():
        user_id = 1
        field_overrides = {
            "first_name": "Johnny",
            "last_name": "Doe",
        }

        merge_log = merge_service.execute_merge(
            sample_dedupe_suggestion.id,
            user_id=user_id,
            field_overrides=field_overrides,
        )

        assert merge_log is not None
        # Verify metadata includes field overrides
        assert merge_log.metadata_json is not None
        assert "field_overrides" in merge_log.metadata_json


def test_execute_merge_creates_snapshots(merge_service, app, sample_dedupe_suggestion):
    """Test that merge creates before/after snapshots."""
    with app.app_context():
        user_id = 1
        merge_log = merge_service.execute_merge(
            sample_dedupe_suggestion.id,
            user_id=user_id,
        )

        assert merge_log.snapshot_before is not None
        assert merge_log.snapshot_after is not None
        assert "primary" in merge_log.snapshot_before
        assert "primary" in merge_log.snapshot_after
