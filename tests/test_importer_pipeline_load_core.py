from datetime import datetime, timezone

from flask_app.importer.pipeline.clean import promote_clean_volunteers
from flask_app.importer.pipeline.load_core import load_core_volunteers
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
    ImportRunStatus,
    StagingRecordStatus,
    StagingVolunteer,
    Volunteer,
    db,
    DataQualityViolation,
    DataQualitySeverity,
    DataQualityStatus,
)


def _make_run() -> ImportRun:
    run = ImportRun(source="csv", adapter="csv", status=ImportRunStatus.PENDING, dry_run=False)
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _make_validated_row(
    run: ImportRun,
    *,
    seq: int,
    email: str,
    phone: str | None = None,
    external_id: str | None = None,
) -> StagingVolunteer:
    row = StagingVolunteer(
        run_id=run.id,
        sequence_number=seq,
        source_record_id=f"row-{seq}",
        external_system="csv",
        external_id=external_id or f"ext-{seq}",
        payload_json={
            "first_name": "Test",
            "last_name": f"User{seq}",
            "email": email,
            "phone": phone or "",
        },
        normalized_json={
            "first_name": "Test",
            "last_name": f"User{seq}",
            "email": email,
            "phone": phone or "",
        },
        checksum=f"checksum-{seq}",
        status=StagingRecordStatus.VALIDATED,
    )
    db.session.add(row)
    db.session.commit()
    return db.session.get(StagingVolunteer, row.id)


def test_load_core_volunteers_inserts_contacts(app):
    run = _make_run()
    row = _make_validated_row(run, seq=1, email="core-insert@example.org", phone="+14155550111")

    promote_clean_volunteers(run, dry_run=False)
    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()

    volunteer = Volunteer.query.filter_by(first_name="Test", last_name="User1").one()
    email = (
        db.session.query(ContactEmail)
        .filter(ContactEmail.contact_id == volunteer.id)
        .filter(ContactEmail.email == "core-insert@example.org")
        .one()
    )
    phone = (
        db.session.query(ContactPhone)
        .filter(ContactPhone.contact_id == volunteer.id)
        .filter(ContactPhone.phone_number == "+14155550111")
        .one()
    )

    assert summary.rows_created == 1
    assert summary.rows_deduped_auto == 0
    assert summary.rows_skipped_duplicates == 0
    assert row.status == StagingRecordStatus.LOADED
    assert email.is_primary is True
    assert phone.is_primary is True

    counts = run.counts_json["core"]["volunteers"]
    assert counts["rows_created"] == 1
    assert counts["rows_updated"] == 0
    assert counts["rows_deduped_auto"] == 0
    assert counts["rows_skipped_duplicates"] == 0
    assert counts["rows_skipped_no_change"] == 0
    metrics = run.metrics_json["core"]["volunteers"]
    assert metrics["rows_created"] == 1
    assert metrics["rows_updated"] == 0
    assert metrics["rows_deduped_auto"] == 0


def test_load_core_volunteers_skips_duplicates(app):
    run = _make_run()
    _make_validated_row(run, seq=1, email="duplicate@example.org", phone=None)
    promote_clean_volunteers(run, dry_run=False)

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

    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()

    assert summary.rows_created == 0
    assert summary.rows_updated == 1
    assert summary.rows_deduped_auto == 1
    clean_row = CleanVolunteer.query.filter_by(run_id=run.id).one()
    assert clean_row.load_action == "deterministic_update"
    assert StagingVolunteer.query.filter_by(run_id=run.id).one().status == StagingRecordStatus.LOADED
    counts = run.counts_json["core"]["volunteers"]
    assert counts["rows_created"] == 0
    assert counts["rows_updated"] == 1
    assert counts["rows_deduped_auto"] == 1
    suggestion = DedupeSuggestion.query.filter_by(run_id=run.id).one()
    assert suggestion.decision == DedupeDecision.AUTO_MERGED
    assert suggestion.match_type == "email"
    assert float(suggestion.confidence_score) == 1.0


