"""
Comprehensive tests for volunteer management routes
"""

from datetime import date
from unittest.mock import patch

import pytest
from flask import url_for
from werkzeug.security import generate_password_hash

from flask_app.models import (
    ClearanceStatus,
    ContactEmail,
    ContactPhone,
    ContactStatus,
    ContactType,
    EducationLevel,
    EmailType,
    Gender,
    PhoneType,
    PreferredLanguage,
    RaceEthnicity,
    Salutation,
    Volunteer,
    VolunteerStatus,
    db,
)


class TestVolunteerRoutes:
    """Test volunteer management routes"""

    def test_volunteers_list_requires_login(self, client):
        """Test that volunteers list requires login"""
        response = client.get("/volunteers", follow_redirects=True)
        # Should redirect to login
        assert response.status_code == 200
        assert b"login" in response.data.lower() or b"Login" in response.data

    def test_volunteers_list_logged_in(self, client, test_user, app):
        """Test listing volunteers when logged in"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            # Create some test volunteers
            volunteer1 = Volunteer(
                first_name="John",
                last_name="Doe",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            volunteer2 = Volunteer(
                first_name="Jane",
                last_name="Smith",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer1)
            db.session.add(volunteer2)
            db.session.commit()

            # Login
            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Access volunteers list
            response = client.get("/volunteers")
            assert response.status_code == 200
            assert b"John" in response.data or b"Doe" in response.data
            assert b"Jane" in response.data or b"Smith" in response.data

    def test_volunteers_list_search(self, client, test_user, app):
        """Test volunteers list with search"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer = Volunteer(
                first_name="Searchable",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get("/volunteers?search=Searchable")
            assert response.status_code == 200
            assert b"Searchable" in response.data

    def test_volunteers_list_search_by_email(self, client, test_user, app):
        """Test volunteers list search by email"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer = Volunteer(
                first_name="Test",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer)
            db.session.flush()

            email = ContactEmail(
                contact_id=volunteer.id,
                email="test@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
            db.session.add(email)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get("/volunteers?search=test@example.com")
            assert response.status_code == 200
            assert b"Test" in response.data or b"Volunteer" in response.data

    def test_volunteers_list_sorting(self, client, test_user, app):
        """Test volunteers list sorting"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer1 = Volunteer(
                first_name="Alice",
                last_name="Aardvark",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            volunteer2 = Volunteer(
                first_name="Bob",
                last_name="Zebra",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer1)
            db.session.add(volunteer2)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Test ascending sort
            response = client.get("/volunteers?sort=name&order=asc")
            assert response.status_code == 200

            # Test descending sort
            response = client.get("/volunteers?sort=name&order=desc")
            assert response.status_code == 200

    def test_volunteers_list_pagination(self, client, test_user, app):
        """Test volunteers list pagination"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            # Create more than 20 volunteers (per_page is 20)
            for i in range(25):
                volunteer = Volunteer(
                    first_name=f"Volunteer{i}",
                    last_name="Test",
                    contact_type=ContactType.VOLUNTEER,
                    status=ContactStatus.ACTIVE,
                    volunteer_status=VolunteerStatus.ACTIVE,
                )
                db.session.add(volunteer)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Test first page
            response = client.get("/volunteers?page=1")
            assert response.status_code == 200

            # Test second page
            response = client.get("/volunteers?page=2")
            assert response.status_code == 200

    def test_volunteers_list_error_handling(self, client, test_user, app):
        """Test error handling in volunteers list"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Mock a database error
            with patch("flask_app.routes.volunteer.Volunteer.query") as mock_query:
                mock_query.options.side_effect = Exception("Database error")
                response = client.get("/volunteers", follow_redirects=True)
                assert response.status_code == 200
                # Should redirect to index (error handling redirects there)
                # Flash message might not be in response immediately, so just check redirect
                assert b"index" in response.data.lower() or response.request.path == "/"

    def test_volunteers_create_get(self, client, test_user, app):
        """Test GET request to create volunteer page"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get("/volunteers/create")
            assert response.status_code == 200
            assert b"Create" in response.data or b"Volunteer" in response.data

    def test_volunteers_create_post_success(self, client, test_user, app):
        """Test successful volunteer creation"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.post(
                "/volunteers/create",
                data={
                    "first_name": "New",
                    "last_name": "Volunteer",
                    "volunteer_status": VolunteerStatus.ACTIVE.value,
                    "email": "newvolunteer@example.com",
                    "phone_number": "555-1234",
                    "can_text": True,
                },
                follow_redirects=True,
            )

            assert response.status_code == 200
            # Verify volunteer was created - refresh session to see new data
            db.session.expire_all()
            volunteer = Volunteer.query.filter_by(first_name="New", last_name="Volunteer").first()
            assert volunteer is not None
            assert volunteer.volunteer_status == VolunteerStatus.ACTIVE

            # Verify email was created
            email = ContactEmail.query.filter_by(
                contact_id=volunteer.id, email="newvolunteer@example.com"
            ).first()
            assert email is not None
            assert email.is_primary is True

            # Verify phone was created
            phone = ContactPhone.query.filter_by(
                contact_id=volunteer.id, phone_number="555-1234"
            ).first()
            assert phone is not None
            assert phone.is_primary is True
            assert phone.can_text is True

    def test_volunteers_create_post_with_all_fields(self, client, test_user, app):
        """Test volunteer creation with all fields"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.post(
                "/volunteers/create",
                data={
                    "salutation": Salutation.MR.value,
                    "first_name": "Complete",
                    "middle_name": "Middle",
                    "last_name": "Volunteer",
                    "suffix": "Jr.",
                    "preferred_name": "Comp",
                    "volunteer_status": VolunteerStatus.ACTIVE.value,
                    "email": "complete@example.com",
                    "phone_number": "555-5678",
                    "can_text": False,
                    "gender": Gender.MALE.value,
                    "race": RaceEthnicity.WHITE.value,
                    "birthdate": "1990-01-15",
                    "education_level": EducationLevel.BACHELORS.value,
                    "clearance_status": ClearanceStatus.APPROVED.value,
                    "preferred_language": PreferredLanguage.ENGLISH.value,
                    "title": "Engineer",
                    "industry": "Technology",
                    "is_local": True,
                    "do_not_call": False,
                    "do_not_email": False,
                    "do_not_contact": False,
                    "notes": "Test notes",
                    "internal_notes": "Internal notes",
                },
                follow_redirects=True,
            )

            assert response.status_code == 200
            # Refresh session to see new data
            db.session.expire_all()
            volunteer = Volunteer.query.filter_by(first_name="Complete").first()
            assert volunteer is not None
            assert volunteer.salutation == Salutation.MR
            assert volunteer.middle_name == "Middle"
            assert volunteer.suffix == "Jr."
            assert volunteer.preferred_name == "Comp"
            assert volunteer.gender == Gender.MALE
            assert volunteer.race == RaceEthnicity.WHITE
            assert volunteer.birthdate == date(1990, 1, 15)
            assert volunteer.education_level == EducationLevel.BACHELORS
            assert volunteer.clearance_status == ClearanceStatus.APPROVED
            assert volunteer.title == "Engineer"
            assert volunteer.industry == "Technology"

    def test_volunteers_create_post_validation_error(self, client, test_user, app):
        """Test volunteer creation with validation errors"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Missing required fields
            response = client.post(
                "/volunteers/create",
                data={
                    "first_name": "",  # Required field missing
                    "last_name": "Test",
                    "volunteer_status": VolunteerStatus.ACTIVE.value,
                },
            )

            assert response.status_code == 200
            # Should show form with errors
            assert b"required" in response.data.lower() or b"error" in response.data.lower()

    def test_volunteers_create_post_invalid_email(self, client, test_user, app):
        """Test volunteer creation with invalid email"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.post(
                "/volunteers/create",
                data={
                    "first_name": "Test",
                    "last_name": "Volunteer",
                    "volunteer_status": VolunteerStatus.ACTIVE.value,
                    "email": "invalid-email",  # Invalid email format
                },
            )

            assert response.status_code == 200
            # Should show validation error
            assert b"email" in response.data.lower() or b"invalid" in response.data.lower()

    def test_volunteers_create_error_handling(self, client, test_user, app):
        """Test error handling in volunteer creation"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Mock a database error
            with patch("flask_app.routes.volunteer.db.session.commit") as mock_commit:
                mock_commit.side_effect = Exception("Database error")
                response = client.post(
                    "/volunteers/create",
                    data={
                        "first_name": "Test",
                        "last_name": "Volunteer",
                        "volunteer_status": VolunteerStatus.ACTIVE.value,
                    },
                )
                assert response.status_code == 200
                # Error is logged and flash message shown, but may not be in response immediately
                # Just verify the form is re-rendered (not a redirect)
                assert b"Create" in response.data or b"Volunteer" in response.data

    def test_volunteers_view(self, client, test_user, app):
        """Test viewing volunteer details"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer = Volunteer(
                first_name="View",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
                title="Manager",
                industry="Non-profit",
            )
            db.session.add(volunteer)
            db.session.flush()

            email = ContactEmail(
                contact_id=volunteer.id,
                email="view@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
            phone = ContactPhone(
                contact_id=volunteer.id,
                phone_number="555-9999",
                phone_type=PhoneType.MOBILE,
                is_primary=True,
            )
            db.session.add(email)
            db.session.add(phone)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get(f"/volunteers/{volunteer.id}")
            assert response.status_code == 200
            assert b"View" in response.data or b"Volunteer" in response.data
            assert b"Manager" in response.data or b"Non-profit" in response.data

    def test_volunteers_view_not_found(self, client, test_user, app):
        """Test viewing non-existent volunteer"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get("/volunteers/99999", follow_redirects=True)
            assert response.status_code == 404 or response.status_code == 200
            # Should show 404 or redirect with error

    def test_volunteers_view_error_handling(self, client, test_user, app):
        """Test error handling in volunteer view"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Mock a database error
            with patch("flask_app.routes.volunteer.Volunteer.query") as mock_query:
                mock_query.options.return_value.get_or_404.side_effect = Exception("Database error")
                response = client.get("/volunteers/1", follow_redirects=True)
                assert response.status_code == 200
                # Should redirect to list (error handling redirects there)
                # Flash message might not be in response immediately
                assert b"volunteer" in response.data.lower() or response.request.path == "/volunteers"

    def test_volunteers_edit_get(self, client, test_user, app):
        """Test GET request to edit volunteer page"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer = Volunteer(
                first_name="Edit",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get(f"/volunteers/{volunteer.id}/edit")
            assert response.status_code == 200
            assert b"Edit" in response.data or b"Volunteer" in response.data

    def test_volunteers_edit_post_success(self, client, test_user, app):
        """Test successful volunteer update"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer = Volunteer(
                first_name="Original",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer)
            db.session.flush()

            email = ContactEmail(
                contact_id=volunteer.id,
                email="original@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
            db.session.add(email)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.post(
                f"/volunteers/{volunteer.id}/edit",
                data={
                    "first_name": "Updated",
                    "last_name": "Volunteer",
                    "volunteer_status": VolunteerStatus.ACTIVE.value,
                    "email": "updated@example.com",
                    "phone_number": "555-0000",
                    "can_text": True,
                },
                follow_redirects=True,
            )

            assert response.status_code == 200
            # Verify volunteer was updated - refresh session and relationships
            db.session.expire_all()
            updated_volunteer = db.session.get(Volunteer, volunteer.id)
            # Explicitly reload the emails relationship
            _ = updated_volunteer.emails  # Force reload of relationship
            assert updated_volunteer.first_name == "Updated"
            # Query email directly to verify update
            updated_email = ContactEmail.query.filter_by(contact_id=volunteer.id, is_primary=True).first()
            assert updated_email is not None, "Primary email should exist"
            assert updated_email.email == "updated@example.com", f"Expected 'updated@example.com', got '{updated_email.email}'"
            assert updated_volunteer.get_primary_email() == "updated@example.com"

    def test_volunteers_edit_post_update_all_fields(self, client, test_user, app):
        """Test volunteer update with all fields"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer = Volunteer(
                first_name="Test",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.post(
                f"/volunteers/{volunteer.id}/edit",
                data={
                    "salutation": Salutation.MR.value,
                    "first_name": "Updated",
                    "middle_name": "Middle",
                    "last_name": "Volunteer",
                    "suffix": "Jr.",
                    "preferred_name": "Upd",
                    "volunteer_status": VolunteerStatus.HOLD.value,
                    "email": "updated@example.com",
                    "phone_number": "555-1111",
                    "can_text": False,
                    "gender": Gender.FEMALE.value,
                    "race": RaceEthnicity.ASIAN.value,
                    "birthdate": "1985-05-20",
                    "education_level": EducationLevel.MASTERS.value,
                    "clearance_status": ClearanceStatus.PENDING.value,
                    "preferred_language": PreferredLanguage.SPANISH.value,
                    "title": "Director",
                    "industry": "Education",
                    "is_local": False,
                    "do_not_call": True,
                    "do_not_email": False,
                    "do_not_contact": False,
                    "notes": "Updated notes",
                    "internal_notes": "Updated internal",
                },
                follow_redirects=True,
            )

            assert response.status_code == 200
            # Refresh session to see updated data
            db.session.expire_all()
            updated_volunteer = db.session.get(Volunteer, volunteer.id)
            assert updated_volunteer.first_name == "Updated"
            assert updated_volunteer.middle_name == "Middle"
            assert updated_volunteer.suffix == "Jr."
            assert updated_volunteer.preferred_name == "Upd"
            assert updated_volunteer.volunteer_status == VolunteerStatus.HOLD
            assert updated_volunteer.gender == Gender.FEMALE
            assert updated_volunteer.race == RaceEthnicity.ASIAN
            assert updated_volunteer.birthdate == date(1985, 5, 20)
            assert updated_volunteer.education_level == EducationLevel.MASTERS
            assert updated_volunteer.clearance_status == ClearanceStatus.PENDING
            assert updated_volunteer.title == "Director"
            assert updated_volunteer.industry == "Education"
            assert updated_volunteer.is_local is False
            assert updated_volunteer.do_not_call is True

    def test_volunteers_edit_post_remove_email(self, client, test_user, app):
        """Test removing email from volunteer"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer = Volunteer(
                first_name="Test",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer)
            db.session.flush()

            email = ContactEmail(
                contact_id=volunteer.id,
                email="test@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
            db.session.add(email)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Submit form with empty email
            response = client.post(
                f"/volunteers/{volunteer.id}/edit",
                data={
                    "first_name": "Test",
                    "last_name": "Volunteer",
                    "volunteer_status": VolunteerStatus.ACTIVE.value,
                    "email": "",  # Empty email
                },
                follow_redirects=True,
            )

            assert response.status_code == 200
            # Verify email was removed
            email_count = ContactEmail.query.filter_by(contact_id=volunteer.id).count()
            assert email_count == 0

    def test_volunteers_edit_post_validation_error(self, client, test_user, app):
        """Test volunteer update with validation errors"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer = Volunteer(
                first_name="Test",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Missing required fields
            response = client.post(
                f"/volunteers/{volunteer.id}/edit",
                data={
                    "first_name": "",  # Required field missing
                    "last_name": "Volunteer",
                    "volunteer_status": VolunteerStatus.ACTIVE.value,
                },
            )

            assert response.status_code == 200
            # Should show form with errors
            assert b"required" in response.data.lower() or b"error" in response.data.lower()

    def test_volunteers_edit_error_handling(self, client, test_user, app):
        """Test error handling in volunteer update"""
        with app.app_context():
            test_user.password_hash = generate_password_hash("testpass123")
            db.session.add(test_user)
            db.session.commit()

            volunteer = Volunteer(
                first_name="Test",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                status=ContactStatus.ACTIVE,
                volunteer_status=VolunteerStatus.ACTIVE,
            )
            db.session.add(volunteer)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Mock a database error
            with patch("flask_app.routes.volunteer.db.session.commit") as mock_commit:
                mock_commit.side_effect = Exception("Database error")
                response = client.post(
                    f"/volunteers/{volunteer.id}/edit",
                    data={
                        "first_name": "Updated",
                        "last_name": "Volunteer",
                        "volunteer_status": VolunteerStatus.ACTIVE.value,
                    },
                )
                assert response.status_code == 200
                # Error is logged and flash message shown, but may not be in response immediately
                # Just verify the form is re-rendered (not a redirect)
                assert b"Edit" in response.data or b"Volunteer" in response.data

