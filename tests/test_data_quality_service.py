"""Tests for data quality service"""

import pytest
from datetime import datetime

from flask_app.models import (
    Contact,
    ContactAddress,
    ContactEmail,
    ContactOrganization,
    ContactPhone,
    Event,
    Organization,
    OrganizationAddress,
    Student,
    Teacher,
    User,
    Volunteer,
    VolunteerAvailability,
    VolunteerHours,
    VolunteerInterest,
    VolunteerSkill,
    db,
)
from flask_app.services.data_quality_service import DataQualityService


@pytest.fixture
def sample_contacts(app, test_organization):
    """Create sample contacts for testing"""
    contacts = []
    for i in range(5):
        contact = Contact(
            first_name=f"Contact{i}",
            last_name="Test",
            organization_id=test_organization.id if i < 3 else None,
        )
        contacts.append(contact)
        db.session.add(contact)
    
    db.session.commit()
    return contacts


@pytest.fixture
def sample_contacts_with_emails(app, sample_contacts):
    """Create contacts with email addresses"""
    for i, contact in enumerate(sample_contacts[:3]):
        email = ContactEmail(
            contact_id=contact.id,
            email=f"contact{i}@example.com",
            email_type="primary",
        )
        db.session.add(email)
    
    db.session.commit()
    return sample_contacts


@pytest.fixture
def sample_contacts_with_phones(app, sample_contacts):
    """Create contacts with phone numbers"""
    for i, contact in enumerate(sample_contacts[:2]):
        phone = ContactPhone(
            contact_id=contact.id,
            phone_number=f"+1555555000{i}",
            phone_type="mobile",
        )
        db.session.add(phone)
    
    db.session.commit()
    return sample_contacts


@pytest.fixture
def sample_contacts_with_addresses(app, sample_contacts):
    """Create contacts with addresses"""
    for i, contact in enumerate(sample_contacts[:2]):
        address = ContactAddress(
            contact_id=contact.id,
            street_address_1=f"{i} Test Street",
            city="Test City",
            state="CA",
            postal_code="12345",
            address_type="home",
        )
        db.session.add(address)
    
    db.session.commit()
    return sample_contacts


@pytest.fixture
def sample_volunteers(app, test_organization):
    """Create sample volunteers for testing"""
    volunteers = []
    for i in range(3):
        volunteer = Volunteer(
            first_name=f"Volunteer{i}",
            last_name="Test",
            title=f"Title{i}" if i < 2 else None,
            industry=f"Industry{i}" if i < 1 else None,
        )
        volunteers.append(volunteer)
        db.session.add(volunteer)
        
        # Link volunteer to organization via ContactOrganization
        if i < 2:
            org_link = ContactOrganization(
                contact_id=volunteer.id,
                organization_id=test_organization.id,
                is_primary=True,
                end_date=None,
            )
            db.session.add(org_link)
    
    db.session.commit()
    return volunteers


@pytest.fixture
def sample_volunteers_with_skills(app, sample_volunteers):
    """Create volunteers with skills"""
    for i, volunteer in enumerate(sample_volunteers[:2]):
        skill = VolunteerSkill(
            volunteer_id=volunteer.id,
            skill_name=f"Skill{i}",
        )
        db.session.add(skill)
    
    db.session.commit()
    return sample_volunteers


@pytest.fixture
def sample_events(app, test_organization):
    """Create sample events for testing"""
    from flask_app.models.event.models import EventOrganization
    
    events = []
    for i in range(3):
        event = Event(
            title=f"Event{i}",
            description=f"Description{i}" if i < 2 else None,
            start_date=datetime(2024, 1, 1 + i),
            end_date=datetime(2024, 1, 2 + i) if i < 2 else None,
        )
        events.append(event)
        db.session.add(event)
        
        # Link event to organization
        if i < 2:
            event_org = EventOrganization(
                event_id=event.id,
                organization_id=test_organization.id,
            )
            db.session.add(event_org)
    
    db.session.commit()
    return events


@pytest.fixture
def sample_users(app, test_organization):
    """Create sample users for testing"""
    from flask_app.models import UserOrganization
    
    users = []
    for i in range(3):
        user = User(
            username=f"user{i}",
            email=f"user{i}@example.com",
            password_hash="hashed",
            first_name=f"User{i}" if i < 2 else None,
            last_name="Test" if i < 2 else None,
        )
        users.append(user)
        db.session.add(user)
        
        # Link user to organization
        if i < 2:
            user_org = UserOrganization(
                user_id=user.id,
                organization_id=test_organization.id,
                role_id=1,  # Assuming role exists
                is_active=True,
            )
            db.session.add(user_org)
    
    db.session.commit()
    return users


