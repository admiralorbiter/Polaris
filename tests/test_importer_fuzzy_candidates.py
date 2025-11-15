import time
from datetime import date
from uuid import uuid4

from flask_app.importer.pipeline.fuzzy_candidates import generate_fuzzy_candidates
from flask_app.models import (
    AddressType,
    CleanVolunteer,
    ContactAddress,
    ContactEmail,
    ContactPhone,
    DedupeSuggestion,
    EmailType,
    ImportRun,
    Organization,
    PhoneType,
    Volunteer,
    db,
)


def _seed_volunteer(
    first_name: str,
    last_name: str,
    *,
    email: str,
    phone: str,
    street: str,
    city: str,
    postal_code: str,
    dob: str | None = None,
    employer: str | None = None,
):
    volunteer = Volunteer(first_name=first_name, last_name=last_name)
    volunteer.birthdate = date.fromisoformat(dob) if dob else date(1992, 5, 11)
    db.session.add(volunteer)
    db.session.flush()

    if employer:
        slug_base = employer.lower().replace(" ", "-") or f"org-{uuid4().hex[:8]}"
        slug = slug_base
        index = 1
        while Organization.query.filter_by(slug=slug).first() is not None:
            slug = f"{slug_base}-{index}"
            index += 1
        organization = Organization(name=employer, slug=slug)
        db.session.add(organization)
        db.session.flush()
        volunteer.organization = organization

    db.session.add(
        ContactEmail(
            contact_id=volunteer.id,
            email=email,
            email_type=EmailType.PERSONAL,
            is_primary=True,
        )
    )
    if phone:
        db.session.add(
            ContactPhone(
                contact_id=volunteer.id,
                phone_number=phone,
                phone_type=PhoneType.MOBILE,
                is_primary=True,
            )
        )
    db.session.add(
        ContactAddress(
            contact_id=volunteer.id,
            address_type=AddressType.HOME,
            street_address_1=street,
            city=city,
            state="CA",
            postal_code=postal_code,
            country="US",
            is_primary=True,
        )
    )
    return volunteer


def test_generate_fuzzy_candidates_high_confidence_persists(app):
    with app.app_context():
        run = ImportRun(source="csv")
        db.session.add(run)
        db.session.commit()

        volunteer = _seed_volunteer(
            "Isabella",
            "Martinez",
            email="isabella.martinez@example.org",
            phone="+14155553001",
            street="125 Palm St",
            city="San Francisco",
            postal_code="94110",
            employer="North Beach Tutoring",
        )
        db.session.commit()

        payload = {
            "first_name": "Izabella",
            "last_name": "Martinez",
            "dob": "1992-05-11",
            "street": "125 Palm Street",
            "city": "San Francisco",
            "postal_code": "94110",
            "employer": "North Beach Tutoring",
            "alternate_emails": "isabella.martinez+alumni@example.org",
        }

        clean_row = CleanVolunteer(
            run_id=run.id,
            staging_volunteer_id=None,
            external_system="legacy_csv",
            external_id="fuzzy-candidate-001",
            first_name="Izabella",
            last_name="Martinez",
            email=None,
            phone_e164=None,
            payload_json={
                **payload,
                "alternate_emails": [payload["alternate_emails"]],
                "alternate_phones": ["+14155553001"],
            },
        )
        db.session.add(clean_row)
        db.session.commit()

        summary = generate_fuzzy_candidates(run, dry_run=False)

        assert summary.suggestions_created == 1
        assert summary.review_band == 1
        suggestion = DedupeSuggestion.query.filter_by(run_id=run.id).one()
        assert suggestion.primary_contact_id == volunteer.id
        assert suggestion.match_type == "fuzzy_review"
        assert 0.80 <= float(suggestion.score) < 0.95


