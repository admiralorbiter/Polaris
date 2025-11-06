"""
Comprehensive tests for Contact models and related functionality.
Tests cover base Contact model, sub-classes, relationships, validations, and edge cases.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from flask_app.models import (
    AddressType,
    AgeGroup,
    ClearanceStatus,
    Contact,
    ContactAddress,
    ContactEmail,
    ContactOrganization,
    ContactPhone,
    ContactRole,
    ContactStatus,
    ContactTag,
    ContactType,
    EducationLevel,
    EmailType,
    EmergencyContact,
    Gender,
    Organization,
    PhoneType,
    PreferredLanguage,
    RaceEthnicity,
    RoleType,
    Salutation,
    Student,
    Teacher,
    Volunteer,
    VolunteerAvailability,
    VolunteerHours,
    VolunteerInterest,
    VolunteerSkill,
    VolunteerStatus,
    db,
)


@pytest.fixture
def test_organization(app):
    """Create a test organization
    Note: app_context fixture is autouse, so app context is already available
    """
    org = Organization(name="Test Organization", slug="test-org")
    db.session.add(org)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return org


@pytest.fixture
def test_contact(app):
    """Create a basic test contact
    Note: app_context fixture is autouse, so app context is already available
    """
    contact = Contact(
        first_name="John",
        last_name="Doe",
        contact_type=ContactType.CONTACT,
        status=ContactStatus.ACTIVE,
    )
    db.session.add(contact)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return contact


@pytest.fixture
def test_volunteer(app):
    """Create a test volunteer
    Note: app_context fixture is autouse, so app context is already available
    """
    volunteer = Volunteer(
        first_name="Jane",
        last_name="Volunteer",
        contact_type=ContactType.VOLUNTEER,
        status=ContactStatus.ACTIVE,
    )
    db.session.add(volunteer)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return volunteer


@pytest.fixture
def test_student(app):
    """Create a test student
    Note: app_context fixture is autouse, so app context is already available
    """
    student = Student(
        first_name="Alice",
        last_name="Student",
        contact_type=ContactType.STUDENT,
        status=ContactStatus.ACTIVE,
    )
    db.session.add(student)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return student


@pytest.fixture
def test_teacher(app):
    """Create a test teacher
    Note: app_context fixture is autouse, so app context is already available
    """
    teacher = Teacher(
        first_name="Bob",
        last_name="Teacher",
        contact_type=ContactType.TEACHER,
        status=ContactStatus.ACTIVE,
    )
    db.session.add(teacher)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return teacher


class TestContactModel:
    """Test base Contact model functionality"""

    def test_contact_creation_minimal(self, app):
        """Test creating contact with minimal required fields"""
        with app.app_context():
            contact = Contact(first_name="Test", last_name="Contact")
            db.session.add(contact)
            db.session.commit()

            assert contact.first_name == "Test"
            assert contact.last_name == "Contact"
            assert contact.contact_type == ContactType.CONTACT
            assert contact.status == ContactStatus.ACTIVE
            assert contact.id is not None
            assert contact.created_at is not None

    def test_contact_creation_all_fields(self, app):
        """Test creating contact with all fields"""
        with app.app_context():
            birthdate = date(1990, 1, 15)
            contact = Contact(
                salutation=Salutation.MR,
                first_name="John",
                middle_name="Middle",
                last_name="Doe",
                suffix="Jr.",
                preferred_name="Johnny",
                gender=Gender.MALE,
                race=RaceEthnicity.WHITE,
                birthdate=birthdate,
                education_level=EducationLevel.BACHELORS,
                is_local=True,
                type="General",
                do_not_call=False,
                do_not_email=False,
                do_not_contact=False,
                preferred_language=PreferredLanguage.ENGLISH,
                status=ContactStatus.ACTIVE,
                source="Website",
                last_contact_date=date.today(),
                notes="Test notes",
                internal_notes="Internal notes",
                photo_url="https://example.com/photo.jpg",
            )
            db.session.add(contact)
            db.session.commit()

            assert contact.salutation == Salutation.MR
            assert contact.first_name == "John"
            assert contact.middle_name == "Middle"
            assert contact.last_name == "Doe"
            assert contact.suffix == "Jr."
            assert contact.preferred_name == "Johnny"
            assert contact.birthdate == birthdate
            assert contact.status == ContactStatus.ACTIVE

    def test_contact_repr(self, test_contact):
        """Test contact string representation"""
        assert "Contact" in repr(test_contact)
        assert "John" in repr(test_contact)

    def test_get_full_name_complete(self, app):
        """Test get_full_name with all name components"""
        with app.app_context():
            contact = Contact(
                salutation="Dr.",
                first_name="Jane",
                middle_name="Marie",
                last_name="Smith",
                suffix="III",
            )
            full_name = contact.get_full_name()
            assert full_name == "Dr. Jane Marie Smith III"

    def test_get_full_name_minimal(self, app):
        """Test get_full_name with minimal fields"""
        with app.app_context():
            contact = Contact(first_name="John", last_name="Doe")
            full_name = contact.get_full_name()
            assert full_name == "John Doe"

    def test_get_display_name_with_preferred(self, app):
        """Test get_display_name returns preferred_name when available"""
        with app.app_context():
            contact = Contact(
                first_name="John", last_name="Doe", preferred_name="Johnny"
            )
            assert contact.get_display_name() == "Johnny"

    def test_get_display_name_without_preferred(self, app):
        """Test get_display_name returns full_name when no preferred_name"""
        with app.app_context():
            contact = Contact(first_name="John", last_name="Doe")
            assert contact.get_display_name() == "John Doe"

    def test_validate_birthdate_future(self, app):
        """Test birthdate validation rejects future dates"""
        with app.app_context():
            future_date = date.today() + timedelta(days=1)
            contact = Contact(first_name="Test", last_name="Contact")
            # Validation happens on attribute assignment, not commit
            with pytest.raises(ValueError, match="cannot be in the future"):
                contact.birthdate = future_date

    def test_validate_birthdate_past(self, app):
        """Test birthdate validation accepts past dates"""
        with app.app_context():
            past_date = date(1990, 1, 1)
            contact = Contact(first_name="Test", last_name="Contact", birthdate=past_date)
            db.session.add(contact)
            db.session.commit()
            assert contact.birthdate == past_date

    def test_calculate_age(self, app):
        """Test age calculation from birthdate"""
        with app.app_context():
            birthdate = date.today().replace(year=date.today().year - 25)
            contact = Contact(first_name="Test", last_name="Contact", birthdate=birthdate)
            age = contact.calculate_age()
            assert age == 25

    def test_calculate_age_no_birthdate(self, app):
        """Test age calculation returns None when no birthdate"""
        with app.app_context():
            contact = Contact(first_name="Test", last_name="Contact")
            assert contact.calculate_age() is None

    def test_get_age_group_child(self, app):
        """Test age group calculation for child"""
        with app.app_context():
            birthdate = date.today().replace(year=date.today().year - 10)
            contact = Contact(first_name="Test", last_name="Contact", birthdate=birthdate)
            assert contact.get_age_group() == AgeGroup.CHILD

    def test_get_age_group_teen(self, app):
        """Test age group calculation for teen"""
        with app.app_context():
            birthdate = date.today().replace(year=date.today().year - 15)
            contact = Contact(first_name="Test", last_name="Contact", birthdate=birthdate)
            assert contact.get_age_group() == AgeGroup.TEEN

    def test_get_age_group_adult(self, app):
        """Test age group calculation for adult"""
        with app.app_context():
            birthdate = date.today().replace(year=date.today().year - 30)
            contact = Contact(first_name="Test", last_name="Contact", birthdate=birthdate)
            assert contact.get_age_group() == AgeGroup.ADULT

    def test_get_age_group_senior(self, app):
        """Test age group calculation for senior"""
        with app.app_context():
            birthdate = date.today().replace(year=date.today().year - 70)
            contact = Contact(first_name="Test", last_name="Contact", birthdate=birthdate)
            assert contact.get_age_group() == AgeGroup.SENIOR

    def test_update_age_group(self, app):
        """Test updating stored age_group"""
        with app.app_context():
            birthdate = date.today().replace(year=date.today().year - 20)
            contact = Contact(first_name="Test", last_name="Contact", birthdate=birthdate)
            db.session.add(contact)
            db.session.commit()

            result = contact.update_age_group()
            assert result is True
            assert contact.age_group == AgeGroup.ADULT

    def test_can_contact_allowed(self, app):
        """Test can_contact when all preferences allow"""
        with app.app_context():
            contact = Contact(
                first_name="Test",
                last_name="Contact",
                do_not_contact=False,
                do_not_call=False,
                do_not_email=False,
            )
            assert contact.can_contact() is True
            assert contact.can_contact("call") is True
            assert contact.can_contact("email") is True

    def test_can_contact_do_not_contact(self, app):
        """Test can_contact when do_not_contact is True"""
        with app.app_context():
            contact = Contact(
                first_name="Test", last_name="Contact", do_not_contact=True
            )
            assert contact.can_contact() is False
            assert contact.can_contact("call") is False
            assert contact.can_contact("email") is False

    def test_can_contact_do_not_call(self, app):
        """Test can_contact when do_not_call is True"""
        with app.app_context():
            contact = Contact(
                first_name="Test", last_name="Contact", do_not_call=True
            )
            assert contact.can_contact() is True
            assert contact.can_contact("call") is False
            assert contact.can_contact("email") is True

    def test_can_contact_do_not_email(self, app):
        """Test can_contact when do_not_email is True"""
        with app.app_context():
            contact = Contact(
                first_name="Test", last_name="Contact", do_not_email=True
            )
            assert contact.can_contact() is True
            assert contact.can_contact("call") is True
            assert contact.can_contact("email") is False

    def test_contact_required_fields(self, app):
        """Test that required fields are enforced"""
        with app.app_context():
            # Missing first_name
            with pytest.raises(Exception):
                contact = Contact(last_name="Doe")
                db.session.add(contact)
                db.session.commit()

            db.session.rollback()

            # Missing last_name
            with pytest.raises(Exception):
                contact = Contact(first_name="John")
                db.session.add(contact)
                db.session.commit()

    def test_contact_default_values(self, app):
        """Test default values for contact fields"""
        with app.app_context():
            contact = Contact(first_name="Test", last_name="Contact")
            db.session.add(contact)
            db.session.commit()

            assert contact.contact_type == ContactType.CONTACT
            assert contact.status == ContactStatus.ACTIVE
            assert contact.do_not_call is False
            assert contact.do_not_email is False
            assert contact.do_not_contact is False


class TestContactEmail:
    """Test ContactEmail model"""

    def test_contact_email_creation(self, test_contact, app):
        """Test creating contact email"""
        with app.app_context():
            email = ContactEmail(
                contact_id=test_contact.id,
                email="test@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
            db.session.add(email)
            db.session.commit()

            assert email.email == "test@example.com"
            assert email.email_type == EmailType.PERSONAL
            assert email.is_primary is True
            assert email.is_verified is False

    def test_contact_email_validation(self, test_contact, app):
        """Test email format validation"""
        with app.app_context():
            # Valid email
            email = ContactEmail(
                contact_id=test_contact.id,
                email="valid@example.com",
                email_type=EmailType.PERSONAL,
            )
            db.session.add(email)
            db.session.commit()
            assert email.email == "valid@example.com"

            # Invalid email
            with pytest.raises(ValueError):
                invalid_email = ContactEmail(
                    contact_id=test_contact.id,
                    email="invalid-email",
                    email_type=EmailType.PERSONAL,
                )
                db.session.add(invalid_email)
                db.session.commit()

    def test_get_primary_email(self, test_contact, app):
        """Test get_primary_email helper method"""
        with app.app_context():
            primary = ContactEmail(
                contact_id=test_contact.id,
                email="primary@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
            secondary = ContactEmail(
                contact_id=test_contact.id,
                email="secondary@example.com",
                email_type=EmailType.WORK,
                is_primary=False,
            )
            db.session.add(primary)
            db.session.add(secondary)
            db.session.commit()

            assert test_contact.get_primary_email() == "primary@example.com"

    def test_get_primary_email_none(self, test_contact):
        """Test get_primary_email when no primary email exists"""
        assert test_contact.get_primary_email() is None

    def test_find_by_email(self, test_contact, app):
        """Test Contact.find_by_email static method"""
        with app.app_context():
            email = ContactEmail(
                contact_id=test_contact.id,
                email="findme@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
            db.session.add(email)
            db.session.commit()

            found = Contact.find_by_email("findme@example.com")
            assert found is not None
            assert found.id == test_contact.id

    def test_contact_email_unique_constraint(self, test_contact, app):
        """Test that email must be unique per contact"""
        with app.app_context():
            email1 = ContactEmail(
                contact_id=test_contact.id,
                email="duplicate@example.com",
                email_type=EmailType.PERSONAL,
            )
            db.session.add(email1)
            db.session.commit()

            email2 = ContactEmail(
                contact_id=test_contact.id,
                email="duplicate@example.com",
                email_type=EmailType.WORK,
            )
            db.session.add(email2)
            with pytest.raises(IntegrityError):
                db.session.commit()


class TestContactPhone:
    """Test ContactPhone model"""

    def test_contact_phone_creation(self, test_contact, app):
        """Test creating contact phone"""
        with app.app_context():
            phone = ContactPhone(
                contact_id=test_contact.id,
                phone_number="555-1234",
                phone_type=PhoneType.MOBILE,
                is_primary=True,
                can_text=True,
            )
            db.session.add(phone)
            db.session.commit()

            assert phone.phone_number == "555-1234"
            assert phone.phone_type == PhoneType.MOBILE
            assert phone.is_primary is True
            assert phone.can_text is True

    def test_get_primary_phone(self, test_contact, app):
        """Test get_primary_phone helper method"""
        with app.app_context():
            primary = ContactPhone(
                contact_id=test_contact.id,
                phone_number="555-1111",
                phone_type=PhoneType.MOBILE,
                is_primary=True,
            )
            secondary = ContactPhone(
                contact_id=test_contact.id,
                phone_number="555-2222",
                phone_type=PhoneType.HOME,
                is_primary=False,
            )
            db.session.add(primary)
            db.session.add(secondary)
            db.session.commit()

            assert test_contact.get_primary_phone() == "555-1111"

    def test_find_by_phone(self, test_contact, app):
        """Test Contact.find_by_phone static method"""
        with app.app_context():
            phone = ContactPhone(
                contact_id=test_contact.id,
                phone_number="555-FINDME",
                phone_type=PhoneType.MOBILE,
                is_primary=True,
            )
            db.session.add(phone)
            db.session.commit()

            found = Contact.find_by_phone("555-FINDME")
            assert found is not None
            assert found.id == test_contact.id


class TestContactAddress:
    """Test ContactAddress model"""

    def test_contact_address_creation(self, test_contact, app):
        """Test creating contact address"""
        with app.app_context():
            address = ContactAddress(
                contact_id=test_contact.id,
                address_type=AddressType.HOME,
                street_address_1="123 Main St",
                street_address_2="Apt 4",
                city="Springfield",
                state="IL",
                postal_code="62701",
                country="US",
                is_primary=True,
            )
            db.session.add(address)
            db.session.commit()

            assert address.street_address_1 == "123 Main St"
            assert address.city == "Springfield"
            assert address.is_primary is True

    def test_get_full_address(self, test_contact, app):
        """Test get_full_address method"""
        with app.app_context():
            address = ContactAddress(
                contact_id=test_contact.id,
                address_type=AddressType.HOME,
                street_address_1="123 Main St",
                city="Springfield",
                state="IL",
                postal_code="62701",
                country="US",
            )
            full = address.get_full_address()
            assert "123 Main St" in full
            assert "Springfield" in full
            assert "62701" in full

    def test_get_primary_address(self, test_contact, app):
        """Test get_primary_address helper method"""
        with app.app_context():
            primary = ContactAddress(
                contact_id=test_contact.id,
                address_type=AddressType.HOME,
                street_address_1="123 Primary St",
                city="Springfield",
                state="IL",
                postal_code="62701",
                is_primary=True,
            )
            secondary = ContactAddress(
                contact_id=test_contact.id,
                address_type=AddressType.WORK,
                street_address_1="456 Work St",
                city="Springfield",
                state="IL",
                postal_code="62701",
                is_primary=False,
            )
            db.session.add(primary)
            db.session.add(secondary)
            db.session.commit()

            found = test_contact.get_primary_address()
            assert found is not None
            assert found.street_address_1 == "123 Primary St"


class TestContactRole:
    """Test ContactRole model for multi-class support"""

    def test_contact_role_creation(self, test_contact, app):
        """Test creating contact role"""
        with app.app_context():
            role = ContactRole(
                contact_id=test_contact.id,
                role_type=RoleType.VOLUNTEER,
                start_date=date.today(),
            )
            db.session.add(role)
            db.session.commit()

            assert role.role_type == RoleType.VOLUNTEER
            assert role.is_active is True
            assert role.end_date is None

    def test_has_role(self, test_contact, app):
        """Test has_role method"""
        with app.app_context():
            role = ContactRole(
                contact_id=test_contact.id,
                role_type=RoleType.VOLUNTEER,
                start_date=date.today(),
            )
            db.session.add(role)
            db.session.commit()

            assert test_contact.has_role(RoleType.VOLUNTEER) is True
            assert test_contact.has_role(RoleType.STUDENT) is False

    def test_get_active_roles(self, test_contact, app):
        """Test get_active_roles method"""
        with app.app_context():
            role1 = ContactRole(
                contact_id=test_contact.id,
                role_type=RoleType.VOLUNTEER,
                start_date=date.today(),
            )
            role2 = ContactRole(
                contact_id=test_contact.id,
                role_type=RoleType.STUDENT,
                start_date=date.today(),
            )
            db.session.add(role1)
            db.session.add(role2)
            db.session.commit()

            active_roles = test_contact.get_active_roles()
            assert RoleType.VOLUNTEER in active_roles
            assert RoleType.STUDENT in active_roles

    def test_add_role(self, test_contact, app):
        """Test add_role method"""
        with app.app_context():
            role, error = test_contact.add_role(RoleType.VOLUNTEER)
            assert role is not None
            assert error is None
            assert role.role_type == RoleType.VOLUNTEER
            assert test_contact.has_role(RoleType.VOLUNTEER) is True

    def test_add_role_duplicate(self, test_contact, app):
        """Test adding duplicate role"""
        with app.app_context():
            test_contact.add_role(RoleType.VOLUNTEER)
            role, error = test_contact.add_role(RoleType.VOLUNTEER)
            # Should return existing role
            assert role is not None

    def test_end_role(self, test_contact, app):
        """Test end_role method"""
        with app.app_context():
            test_contact.add_role(RoleType.VOLUNTEER)
            result, error = test_contact.end_role(RoleType.VOLUNTEER)
            assert result is True
            assert error is None
            assert test_contact.has_role(RoleType.VOLUNTEER) is False

    def test_end_role_nonexistent(self, test_contact, app):
        """Test ending non-existent role"""
        with app.app_context():
            result, error = test_contact.end_role(RoleType.VOLUNTEER)
            assert result is False
            assert "not found" in error.lower()

    def test_role_deactivate(self, test_contact, app):
        """Test role deactivate method"""
        with app.app_context():
            role = ContactRole(
                contact_id=test_contact.id,
                role_type=RoleType.VOLUNTEER,
                start_date=date.today(),
            )
            db.session.add(role)
            db.session.commit()

            result = role.deactivate()
            assert result is True
            assert role.is_active is False
            assert role.end_date is not None


class TestContactSubclasses:
    """Test sub-class models (Volunteer, Student, Teacher)"""

    def test_volunteer_creation(self, app):
        """Test creating volunteer with new fields"""
        with app.app_context():
            from datetime import date

            volunteer = Volunteer(
                first_name="Jane",
                last_name="Volunteer",
                contact_type=ContactType.VOLUNTEER,
                volunteer_status=VolunteerStatus.ACTIVE,
                title="Software Engineer",
                industry="Technology",
                clearance_status=ClearanceStatus.APPROVED,
                first_volunteer_date=date(2024, 1, 1),
            )
            db.session.add(volunteer)
            db.session.commit()

            assert volunteer.contact_type == ContactType.VOLUNTEER
            assert volunteer.volunteer_status == VolunteerStatus.ACTIVE
            assert volunteer.title == "Software Engineer"
            assert volunteer.industry == "Technology"
            assert volunteer.clearance_status == ClearanceStatus.APPROVED
            assert volunteer.first_volunteer_date == date(2024, 1, 1)
            assert volunteer.total_volunteer_hours == 0.0
            assert isinstance(volunteer, Contact)
            assert isinstance(volunteer, Volunteer)

    def test_student_creation(self, app):
        """Test creating student"""
        with app.app_context():
            student = Student(
                first_name="Alice",
                last_name="Student",
                contact_type=ContactType.STUDENT,
                grade="10",
                student_id="STU001",
            )
            db.session.add(student)
            db.session.commit()

            assert student.contact_type == ContactType.STUDENT
            assert student.grade == "10"
            assert student.student_id == "STU001"
            assert isinstance(student, Contact)
            assert isinstance(student, Student)

    def test_teacher_creation(self, app):
        """Test creating teacher"""
        with app.app_context():
            teacher = Teacher(
                first_name="Bob",
                last_name="Teacher",
                contact_type=ContactType.TEACHER,
                certification="State Certified",
                employee_id="EMP001",
            )
            db.session.add(teacher)
            db.session.commit()

            assert teacher.contact_type == ContactType.TEACHER
            assert teacher.certification == "State Certified"
            assert teacher.employee_id == "EMP001"
            assert isinstance(teacher, Contact)
            assert isinstance(teacher, Teacher)

    def test_student_unique_student_id(self, app):
        """Test student_id unique constraint"""
        with app.app_context():
            student1 = Student(
                first_name="Alice",
                last_name="Student",
                contact_type=ContactType.STUDENT,
                student_id="STU001",
            )
            db.session.add(student1)
            db.session.commit()

            student2 = Student(
                first_name="Bob",
                last_name="Student",
                contact_type=ContactType.STUDENT,
                student_id="STU001",
            )
            db.session.add(student2)
            with pytest.raises(IntegrityError):
                db.session.commit()

    def test_teacher_unique_employee_id(self, app):
        """Test employee_id unique constraint"""
        with app.app_context():
            teacher1 = Teacher(
                first_name="Bob",
                last_name="Teacher",
                contact_type=ContactType.TEACHER,
                employee_id="EMP001",
            )
            db.session.add(teacher1)
            db.session.commit()

            teacher2 = Teacher(
                first_name="Alice",
                last_name="Teacher",
                contact_type=ContactType.TEACHER,
                employee_id="EMP001",
            )
            db.session.add(teacher2)
            with pytest.raises(IntegrityError):
                db.session.commit()


class TestVolunteerEnhanced:
    """Test enhanced Volunteer model with new fields and relationships"""

    def test_volunteer_status_enum(self, app):
        """Test volunteer status enum values"""
        with app.app_context():
            volunteer = Volunteer(
                first_name="Test",
                last_name="Volunteer",
                volunteer_status=VolunteerStatus.HOLD,
            )
            db.session.add(volunteer)
            db.session.commit()

            assert volunteer.volunteer_status == VolunteerStatus.HOLD

    def test_volunteer_core_fields(self, app):
        """Test all core volunteer fields"""
        with app.app_context():
            from datetime import date

            volunteer = Volunteer(
                first_name="John",
                last_name="Doe",
                volunteer_status=VolunteerStatus.ACTIVE,
                title="Manager",
                industry="Non-profit",
                clearance_status=ClearanceStatus.PENDING,
                first_volunteer_date=date(2023, 6, 1),
                last_volunteer_date=date(2024, 12, 15),
                total_volunteer_hours=150.5,
            )
            db.session.add(volunteer)
            db.session.commit()

            assert volunteer.title == "Manager"
            assert volunteer.industry == "Non-profit"
            assert volunteer.first_volunteer_date == date(2023, 6, 1)
            assert volunteer.last_volunteer_date == date(2024, 12, 15)
            assert float(volunteer.total_volunteer_hours) == 150.5

    def test_volunteer_skill_creation(self, test_volunteer, app):
        """Test creating volunteer skill"""
        with app.app_context():
            skill = VolunteerSkill(
                volunteer_id=test_volunteer.id,
                skill_name="Python Programming",
                skill_category="Technical",
                proficiency_level="Advanced",
                verified=True,
            )
            db.session.add(skill)
            db.session.commit()

            assert skill.skill_name == "Python Programming"
            assert skill.skill_category == "Technical"
            assert skill.proficiency_level == "Advanced"
            assert skill.verified is True

    def test_volunteer_add_skill(self, test_volunteer, app):
        """Test add_skill helper method"""
        with app.app_context():
            skill, error = test_volunteer.add_skill(
                "JavaScript", "Technical", "Intermediate", verified=False
            )
            assert skill is not None
            assert error is None
            assert skill.skill_name == "JavaScript"

    def test_volunteer_get_skills_list(self, test_volunteer, app):
        """Test get_skills_list helper method"""
        with app.app_context():
            test_volunteer.add_skill("Python", "Technical", "Advanced", verified=True)
            test_volunteer.add_skill("Spanish", "Language", "Fluent", verified=False)

            all_skills = test_volunteer.get_skills_list()
            assert len(all_skills) == 2

            verified_skills = test_volunteer.get_skills_list(verified_only=True)
            assert len(verified_skills) == 1
            assert verified_skills[0].skill_name == "Python"

            tech_skills = test_volunteer.get_skills_list(category="Technical")
            assert len(tech_skills) == 1
            assert tech_skills[0].skill_name == "Python"

    def test_volunteer_interest_creation(self, test_volunteer, app):
        """Test creating volunteer interest"""
        with app.app_context():
            interest = VolunteerInterest(
                volunteer_id=test_volunteer.id,
                interest_name="Education",
                interest_category="Community",
            )
            db.session.add(interest)
            db.session.commit()

            assert interest.interest_name == "Education"
            assert interest.interest_category == "Community"

    def test_volunteer_add_interest(self, test_volunteer, app):
        """Test add_interest helper method"""
        with app.app_context():
            interest, error = test_volunteer.add_interest("Environment", "Community")
            assert interest is not None
            assert error is None
            assert interest.interest_name == "Environment"

    def test_volunteer_availability_creation(self, test_volunteer, app):
        """Test creating volunteer availability"""
        with app.app_context():
            from datetime import time

            availability = VolunteerAvailability(
                volunteer_id=test_volunteer.id,
                day_of_week=0,  # Monday
                start_time=time(9, 0),
                end_time=time(17, 0),
                is_recurring=True,
            )
            db.session.add(availability)
            db.session.commit()

            assert availability.day_of_week == 0
            assert availability.start_time == time(9, 0)
            assert availability.end_time == time(17, 0)
            assert availability.is_recurring is True

    def test_volunteer_add_availability(self, test_volunteer, app):
        """Test add_availability helper method"""
        with app.app_context():
            from datetime import time

            avail, error = test_volunteer.add_availability(
                1, time(10, 0), time(14, 0), is_recurring=True
            )
            assert avail is not None
            assert error is None
            assert avail.day_of_week == 1

    def test_volunteer_is_available_on_day(self, test_volunteer, app):
        """Test is_available_on_day helper method"""
        with app.app_context():
            from datetime import time

            test_volunteer.add_availability(0, time(9, 0), time(17, 0), is_recurring=True)
            test_volunteer.add_availability(2, time(10, 0), time(14, 0), is_recurring=True)

            assert test_volunteer.is_available_on_day(0) is True
            assert test_volunteer.is_available_on_day(1) is False
            assert test_volunteer.is_available_on_day(2) is True

    def test_volunteer_hours_creation(self, test_volunteer, test_organization, app):
        """Test creating volunteer hours"""
        with app.app_context():
            from datetime import date

            hours = VolunteerHours(
                volunteer_id=test_volunteer.id,
                organization_id=test_organization.id,
                volunteer_date=date(2024, 1, 15),
                hours_worked=4.5,
                activity_type="Event Support",
            )
            db.session.add(hours)
            db.session.commit()

            assert hours.volunteer_date == date(2024, 1, 15)
            assert float(hours.hours_worked) == 4.5
            assert hours.activity_type == "Event Support"

    def test_volunteer_log_hours(self, test_volunteer, test_organization, app):
        """Test log_hours helper method"""
        with app.app_context():
            from datetime import date

            hours_entry, error = test_volunteer.log_hours(
                date(2024, 1, 10),
                3.5,
                organization_id=test_organization.id,
                activity_type="Tutoring",
            )
            assert hours_entry is not None
            assert error is None
            assert float(hours_entry.hours_worked) == 3.5
            assert float(test_volunteer.total_volunteer_hours) == 3.5
            assert test_volunteer.first_volunteer_date == date(2024, 1, 10)
            assert test_volunteer.last_volunteer_date == date(2024, 1, 10)

    def test_volunteer_get_total_hours(self, test_volunteer, app):
        """Test get_total_hours helper method"""
        with app.app_context():
            from datetime import date

            test_volunteer.log_hours(date(2024, 1, 1), 2.0)
            test_volunteer.log_hours(date(2024, 1, 2), 3.5)

            total = test_volunteer.get_total_hours()
            assert total == 5.5

            # Test recalculate
            total_recalc = test_volunteer.get_total_hours(recalculate=True)
            assert total_recalc == 5.5

    def test_volunteer_get_hours_by_date_range(self, test_volunteer, app):
        """Test get_hours_by_date_range helper method"""
        with app.app_context():
            from datetime import date

            test_volunteer.log_hours(date(2024, 1, 5), 2.0)
            test_volunteer.log_hours(date(2024, 1, 10), 3.0)
            test_volunteer.log_hours(date(2024, 2, 1), 4.0)

            hours = test_volunteer.get_hours_by_date_range(date(2024, 1, 1), date(2024, 1, 31))
            assert len(hours) == 2

    def test_volunteer_get_hours_by_organization(
        self, test_volunteer, test_organization, app
    ):
        """Test get_hours_by_organization helper method"""
        with app.app_context():
            from datetime import date

            # Create another org
            org2 = Organization(name="Org 2", slug="org-2")
            db.session.add(org2)
            db.session.commit()

            test_volunteer.log_hours(date(2024, 1, 1), 2.0, organization_id=test_organization.id)
            test_volunteer.log_hours(date(2024, 1, 2), 3.0, organization_id=org2.id)

            hours = test_volunteer.get_hours_by_organization(test_organization.id)
            assert len(hours) == 1
            assert float(hours[0].hours_worked) == 2.0

    def test_volunteer_skill_unique_constraint(self, test_volunteer, app):
        """Test that skill must be unique per volunteer"""
        with app.app_context():
            skill1 = VolunteerSkill(
                volunteer_id=test_volunteer.id, skill_name="Python", skill_category="Technical"
            )
            db.session.add(skill1)
            db.session.commit()

            skill2 = VolunteerSkill(
                volunteer_id=test_volunteer.id, skill_name="Python", skill_category="Language"
            )
            db.session.add(skill2)
            with pytest.raises(IntegrityError):
                db.session.commit()

    def test_volunteer_interest_unique_constraint(self, test_volunteer, app):
        """Test that interest must be unique per volunteer"""
        with app.app_context():
            interest1 = VolunteerInterest(
                volunteer_id=test_volunteer.id, interest_name="Education"
            )
            db.session.add(interest1)
            db.session.commit()

            interest2 = VolunteerInterest(
                volunteer_id=test_volunteer.id, interest_name="Education"
            )
            db.session.add(interest2)
            with pytest.raises(IntegrityError):
                db.session.commit()

    def test_volunteer_availability_time_constraint(self, test_volunteer, app):
        """Test that end_time must be after start_time"""
        with app.app_context():
            from datetime import time

            # This should fail validation
            availability = VolunteerAvailability(
                volunteer_id=test_volunteer.id,
                day_of_week=0,
                start_time=time(17, 0),
                end_time=time(9, 0),  # End before start
            )
            db.session.add(availability)
            with pytest.raises(Exception):  # Should raise constraint error
                db.session.commit()

    def test_volunteer_hours_positive_constraint(self, test_volunteer, app):
        """Test that hours_worked must be positive"""
        with app.app_context():
            from datetime import date

            hours = VolunteerHours(
                volunteer_id=test_volunteer.id,
                volunteer_date=date(2024, 1, 1),
                hours_worked=-1.0,  # Negative hours
            )
            db.session.add(hours)
            with pytest.raises(Exception):  # Should raise constraint error
                db.session.commit()


class TestContactOrganization:
    """Test ContactOrganization junction table"""

    def test_contact_organization_creation(self, test_contact, test_organization, app):
        """Test creating contact-organization link"""
        with app.app_context():
            link = ContactOrganization(
                contact_id=test_contact.id,
                organization_id=test_organization.id,
                is_primary=True,
                start_date=date.today(),
            )
            db.session.add(link)
            db.session.commit()

            assert link.contact_id == test_contact.id
            assert link.organization_id == test_organization.id
            assert link.is_primary is True

    def test_contact_organization_unique_constraint(
        self, test_contact, test_organization, app
    ):
        """Test unique constraint on contact-organization"""
        with app.app_context():
            link1 = ContactOrganization(
                contact_id=test_contact.id,
                organization_id=test_organization.id,
            )
            db.session.add(link1)
            db.session.commit()

            link2 = ContactOrganization(
                contact_id=test_contact.id,
                organization_id=test_organization.id,
            )
            db.session.add(link2)
            with pytest.raises(IntegrityError):
                db.session.commit()


class TestContactTag:
    """Test ContactTag model"""

    def test_contact_tag_creation(self, test_contact, app):
        """Test creating contact tag"""
        with app.app_context():
            tag = ContactTag(contact_id=test_contact.id, tag_name="vip")
            db.session.add(tag)
            db.session.commit()

            assert tag.tag_name == "vip"
            assert tag.contact_id == test_contact.id

    def test_contact_tag_unique_constraint(self, test_contact, app):
        """Test unique constraint on contact-tag"""
        with app.app_context():
            tag1 = ContactTag(contact_id=test_contact.id, tag_name="vip")
            db.session.add(tag1)
            db.session.commit()

            tag2 = ContactTag(contact_id=test_contact.id, tag_name="vip")
            db.session.add(tag2)
            with pytest.raises(IntegrityError):
                db.session.commit()


class TestEmergencyContact:
    """Test EmergencyContact model"""

    def test_emergency_contact_creation(self, test_contact, app):
        """Test creating emergency contact"""
        with app.app_context():
            emergency = EmergencyContact(
                contact_id=test_contact.id,
                first_name="Emergency",
                last_name="Contact",
                relationship="Parent",
                phone_number="555-9999",
                email="emergency@example.com",
                is_primary=True,
            )
            db.session.add(emergency)
            db.session.commit()

            assert emergency.first_name == "Emergency"
            assert emergency.relationship == "Parent"
            assert emergency.is_primary is True

    def test_emergency_contact_get_full_name(self, test_contact, app):
        """Test get_full_name method"""
        with app.app_context():
            emergency = EmergencyContact(
                contact_id=test_contact.id,
                first_name="Emergency",
                last_name="Contact",
            )
            assert emergency.get_full_name() == "Emergency Contact"


class TestContactEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_contact_with_no_emails_phones_addresses(self, app):
        """Test contact with no related records"""
        with app.app_context():
            contact = Contact(first_name="Minimal", last_name="Contact")
            db.session.add(contact)
            db.session.commit()

            assert contact.get_primary_email() is None
            assert contact.get_primary_phone() is None
            assert contact.get_primary_address() is None
            assert contact.get_active_roles() == []

    def test_contact_multiple_roles(self, test_contact, app):
        """Test contact with multiple active roles"""
        with app.app_context():
            test_contact.add_role(RoleType.VOLUNTEER)
            test_contact.add_role(RoleType.STUDENT)
            test_contact.add_role(RoleType.TEACHER)

            active_roles = test_contact.get_active_roles()
            assert len(active_roles) == 3
            assert RoleType.VOLUNTEER in active_roles
            assert RoleType.STUDENT in active_roles
            assert RoleType.TEACHER in active_roles

    def test_contact_role_history(self, test_contact, app):
        """Test role history with start and end dates"""
        with app.app_context():
            # Add role
            role, _ = test_contact.add_role(RoleType.VOLUNTEER, start_date=date(2020, 1, 1))
            assert role.start_date == date(2020, 1, 1)

            # End role - returns (result, error) tuple
            result, error = test_contact.end_role(RoleType.VOLUNTEER, end_date=date(2023, 12, 31))
            assert result is True
            assert error is None
            assert test_contact.has_role(RoleType.VOLUNTEER) is False

            # Can add same role again after ending
            new_role, _ = test_contact.add_role(RoleType.VOLUNTEER, start_date=date(2024, 1, 1))
            assert new_role.start_date == date(2024, 1, 1)
            # Reload contact from database to refresh relationships
            contact_id = test_contact.id
            db.session.expire_all()
            reloaded_contact = db.session.get(Contact, contact_id)
            assert reloaded_contact.has_role(RoleType.VOLUNTEER) is True

    def test_can_volunteer_in_person(self, app):
        """Test can_volunteer_in_person method"""
        with app.app_context():
            contact = Contact(first_name="Test", last_name="Contact", is_local=True)
            assert contact.can_volunteer_in_person() is True

            contact2 = Contact(first_name="Test", last_name="Contact", is_local=False)
            assert contact2.can_volunteer_in_person() is False

    def test_update_age_group_error_handling(self, app):
        """Test update_age_group error handling"""
        with app.app_context():
            contact = Contact(
                first_name="Test",
                last_name="Contact",
                birthdate=date(1990, 1, 1),
            )
            db.session.add(contact)
            db.session.commit()

            # Mock database error
            with patch("flask_app.models.contact.base.db.session.commit") as mock_commit:
                mock_commit.side_effect = SQLAlchemyError("Database error")
                result = contact.update_age_group()
                assert result is False

    def test_find_by_email_error_handling(self, app):
        """Test find_by_email error handling"""
        with app.app_context():
            # Mock database error - patch the imported ContactEmail inside the method
            with patch("flask_app.models.contact.info.ContactEmail.query") as mock_query:
                mock_query.filter_by.return_value.first.side_effect = SQLAlchemyError("Database error")
                result = Contact.find_by_email("test@example.com")
                assert result is None

    def test_find_by_phone_error_handling(self, app):
        """Test find_by_phone error handling"""
        with app.app_context():
            # Mock database error - patch the imported ContactPhone inside the method
            with patch("flask_app.models.contact.info.ContactPhone.query") as mock_query:
                mock_query.filter_by.return_value.first.side_effect = SQLAlchemyError("Database error")
                result = Contact.find_by_phone("555-1234")
                assert result is None

    def test_contact_cascade_delete_emails(self, app):
        """Test that deleting contact cascades to emails"""
        with app.app_context():
            contact = Contact(first_name="Test", last_name="Contact")
            db.session.add(contact)
            db.session.flush()

            email = ContactEmail(
                contact_id=contact.id,
                email="test@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
            db.session.add(email)
            db.session.commit()

            contact_id = contact.id
            email_id = email.id

            db.session.delete(contact)
            db.session.commit()

            # Verify email was deleted
            deleted_email = db.session.get(ContactEmail, email_id)
            assert deleted_email is None

    def test_contact_cascade_delete_phones(self, app):
        """Test that deleting contact cascades to phones"""
        with app.app_context():
            contact = Contact(first_name="Test", last_name="Contact")
            db.session.add(contact)
            db.session.flush()

            phone = ContactPhone(
                contact_id=contact.id,
                phone_number="555-1234",
                phone_type=PhoneType.MOBILE,
                is_primary=True,
            )
            db.session.add(phone)
            db.session.commit()

            contact_id = contact.id
            phone_id = phone.id

            db.session.delete(contact)
            db.session.commit()

            # Verify phone was deleted
            deleted_phone = db.session.get(ContactPhone, phone_id)
            assert deleted_phone is None

    def test_contact_cascade_delete_addresses(self, app):
        """Test that deleting contact cascades to addresses"""
        with app.app_context():
            contact = Contact(first_name="Test", last_name="Contact")
            db.session.add(contact)
            db.session.flush()

            address = ContactAddress(
                contact_id=contact.id,
                address_type=AddressType.HOME,
                street_address_1="123 Main St",
                city="Springfield",
                state="IL",
                postal_code="62701",
                is_primary=True,
            )
            db.session.add(address)
            db.session.commit()

            contact_id = contact.id
            address_id = address.id

            db.session.delete(contact)
            db.session.commit()

            # Verify address was deleted
            deleted_address = db.session.get(ContactAddress, address_id)
            assert deleted_address is None

    def test_contact_cascade_delete_roles(self, app):
        """Test that deleting contact cascades to roles"""
        with app.app_context():
            contact = Contact(first_name="Test", last_name="Contact")
            db.session.add(contact)
            db.session.flush()

            role = ContactRole(
                contact_id=contact.id,
                role_type=RoleType.VOLUNTEER,
                start_date=date.today(),
            )
            db.session.add(role)
            db.session.commit()

            contact_id = contact.id
            role_id = role.id

            db.session.delete(contact)
            db.session.commit()

            # Verify role was deleted
            deleted_role = db.session.get(ContactRole, role_id)
            assert deleted_role is None

    def test_volunteer_get_interests_list(self, test_volunteer, app):
        """Test get_interests_list helper method"""
        with app.app_context():
            test_volunteer.add_interest("Education", "Community")
            test_volunteer.add_interest("Environment", "Community")
            test_volunteer.add_interest("Technology", "Professional")

            all_interests = test_volunteer.get_interests_list()
            assert len(all_interests) == 3

            community_interests = test_volunteer.get_interests_list(category="Community")
            assert len(community_interests) == 2

    def test_volunteer_get_availability_for_day(self, test_volunteer, app):
        """Test get_availability_for_day helper method"""
        with app.app_context():
            from datetime import time

            test_volunteer.add_availability(0, time(9, 0), time(12, 0), is_recurring=True)
            test_volunteer.add_availability(0, time(13, 0), time(17, 0), is_recurring=True)

            availabilities = test_volunteer.get_availability_for_day(0)
            assert len(availabilities) == 2

            availabilities = test_volunteer.get_availability_for_day(1)
            assert len(availabilities) == 0

    def test_volunteer_is_available_on_day_with_date(self, test_volunteer, app):
        """Test is_available_on_day with date parameter"""
        with app.app_context():
            from datetime import time

            test_date = date(2024, 6, 10)  # Monday
            test_volunteer.add_availability(
                0, time(9, 0), time(17, 0), is_recurring=True, start_date=test_date
            )

            assert test_volunteer.is_available_on_day(0, date=test_date) is True
            assert test_volunteer.is_available_on_day(1, date=test_date) is False

    def test_volunteer_add_skill_error_handling(self, test_volunteer, app):
        """Test add_skill error handling"""
        with app.app_context():
            # Mock database error
            with patch("flask_app.models.contact.volunteer.db.session.commit") as mock_commit:
                mock_commit.side_effect = SQLAlchemyError("Database error")
                skill, error = test_volunteer.add_skill("Python", "Technical", "Advanced")
                assert skill is None
                assert error is not None

    def test_volunteer_add_interest_error_handling(self, test_volunteer, app):
        """Test add_interest error handling"""
        with app.app_context():
            # Mock database error
            with patch("flask_app.models.contact.volunteer.db.session.commit") as mock_commit:
                mock_commit.side_effect = SQLAlchemyError("Database error")
                interest, error = test_volunteer.add_interest("Education", "Community")
                assert interest is None
                assert error is not None

    def test_volunteer_add_availability_error_handling(self, test_volunteer, app):
        """Test add_availability error handling"""
        with app.app_context():
            from datetime import time

            # Mock database error
            with patch("flask_app.models.contact.volunteer.db.session.commit") as mock_commit:
                mock_commit.side_effect = SQLAlchemyError("Database error")
                avail, error = test_volunteer.add_availability(
                    0, time(9, 0), time(17, 0), is_recurring=True
                )
                assert avail is None
                assert error is not None

    def test_volunteer_log_hours_error_handling(self, test_volunteer, test_organization, app):
        """Test log_hours error handling"""
        with app.app_context():
            from datetime import date

            # Mock database error
            with patch("flask_app.models.contact.volunteer.db.session.commit") as mock_commit:
                mock_commit.side_effect = SQLAlchemyError("Database error")
                hours_entry, error = test_volunteer.log_hours(
                    date(2024, 1, 1), 5.0, organization_id=test_organization.id
                )
                assert hours_entry is None
                assert error is not None

    def test_volunteer_get_total_hours_recalculate(self, test_volunteer, app):
        """Test get_total_hours with recalculate=True"""
        with app.app_context():
            from datetime import date

            test_volunteer.log_hours(date(2024, 1, 1), 2.0)
            test_volunteer.log_hours(date(2024, 1, 2), 3.5)

            # Manually set total to wrong value
            test_volunteer.total_volunteer_hours = 0.0
            db.session.commit()

            # Recalculate should fix it
            total = test_volunteer.get_total_hours(recalculate=True)
            assert total == 5.5
            assert float(test_volunteer.total_volunteer_hours) == 5.5

    def test_volunteer_get_total_hours_recalculate_error(self, test_volunteer, app):
        """Test get_total_hours recalculate error handling"""
        with app.app_context():
            from datetime import date

            test_volunteer.log_hours(date(2024, 1, 1), 2.0)

            # Mock database error during recalculate
            with patch("flask_app.models.contact.volunteer.db.session.commit") as mock_commit:
                mock_commit.side_effect = SQLAlchemyError("Database error")
                # Should still return current total even if recalculate fails
                total = test_volunteer.get_total_hours(recalculate=True)
                assert total >= 0.0  # Should return some value

    def test_contact_email_ensure_single_primary(self, test_contact, app):
        """Test ContactEmail.ensure_single_primary static method"""
        with app.app_context():
            # Create multiple primary emails
            email1 = ContactEmail(
                contact_id=test_contact.id,
                email="primary1@example.com",
                email_type=EmailType.PERSONAL,
                is_primary=True,
            )
            email2 = ContactEmail(
                contact_id=test_contact.id,
                email="primary2@example.com",
                email_type=EmailType.WORK,
                is_primary=True,
            )
            db.session.add(email1)
            db.session.add(email2)
            db.session.commit()

            # Ensure only one primary
            ContactEmail.ensure_single_primary(test_contact.id, exclude_id=email1.id)
            db.session.commit()

            # Refresh and check
            db.session.refresh(email2)
            assert email2.is_primary is False

    def test_contact_phone_ensure_single_primary(self, test_contact, app):
        """Test ContactPhone.ensure_single_primary static method"""
        with app.app_context():
            # Create multiple primary phones
            phone1 = ContactPhone(
                contact_id=test_contact.id,
                phone_number="555-1111",
                phone_type=PhoneType.MOBILE,
                is_primary=True,
            )
            phone2 = ContactPhone(
                contact_id=test_contact.id,
                phone_number="555-2222",
                phone_type=PhoneType.HOME,
                is_primary=True,
            )
            db.session.add(phone1)
            db.session.add(phone2)
            db.session.commit()

            # Ensure only one primary
            ContactPhone.ensure_single_primary(test_contact.id, exclude_id=phone1.id)
            db.session.commit()

            # Refresh and check
            db.session.refresh(phone2)
            assert phone2.is_primary is False

    def test_contact_address_ensure_single_primary(self, test_contact, app):
        """Test ContactAddress.ensure_single_primary static method"""
        with app.app_context():
            # Create multiple primary addresses
            address1 = ContactAddress(
                contact_id=test_contact.id,
                address_type=AddressType.HOME,
                street_address_1="123 Main St",
                city="Springfield",
                state="IL",
                postal_code="62701",
                is_primary=True,
            )
            address2 = ContactAddress(
                contact_id=test_contact.id,
                address_type=AddressType.WORK,
                street_address_1="456 Work St",
                city="Springfield",
                state="IL",
                postal_code="62701",
                is_primary=True,
            )
            db.session.add(address1)
            db.session.add(address2)
            db.session.commit()

            # Ensure only one primary
            ContactAddress.ensure_single_primary(test_contact.id, exclude_id=address1.id)
            db.session.commit()

            # Refresh and check
            db.session.refresh(address2)
            assert address2.is_primary is False