class TestDataQualityService:
    """Tests for DataQualityService"""

    def test_get_overall_health_score_no_data(self, app):
        """Test overall health score with no data"""
        metrics = DataQualityService.get_overall_health_score()
        assert metrics.overall_health_score == 0.0
        assert metrics.total_entities == 0
        assert len(metrics.entity_metrics) == 7  # All entity types

    def test_get_overall_health_score_with_data(self, app, sample_contacts_with_emails):
        """Test overall health score with data"""
        metrics = DataQualityService.get_overall_health_score()
        assert metrics.overall_health_score >= 0.0
        assert metrics.total_entities >= 0
        assert isinstance(metrics.timestamp, datetime)

    def test_get_entity_metrics_contact_no_org(self, app, sample_contacts):
        """Test contact metrics without organization filter"""
        metrics = DataQualityService.get_entity_metrics("contact")
        assert metrics.entity_type == "contact"
        assert metrics.total_records == 5
        assert len(metrics.fields) > 0
        assert metrics.overall_completeness >= 0.0

    def test_get_entity_metrics_contact_with_org(self, app, sample_contacts, test_organization):
        """Test contact metrics with organization filter"""
        metrics = DataQualityService.get_entity_metrics("contact", organization_id=test_organization.id)
        assert metrics.entity_type == "contact"
        assert metrics.total_records >= 0
        assert len(metrics.fields) > 0

    def test_get_entity_metrics_contact_with_emails(self, app, sample_contacts_with_emails):
        """Test contact metrics with email addresses"""
        metrics = DataQualityService.get_entity_metrics("contact")
        email_field = next((f for f in metrics.fields if f.field_name == "email"), None)
        assert email_field is not None
        assert email_field.records_with_value == 3
        assert email_field.completeness_percentage > 0.0

    def test_get_entity_metrics_contact_with_phones(self, app, sample_contacts_with_phones):
        """Test contact metrics with phone numbers"""
        metrics = DataQualityService.get_entity_metrics("contact")
        phone_field = next((f for f in metrics.fields if f.field_name == "phone"), None)
        assert phone_field is not None
        assert phone_field.records_with_value == 2
        assert phone_field.completeness_percentage > 0.0

    def test_get_entity_metrics_contact_with_addresses(self, app, sample_contacts_with_addresses):
        """Test contact metrics with addresses"""
        metrics = DataQualityService.get_entity_metrics("contact")
        address_field = next((f for f in metrics.fields if f.field_name == "address"), None)
        assert address_field is not None
        assert address_field.records_with_value == 2
        assert address_field.completeness_percentage > 0.0

    def test_get_entity_metrics_volunteer(self, app, sample_volunteers):
        """Test volunteer metrics"""
        metrics = DataQualityService.get_entity_metrics("volunteer")
        assert metrics.entity_type == "volunteer"
        assert metrics.total_records == 3
        assert len(metrics.fields) > 0

    def test_get_entity_metrics_volunteer_with_org(self, app, sample_volunteers, test_organization):
        """Test volunteer metrics with organization filter"""
        metrics = DataQualityService.get_entity_metrics("volunteer", organization_id=test_organization.id)
        assert metrics.entity_type == "volunteer"
        assert metrics.total_records >= 0

    def test_get_entity_metrics_volunteer_with_skills(self, app, sample_volunteers_with_skills):
        """Test volunteer metrics with skills"""
        metrics = DataQualityService.get_entity_metrics("volunteer")
        skills_field = next((f for f in metrics.fields if f.field_name == "skills"), None)
        assert skills_field is not None
        assert skills_field.records_with_value == 2

    def test_get_entity_metrics_event(self, app, sample_events):
        """Test event metrics"""
        metrics = DataQualityService.get_entity_metrics("event")
        assert metrics.entity_type == "event"
        assert metrics.total_records == 3
        assert len(metrics.fields) > 0

    def test_get_entity_metrics_event_with_org(self, app, sample_events, test_organization):
        """Test event metrics with organization filter"""
        metrics = DataQualityService.get_entity_metrics("event", organization_id=test_organization.id)
        assert metrics.entity_type == "event"
        assert metrics.total_records >= 0

    def test_get_entity_metrics_user(self, app, sample_users):
        """Test user metrics"""
        metrics = DataQualityService.get_entity_metrics("user")
        assert metrics.entity_type == "user"
        assert metrics.total_records >= 0
        assert len(metrics.fields) > 0

    def test_get_entity_metrics_user_with_org(self, app, sample_users, test_organization):
        """Test user metrics with organization filter"""
        metrics = DataQualityService.get_entity_metrics("user", organization_id=test_organization.id)
        assert metrics.entity_type == "user"
        assert metrics.total_records >= 0

    def test_get_entity_metrics_invalid_type(self, app):
        """Test invalid entity type"""
        with pytest.raises(ValueError, match="Unknown entity type"):
            DataQualityService.get_entity_metrics("invalid_type")

    def test_field_status_good(self, app):
        """Test field status classification - good"""
        # Create contacts with high completeness
        for i in range(10):
            contact = Contact(
                first_name=f"Contact{i}",
                last_name="Test",
                birthdate=datetime(1990, 1, 1).date() if i < 9 else None,
            )
            db.session.add(contact)
            if i < 9:
                email = ContactEmail(
                    contact_id=contact.id,
                    email=f"contact{i}@example.com",
                    email_type="primary",
                )
                db.session.add(email)
        
        db.session.commit()
        
        metrics = DataQualityService.get_entity_metrics("contact")
        email_field = next((f for f in metrics.fields if f.field_name == "email"), None)
        assert email_field is not None
        assert email_field.status == "good"  # 90% completeness

    def test_field_status_warning(self, app):
        """Test field status classification - warning"""
        # Create contacts with medium completeness
        for i in range(10):
            contact = Contact(
                first_name=f"Contact{i}",
                last_name="Test",
            )
            db.session.add(contact)
            if i < 6:  # 60% completeness
                email = ContactEmail(
                    contact_id=contact.id,
                    email=f"contact{i}@example.com",
                    email_type="primary",
                )
                db.session.add(email)
        
        db.session.commit()
        
        metrics = DataQualityService.get_entity_metrics("contact")
        email_field = next((f for f in metrics.fields if f.field_name == "email"), None)
        assert email_field is not None
        assert email_field.status == "warning"  # 60% completeness

    def test_field_status_critical(self, app):
        """Test field status classification - critical"""
        # Create contacts with low completeness
        for i in range(10):
            contact = Contact(
                first_name=f"Contact{i}",
                last_name="Test",
            )
            db.session.add(contact)
            if i < 3:  # 30% completeness
                email = ContactEmail(
                    contact_id=contact.id,
                    email=f"contact{i}@example.com",
                    email_type="primary",
                )
                db.session.add(email)
        
        db.session.commit()
        
        metrics = DataQualityService.get_entity_metrics("contact")
        email_field = next((f for f in metrics.fields if f.field_name == "email"), None)
        assert email_field is not None
        assert email_field.status == "critical"  # 30% completeness

    def test_cache_functionality(self, app, sample_contacts):
        """Test that caching works"""
        # Clear cache
        DataQualityService._clear_cache()
        
        # First call
        metrics1 = DataQualityService.get_overall_health_score()
        timestamp1 = metrics1.timestamp
        
        # Second call should use cache
        metrics2 = DataQualityService.get_overall_health_score()
        timestamp2 = metrics2.timestamp
        
        # Timestamps should be the same (cached)
        assert timestamp1 == timestamp2

    def test_contact_organization_filtering(self, app, test_organization):
        """Test contact filtering by organization via ContactOrganization"""
        # Create contact linked via ContactOrganization
        contact1 = Contact(
            first_name="Contact1",
            last_name="Test",
        )
        db.session.add(contact1)
        db.session.flush()
        
        org_link = ContactOrganization(
            contact_id=contact1.id,
            organization_id=test_organization.id,
            is_primary=True,
            end_date=None,
        )
        db.session.add(org_link)
        
        # Create contact with direct organization_id
        contact2 = Contact(
            first_name="Contact2",
            last_name="Test",
            organization_id=test_organization.id,
        )
        db.session.add(contact2)
        
        # Create contact not linked to organization
        contact3 = Contact(
            first_name="Contact3",
            last_name="Test",
        )
        db.session.add(contact3)
        
        db.session.commit()
        
        # Get metrics for organization
        metrics = DataQualityService.get_entity_metrics("contact", organization_id=test_organization.id)
        assert metrics.total_records == 2  # Should include both contact1 and contact2

    def test_volunteer_organization_filtering(self, app, test_organization):
        """Test volunteer filtering by organization"""
        # Create volunteer linked via ContactOrganization
        volunteer = Volunteer(
            first_name="Volunteer1",
            last_name="Test",
        )
        db.session.add(volunteer)
        db.session.flush()
        
        org_link = ContactOrganization(
            contact_id=volunteer.id,
            organization_id=test_organization.id,
            is_primary=True,
            end_date=None,
        )
        db.session.add(org_link)
        db.session.commit()
        
        # Get metrics for organization
        metrics = DataQualityService.get_entity_metrics("volunteer", organization_id=test_organization.id)
        assert metrics.total_records == 1

    def test_organization_metrics(self, app, test_organization):
        """Test organization metrics"""
        # Add address to organization
        address = OrganizationAddress(
            organization_id=test_organization.id,
            street_address_1="123 Test St",
            city="Test City",
            state="CA",
            postal_code="12345",
            address_type="primary",
        )
        db.session.add(address)
        db.session.commit()
        
        metrics = DataQualityService.get_entity_metrics("organization")
        assert metrics.entity_type == "organization"
        address_field = next((f for f in metrics.fields if f.field_name == "address"), None)
        assert address_field is not None
        assert address_field.records_with_value == 1