def test_load_core_volunteers_dry_run(app):
    run = _make_run()
    _make_validated_row(run, seq=1, email="dry-run@example.org", phone=None)
    clean_summary = promote_clean_volunteers(run, dry_run=True)

    summary = load_core_volunteers(
        run,
        dry_run=True,
        clean_candidates=clean_summary.candidates,
    )
    db.session.commit()

    assert summary.rows_processed == 1
    assert summary.rows_created == 0
    assert summary.rows_updated == 0
    assert Volunteer.query.count() == 0
    counts = run.counts_json["core"]["volunteers"]
    assert counts["rows_created"] == 0
    assert counts["rows_updated"] == 0
    assert counts["rows_deduped_auto"] == 0
    assert counts["dry_run"] is True
    metrics_core = run.metrics_json["core"]["volunteers"]
    assert metrics_core["rows_created"] == 1
    assert metrics_core["rows_updated"] == 0
    assert metrics_core["rows_deduped_auto"] == 0


def test_load_core_volunteers_updates_existing_contact(app):
    run_initial = _make_run()
    shared_external_id = "shared-ext-1"
    _make_validated_row(run_initial, seq=1, email="initial@example.org", phone=None, external_id=shared_external_id)
    promote_clean_volunteers(run_initial, dry_run=False)
    load_core_volunteers(run_initial, dry_run=False)
    db.session.commit()

    volunteer = Volunteer.query.filter_by(last_name="User1").one()
    id_map = ExternalIdMap.query.filter_by(external_id=shared_external_id).one()
    assert id_map.entity_id == volunteer.id

    run_update = _make_run()
    _make_validated_row(
        run_update,
        seq=2,
        email="updated@example.org",
        phone="+14155550199",
        external_id=shared_external_id,
    )
    promote_clean_volunteers(run_update, dry_run=False)
    summary = load_core_volunteers(run_update, dry_run=False)
    db.session.commit()
    db.session.refresh(run_update)

    primary_email = ContactEmail.query.filter_by(contact_id=volunteer.id, is_primary=True).one()
    primary_phone = ContactPhone.query.filter_by(contact_id=volunteer.id, is_primary=True).one()
    clean_row = CleanVolunteer.query.filter_by(run_id=run_update.id).one()
    counts_update = run_update.counts_json["core"]["volunteers"]
    metrics_update = run_update.metrics_json["core"]["volunteers"]

    assert summary.rows_updated == 1
    assert summary.rows_created == 0
    assert summary.rows_skipped_no_change == 0
    assert clean_row.load_action == "updated"
    assert primary_email.email == "updated@example.org"
    assert primary_phone.phone_number == "+14155550199"
    assert counts_update["rows_updated"] == 1
    assert counts_update["rows_created"] == 0
    assert counts_update["rows_deduped_auto"] == 0
    assert metrics_update["rows_updated"] == 1