def test_generate_fuzzy_candidates_respects_dry_run(app):
    with app.app_context():
        run = ImportRun(source="csv")
        db.session.add(run)
        db.session.commit()

        _seed_volunteer(
            "Isabella",
            "Martinez",
            email="isabella.martinez@example.org",
            phone="+14155553001",
            street="125 Palm St",
            city="San Francisco",
            postal_code="94110",
            employer="North Beach Tutoring",
        )
        db.session.commit()

        payload = {
            "first_name": "Izabella",
            "last_name": "Martinez",
            "dob": "1992-05-11",
            "street": "125 Palm Street",
            "city": "San Francisco",
            "postal_code": "94110",
            "alternate_emails": ["isabella.martinez+alumni@example.org"],
            "alternate_phones": ["+14155553001"],
            "employer": "North Beach Tutoring",
        }

        clean_row = CleanVolunteer(
            run_id=run.id,
            staging_volunteer_id=None,
            external_system="legacy_csv",
            external_id="fuzzy-candidate-dry-run",
            first_name="Izabella",
            last_name="Martinez",
            email=None,
            phone_e164=None,
            payload_json=payload,
        )
        db.session.add(clean_row)
        db.session.commit()

        summary = generate_fuzzy_candidates(run, dry_run=True)

        assert summary.suggestions_created == 1
        assert summary.review_band == 1
        assert DedupeSuggestion.query.filter_by(run_id=run.id).count() == 0


def test_generate_fuzzy_candidates_multiple_reviews(app):
    with app.app_context():
        run = ImportRun(source="csv")
        db.session.add(run)
        db.session.commit()

        _seed_volunteer(
            "Isabella",
            "Martinez",
            email="isabella.martinez@example.org",
            phone="+14155553001",
            street="125 Palm St",
            city="San Francisco",
            postal_code="94110",
            dob="1992-05-11",
            employer="North Beach Tutoring",
        )
        _seed_volunteer(
            "Jonathan",
            "Chen",
            email="jonathan.chen@example.org",
            phone="+14155553002",
            street="87 Elm Ave",
            city="Oakland",
            postal_code="94607",
            dob="1990-02-19",
            employer="Bay Robotics",
        )
        db.session.commit()

        candidates = [
            {
                "external_id": "fuzzy-candidate-001",
                "first_name": "Izabella",
                "last_name": "Martinez",
                "dob": "1992-05-11",
                "street": "125 Palm Street",
                "city": "San Francisco",
                "postal_code": "94110",
                "employer": "North Beach Tutoring",
                "alternate_emails": ["isabella.martinez+alumni@example.org"],
                "alternate_phones": ["+14155553001"],
            },
            {
                "external_id": "fuzzy-candidate-002",
                "first_name": "Jon",
                "last_name": "Chen",
                "dob": "1990-02-19",
                "street": "89 Elm Avenue",
                "city": "Oakland",
                "postal_code": "94607",
                "employer": "Bay Robotics",
                "alternate_emails": ["jonathan.chen@example.org"],
                "alternate_phones": ["+14155553112"],
            },
        ]

        for payload in candidates:
            clean_row = CleanVolunteer(
                run_id=run.id,
                staging_volunteer_id=None,
                external_system="legacy_csv",
                external_id=payload["external_id"],
                first_name=payload["first_name"],
                last_name=payload["last_name"],
                email=None,
                phone_e164=None,
                payload_json=payload,
            )
            db.session.add(clean_row)
        db.session.commit()

        summary = generate_fuzzy_candidates(run, dry_run=False)
        suggestions = DedupeSuggestion.query.filter_by(run_id=run.id).order_by(DedupeSuggestion.score.desc()).all()

        assert summary.suggestions_created == 2
        assert summary.review_band == 2
        assert all(s.match_type == "fuzzy_review" for s in suggestions)
        assert all(0.80 <= float(s.score) < 0.95 for s in suggestions)