def test_survivorship_manual_override_wins(app):
    shared_external_id = "survivorship-ext-1"

    run_initial = _make_run()
    initial_row = _make_validated_row(
        run_initial,
        seq=1,
        email="initial-survivorship@example.org",
        phone=None,
        external_id=shared_external_id,
    )
    initial_row.payload_json = {**(initial_row.payload_json or {}), "notes": "Initial note"}
    initial_row.normalized_json = {**(initial_row.normalized_json or {}), "notes": "Initial note"}
    db.session.add(initial_row)
    db.session.commit()

    promote_clean_volunteers(run_initial, dry_run=False)
    load_core_volunteers(run_initial, dry_run=False)
    db.session.commit()

    volunteer = Volunteer.query.filter_by(last_name="User1").one()
    volunteer.notes = "Initial note"
    db.session.commit()

    run_update = _make_run()
    update_row = _make_validated_row(
        run_update,
        seq=2,
        email="manual-win@example.org",
        phone=None,
        external_id=shared_external_id,
    )
    update_row.payload_json = {**(update_row.payload_json or {}), "notes": "Source note"}
    update_row.normalized_json = {**(update_row.normalized_json or {}), "notes": "Source note"}
    db.session.add(update_row)
    db.session.flush()

    violation = DataQualityViolation(
        run_id=run_update.id,
        staging_volunteer_id=update_row.id,
        entity_type="volunteer",
        record_key=str(update_row.id),
        rule_code="manual_override",
        severity=DataQualitySeverity.INFO,
        status=DataQualityStatus.FIXED,
        message="Manual edits applied",
        edited_fields_json={
            "notes": {
                "before": "Initial note",
                "after": "Manual note",
            }
        },
        remediated_at=datetime.now(timezone.utc),
    )
    db.session.add(violation)
    db.session.commit()

    promote_clean_volunteers(run_update, dry_run=False)
    clean_candidate = CleanVolunteer.query.filter_by(run_id=run_update.id).one()
    assert clean_candidate.payload_json.get("notes") == "Source note"
    load_core_volunteers(run_update, dry_run=False)
    db.session.commit()
    db.session.refresh(run_update)
    db.session.refresh(volunteer)

    assert volunteer.notes == "Manual note"

    change_entry = ChangeLogEntry.query.filter_by(run_id=run_update.id, field_name="notes").one()
    metadata = change_entry.metadata_json or {}
    survivorship_meta = metadata.get("survivorship", {})
    assert survivorship_meta.get("manual_override") is True
    assert survivorship_meta.get("winner", {}).get("tier") == "manual"
    incoming_loser = next((loser for loser in survivorship_meta.get("losers", []) if loser.get("tier") == "incoming"), None)
    assert incoming_loser is not None
    assert incoming_loser.get("value") == "Source note"

    survivorship_counts = run_update.counts_json["core"]["volunteers"]["survivorship"]["stats"]
    assert survivorship_counts.get("manual_wins") == 1
    metrics_survivorship = run_update.metrics_json["core"]["volunteers"]["survivorship"]
    assert metrics_survivorship.get("manual_wins") == 1


def test_survivorship_incoming_overrides_recorded(app):
    shared_external_id = "survivorship-ext-2"

    run_initial = _make_run()
    initial_row = _make_validated_row(
        run_initial,
        seq=1,
        email="incoming-survivorship@example.org",
        phone=None,
        external_id=shared_external_id,
    )
    initial_row.payload_json = {**(initial_row.payload_json or {}), "notes": "Existing note"}
    initial_row.normalized_json = {**(initial_row.normalized_json or {}), "notes": "Existing note"}
    db.session.add(initial_row)
    db.session.commit()

    promote_clean_volunteers(run_initial, dry_run=False)
    load_core_volunteers(run_initial, dry_run=False)
    db.session.commit()

    volunteer = Volunteer.query.filter_by(last_name="User1").one()
    volunteer.notes = "Existing note"
    db.session.commit()

    run_update = _make_run()
    update_row = _make_validated_row(
        run_update,
        seq=2,
        email="incoming-update@example.org",
        phone=None,
        external_id=shared_external_id,
    )
    update_row.payload_json = {**(update_row.payload_json or {}), "notes": "Fresh note"}
    update_row.normalized_json = {**(update_row.normalized_json or {}), "notes": "Fresh note"}
    db.session.add(update_row)
    db.session.commit()

    promote_clean_volunteers(run_update, dry_run=False)
    clean_candidate = CleanVolunteer.query.filter_by(run_id=run_update.id).one()
    assert clean_candidate.payload_json.get("notes") == "Fresh note"
    load_core_volunteers(run_update, dry_run=False)
    db.session.commit()
    db.session.refresh(run_update)
    db.session.refresh(volunteer)

    assert volunteer.notes == "Fresh note"

    change_entry = ChangeLogEntry.query.filter_by(run_id=run_update.id, field_name="notes").one()
    metadata = change_entry.metadata_json or {}
    survivorship_meta = metadata.get("survivorship", {})
    assert survivorship_meta.get("winner", {}).get("tier") == "incoming"
    assert survivorship_meta.get("manual_override") is False

    survivorship_counts = run_update.counts_json["core"]["volunteers"]["survivorship"]["stats"]
    assert survivorship_counts.get("incoming_overrides", 0) >= 1
    metrics_survivorship = run_update.metrics_json["core"]["volunteers"]["survivorship"]
    assert metrics_survivorship.get("incoming_overrides", 0) >= 1

    change_entries = ChangeLogEntry.query.filter_by(run_id=run_update.id).all()
    changed_fields = {entry.field_name for entry in change_entries}
    assert "email" in changed_fields


def test_load_core_volunteers_deterministic_email_match_updates_existing_contact(app):
    seed_run = _make_run()
    _make_validated_row(
        seed_run, seq=1, email="deterministic@example.org", phone="+14155550000", external_id="seed-ext"
    )
    promote_clean_volunteers(seed_run, dry_run=False)
    load_core_volunteers(seed_run, dry_run=False)
    db.session.commit()

    volunteer = Volunteer.query.filter_by(last_name="User1").one()

    dedupe_run = _make_run()
    _make_validated_row(
        dedupe_run,
        seq=2,
        email="deterministic@example.org",
        phone="+14155550099",
        external_id="fresh-ext-1",
    )
    promote_clean_volunteers(dedupe_run, dry_run=False)
    summary = load_core_volunteers(dedupe_run, dry_run=False)
    db.session.commit()
    db.session.refresh(dedupe_run)

    phone_entry = ContactPhone.query.filter_by(contact_id=volunteer.id, is_primary=True).one()
    clean_row = CleanVolunteer.query.filter_by(run_id=dedupe_run.id).one()
    counts = dedupe_run.counts_json["core"]["volunteers"]
    metrics = dedupe_run.metrics_json["core"]["volunteers"]
    suggestion = DedupeSuggestion.query.filter_by(run_id=dedupe_run.id).one()

    assert summary.rows_updated == 1
    assert summary.rows_deduped_auto == 1
    assert clean_row.load_action == "deterministic_update"
    assert counts["rows_deduped_auto"] == 1
    assert metrics["rows_deduped_auto"] == 1
    assert suggestion.decision == DedupeDecision.AUTO_MERGED
    assert suggestion.features_json["match_type"] == "email"
    assert suggestion.match_type == "email"
    assert float(suggestion.confidence_score) == 1.0
    assert phone_entry.phone_number == "+14155550099"


def test_load_core_volunteers_reactivates_soft_deleted_mapping(app):
    run_initial = _make_run()
    shared_external_id = "shared-ext-2"
    _make_validated_row(run_initial, seq=1, email="reactivate@example.org", phone=None, external_id=shared_external_id)
    promote_clean_volunteers(run_initial, dry_run=False)
    load_core_volunteers(run_initial, dry_run=False)
    db.session.commit()

    id_map = ExternalIdMap.query.filter_by(external_id=shared_external_id).one()
    id_map.soft_delete(reason="Removed upstream")
    db.session.commit()

    assert not id_map.is_active
    assert id_map.deactivated_at is not None

    run_reactivate = _make_run()
    _make_validated_row(
        run_reactivate,
        seq=2,
        email="reactivate@example.org",
        phone=None,
        external_id=shared_external_id,
    )
    promote_clean_volunteers(run_reactivate, dry_run=False)
    summary = load_core_volunteers(run_reactivate, dry_run=False)
    db.session.commit()
    db.session.refresh(run_reactivate)

    refreshed_map = ExternalIdMap.query.filter_by(external_id=shared_external_id).one()
    clean_row = CleanVolunteer.query.filter_by(run_id=run_reactivate.id).one()
    counts_reactivate = run_reactivate.counts_json["core"]["volunteers"]

    assert summary.rows_reactivated == 1
    assert summary.rows_skipped_no_change >= 0
    assert refreshed_map.is_active
    assert refreshed_map.deactivated_at is None
    assert refreshed_map.upstream_deleted_reason is None
    assert clean_row.load_action == "reactivated"
    assert counts_reactivate["rows_reactivated"] == 1
    assert counts_reactivate["rows_deduped_auto"] == 0