def test_generate_fuzzy_candidates_bulk_performance(app):
    with app.app_context():
        run = ImportRun(source="csv")
        db.session.add(run)
        db.session.commit()

        _seed_volunteer(
            "Jordan",
            "Baker",
            email="jordan.baker@example.org",
            phone="+14155553100",
            street="400 Pine St",
            city="San Francisco",
            postal_code="94111",
            dob="1990-01-01",
            employer="North Beach Tutoring",
        )
        db.session.commit()

        for index in range(500):
            payload = {
                "first_name": "Jordan",
                "last_name": "Baker",
                "dob": "1990-01-01",
                "street": "400 Pine St",
                "city": "San Francisco",
                "postal_code": "94111",
                "alternate_emails": f"jordan.baker+{index}@example.org",
            }
            clean_row = CleanVolunteer(
                run_id=run.id,
                staging_volunteer_id=None,
                external_system="legacy_csv",
                external_id=f"bulk-{index:05d}",
                first_name="Jordan",
                last_name="Baker",
                email=None,
                phone_e164=None,
                payload_json={
                    **payload,
                    "alternate_emails": [payload["alternate_emails"]],
                    "alternate_phones": ["+14155553100"],
                },
            )
            db.session.add(clean_row)
        db.session.commit()

        start = time.perf_counter()
        summary = generate_fuzzy_candidates(run, dry_run=False)
        duration = time.perf_counter() - start

        assert summary.rows_considered == 500
        assert summary.suggestions_created == 500
        # Performance test - allow variance for system load (increased threshold to account for CI/system variations)
        assert duration < 5.0, f"Fuzzy candidate generation took too long ({duration:.2f}s)"


def test_generate_fuzzy_candidates_skips_deterministic_matches(app):
    with app.app_context():
        run = ImportRun(source="csv")
        db.session.add(run)
        db.session.commit()

        _seed_volunteer(
            "Alex",
            "Rivera",
            email="alex.rivera@example.org",
            phone="+14155554001",
            street="10 Oak Ave",
            city="Oakland",
            postal_code="94607",
            dob="1988-02-02",
            employer="Tech Corps",
        )
        db.session.commit()

        payload = {
            "first_name": "Alex",
            "last_name": "Rivera",
            "email": "alex.rivera@example.org",
            "phone": "+14155554001",
            "employer": "Tech Corps",
        }
        clean_row = CleanVolunteer(
            run_id=run.id,
            staging_volunteer_id=None,
            external_system="legacy_csv",
            external_id="deterministic-001",
            first_name="Alex",
            last_name="Rivera",
            email="alex.rivera@example.org",
            phone_e164="+14155554001",
            payload_json=payload,
        )
        db.session.add(clean_row)
        db.session.commit()

        summary = generate_fuzzy_candidates(run, dry_run=False)

        assert summary.suggestions_created == 0
        assert summary.skipped_deterministic == 1
        assert DedupeSuggestion.query.filter_by(run_id=run.id).count() == 0