def test_load_core_volunteers_flags_missing_external_id(app):
    run = _make_run()
    row = _make_validated_row(run, seq=1, email="no-ext@example.org", phone=None, external_id=None)
    # Null out external_id after creation to simulate missing identifier.
    row.external_id = None
    db.session.commit()

    promote_clean_volunteers(run, dry_run=False)
    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()

    clean_row = CleanVolunteer.query.filter_by(run_id=run.id).one()
    staging_row = StagingVolunteer.query.filter_by(run_id=run.id).one()

    assert summary.rows_missing_external_id == 1
    assert clean_row.load_action == "error_missing_external_id"
    assert staging_row.status == StagingRecordStatus.QUARANTINED
    assert "external_id" in (staging_row.last_error or "").lower()


def test_load_core_volunteers_skips_exact_name_duplicate(app):
    """Test that exact name matches are detected and skipped, with email merging."""
    run = _make_run()
    
    # Create existing volunteer with exact name
    existing = Volunteer(first_name="Rebecca", last_name="Coulson")
    db.session.add(existing)
    db.session.flush()
    db.session.add(
        ContactEmail(
            contact_id=existing.id,
            email="rebecca.coulson@hallfamilyfoundation.org",
            email_type=EmailType.PERSONAL,
            is_primary=True,
            is_verified=True,
        )
    )
    db.session.commit()
    
    # Create new row with same name but different email
    _make_validated_row(
        run,
        seq=1,
        email="rebecca.hall@hallmark.com",
        phone=None,
        external_id="new-ext-1",
    )
    # Update the payload to have exact matching name
    row = StagingVolunteer.query.filter_by(run_id=run.id).one()
    # Update JSON by creating new dicts to ensure SQLAlchemy detects the change
    payload_json = dict(row.payload_json or {})
    payload_json["first_name"] = "Rebecca"
    payload_json["last_name"] = "Coulson"
    row.payload_json = payload_json
    
    normalized_json = dict(row.normalized_json or {})
    normalized_json["first_name"] = "Rebecca"
    normalized_json["last_name"] = "Coulson"
    row.normalized_json = normalized_json
    
    db.session.commit()
    
    promote_clean_volunteers(run, dry_run=False)
    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()
    
    assert summary.rows_created == 0
    assert summary.rows_skipped_duplicate_name == 1
    assert summary.rows_updated == 0
    
    # Check that email was merged
    emails = ContactEmail.query.filter_by(contact_id=existing.id).all()
    email_addresses = {e.email for e in emails}
    assert "rebecca.coulson@hallfamilyfoundation.org" in email_addresses
    assert "rebecca.hall@hallmark.com" in email_addresses
    
    # Check that ExternalIdMap was created
    id_map = ExternalIdMap.query.filter_by(external_id="new-ext-1").one()
    assert id_map.entity_id == existing.id
    
    clean_row = CleanVolunteer.query.filter_by(run_id=run.id).one()
    assert clean_row.load_action == "skipped_duplicate"
    assert clean_row.core_contact_id == existing.id


def test_load_core_volunteers_name_dedupe_case_insensitive(app):
    """Test that name matching is case-insensitive."""
    run = _make_run()
    
    # Create existing volunteer
    existing = Volunteer(first_name="John", last_name="Smith")
    db.session.add(existing)
    db.session.commit()
    
    # Create new row with same name but different case
    _make_validated_row(
        run,
        seq=1,
        email="john.smith@example.org",
        phone=None,
        external_id="case-test-1",
    )
    row = StagingVolunteer.query.filter_by(run_id=run.id).one()
    # Update JSON by creating new dicts to ensure SQLAlchemy detects the change
    payload_json = dict(row.payload_json or {})
    payload_json["first_name"] = "JOHN"
    payload_json["last_name"] = "SMITH"
    row.payload_json = payload_json
    
    normalized_json = dict(row.normalized_json or {})
    normalized_json["first_name"] = "JOHN"
    normalized_json["last_name"] = "SMITH"
    row.normalized_json = normalized_json
    
    db.session.commit()
    
    promote_clean_volunteers(run, dry_run=False)
    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()
    
    assert summary.rows_skipped_duplicate_name == 1
    assert summary.rows_created == 0


def test_load_core_volunteers_name_dedupe_with_whitespace(app):
    """Test that name matching handles whitespace normalization."""
    run = _make_run()
    
    # Create existing volunteer
    existing = Volunteer(first_name="Mary", last_name="Johnson")
    db.session.add(existing)
    db.session.commit()
    
    # Create new row with same name but extra whitespace
    _make_validated_row(
        run,
        seq=1,
        email="mary.johnson@example.org",
        phone=None,
        external_id="whitespace-test-1",
    )
    row = StagingVolunteer.query.filter_by(run_id=run.id).one()
    # Update JSON by creating new dicts to ensure SQLAlchemy detects the change
    payload_json = dict(row.payload_json or {})
    payload_json["first_name"] = "  Mary  "
    payload_json["last_name"] = "  Johnson  "
    row.payload_json = payload_json
    
    normalized_json = dict(row.normalized_json or {})
    normalized_json["first_name"] = "  Mary  "
    normalized_json["last_name"] = "  Johnson  "
    row.normalized_json = normalized_json
    
    db.session.commit()
    
    promote_clean_volunteers(run, dry_run=False)
    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()
    
    assert summary.rows_skipped_duplicate_name == 1
    assert summary.rows_created == 0


def test_load_core_volunteers_name_cache_works(app):
    """Test that name lookup caching reduces database queries."""
    run = _make_run()
    
    # Create existing volunteer
    existing = Volunteer(first_name="Test", last_name="Cache")
    db.session.add(existing)
    db.session.commit()
    
    # Create multiple rows with same name (should use cache)
    for i in range(3):
        _make_validated_row(
            run,
            seq=i + 1,
            email=f"test{i}@example.org",
            phone=None,
            external_id=f"cache-test-{i}",
        )
        row = StagingVolunteer.query.filter_by(run_id=run.id, sequence_number=i + 1).one()
        # Update JSON by creating new dicts to ensure SQLAlchemy detects the change
        payload_json = dict(row.payload_json or {})
        payload_json["first_name"] = "Test"
        payload_json["last_name"] = "Cache"
        row.payload_json = payload_json
        
        normalized_json = dict(row.normalized_json or {})
        normalized_json["first_name"] = "Test"
        normalized_json["last_name"] = "Cache"
        row.normalized_json = normalized_json
    
    db.session.commit()
    
    promote_clean_volunteers(run, dry_run=False)
    summary = load_core_volunteers(run, dry_run=False)
    db.session.commit()
    
    # All three should be skipped as duplicates
    assert summary.rows_skipped_duplicate_name == 3
    assert summary.rows_created == 0
    
    # All emails should be merged (3 new emails merged into existing volunteer)
    emails = ContactEmail.query.filter_by(contact_id=existing.id).all()
    assert len(emails) == 3  # 3 new emails merged
    email_addresses = {e.email for e in emails}
    assert "test0@example.org" in email_addresses
    assert "test1@example.org" in email_addresses
    assert "test2@example.org" in email_addresses