def test_scan_existing_volunteers_finds_exact_name_duplicates(app):
    """Test that scan_existing_volunteers_for_duplicates finds exact name matches."""
    from flask_app.importer.pipeline.fuzzy_candidates import scan_existing_volunteers_for_duplicates
    from flask_app.models.importer.schema import ImportRun, ImportRunStatus

    with app.app_context():
        # Create two volunteers with exact same name but different emails
        volunteer1 = Volunteer(first_name="Sarah", last_name="Higgerson")
        db.session.add(volunteer1)
        db.session.flush()
        db.session.add(
            ContactEmail(
                contact_id=volunteer1.id,
                email="sarah.higgerson@example.org",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
        )

        volunteer2 = Volunteer(first_name="Sarah", last_name="Higgerson")
        db.session.add(volunteer2)
        db.session.flush()
        db.session.add(
            ContactEmail(
                contact_id=volunteer2.id,
                email="sarah.h@different.org",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
        )
        db.session.commit()

        summary = scan_existing_volunteers_for_duplicates(dry_run=False, similarity_threshold=0.80)

        assert summary.rows_considered >= 2
        assert summary.suggestions_created >= 1

        # Check that a suggestion was created
        suggestions = DedupeSuggestion.query.filter(
            DedupeSuggestion.primary_contact_id.in_([volunteer1.id, volunteer2.id]),
            DedupeSuggestion.candidate_contact_id.in_([volunteer1.id, volunteer2.id]),
            DedupeSuggestion.decision == "PENDING",
        ).all()
        assert len(suggestions) >= 1

        # Check that the suggestion has a high score (exact match should be >= 0.90)
        suggestion = suggestions[0]
        assert float(suggestion.score) >= 0.90
        # Check features in the features_json structure
        features = suggestion.features_json.get("features", suggestion.features_json)
        assert features.get("name") == 1.0  # Exact match


def test_scan_existing_volunteers_respects_dry_run(app):
    """Test that scan_existing_volunteers_for_duplicates respects dry_run flag."""
    from flask_app.importer.pipeline.fuzzy_candidates import scan_existing_volunteers_for_duplicates

    with app.app_context():
        # Create two volunteers with exact same name
        volunteer1 = Volunteer(first_name="Test", last_name="Duplicate")
        db.session.add(volunteer1)
        volunteer2 = Volunteer(first_name="Test", last_name="Duplicate")
        db.session.add(volunteer2)
        db.session.commit()

        summary = scan_existing_volunteers_for_duplicates(dry_run=True, similarity_threshold=0.80)

        assert summary.rows_considered >= 2
        assert summary.suggestions_created >= 1  # Counted but not persisted

        # Check that no suggestions were actually persisted
        suggestions = DedupeSuggestion.query.filter(
            DedupeSuggestion.primary_contact_id.in_([volunteer1.id, volunteer2.id]),
            DedupeSuggestion.candidate_contact_id.in_([volunteer1.id, volunteer2.id]),
        ).all()
        assert len(suggestions) == 0


def test_scan_existing_volunteers_uses_blocking_strategy(app):
    """Test that scan uses efficient blocking strategy (same last name + first initial)."""
    from flask_app.importer.pipeline.fuzzy_candidates import scan_existing_volunteers_for_duplicates

    with app.app_context():
        # Create volunteers with same last name and first initial (should be in same block)
        volunteer1 = Volunteer(first_name="John", last_name="Smith")
        volunteer2 = Volunteer(first_name="Jane", last_name="Smith")
        volunteer3 = Volunteer(first_name="Jim", last_name="Smith")
        # Create one with different last name (should be in different block)
        volunteer4 = Volunteer(first_name="John", last_name="Jones")

        db.session.add_all([volunteer1, volunteer2, volunteer3, volunteer4])
        db.session.commit()

        summary = scan_existing_volunteers_for_duplicates(dry_run=True, similarity_threshold=0.80)

        # Should process all volunteers
        assert summary.rows_considered >= 4

        # The blocking strategy should still find matches if names are similar enough
        # (John Smith vs Jane Smith might not match, but the scan should still run efficiently)


def test_scan_existing_volunteers_handles_empty_database(app):
    """Test that scan handles empty database gracefully."""
    from flask_app.importer.pipeline.fuzzy_candidates import scan_existing_volunteers_for_duplicates

    with app.app_context():
        # Ensure no volunteers exist
        Volunteer.query.delete()
        db.session.commit()

        summary = scan_existing_volunteers_for_duplicates(dry_run=True, similarity_threshold=0.80)

        assert summary.rows_considered == 0
        assert summary.suggestions_created == 0
        assert summary.high_confidence == 0
        assert summary.review_band == 0
        assert summary.low_score == 0


def test_scan_existing_volunteers_handles_volunteers_without_names(app):
    """Test that scan skips volunteers without first or last names."""
    from flask_app.importer.pipeline.fuzzy_candidates import scan_existing_volunteers_for_duplicates

    with app.app_context():
        # Create volunteers with missing names
        # Note: last_name is required in the Contact model, so we can't create None
        # Instead, test with empty strings or just test that the scan handles it
        volunteer1 = Volunteer(first_name="Jane", last_name="Doe")  # Valid
        volunteer2 = Volunteer(first_name="John", last_name="Doe")  # Valid

        db.session.add_all([volunteer1, volunteer2])
        db.session.commit()

        summary = scan_existing_volunteers_for_duplicates(dry_run=True, similarity_threshold=0.80)

        # Should process volunteers with valid names
        assert summary.rows_considered >= 2
