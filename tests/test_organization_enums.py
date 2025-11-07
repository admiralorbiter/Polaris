"""
Tests for Organization-related enums.
Tests cover OrganizationType and VolunteerOrganizationStatus enums.
"""

import pytest

from flask_app.models import OrganizationType, VolunteerOrganizationStatus


class TestOrganizationType:
    """Test OrganizationType enum"""

    def test_organization_type_all_values_exist(self):
        """Test that all OrganizationType enum values exist"""
        expected_values = {"school", "business", "non_profit", "government", "other"}
        actual_values = {ot.value for ot in OrganizationType}

        assert actual_values == expected_values
        assert len(OrganizationType) == 5

    def test_organization_type_school(self):
        """Test SCHOOL enum value"""
        assert OrganizationType.SCHOOL.value == "school"
        assert isinstance(OrganizationType.SCHOOL.value, str)

    def test_organization_type_business(self):
        """Test BUSINESS enum value"""
        assert OrganizationType.BUSINESS.value == "business"
        assert isinstance(OrganizationType.BUSINESS.value, str)

    def test_organization_type_non_profit(self):
        """Test NON_PROFIT enum value"""
        assert OrganizationType.NON_PROFIT.value == "non_profit"
        assert isinstance(OrganizationType.NON_PROFIT.value, str)

    def test_organization_type_government(self):
        """Test GOVERNMENT enum value"""
        assert OrganizationType.GOVERNMENT.value == "government"
        assert isinstance(OrganizationType.GOVERNMENT.value, str)

    def test_organization_type_other(self):
        """Test OTHER enum value"""
        assert OrganizationType.OTHER.value == "other"
        assert isinstance(OrganizationType.OTHER.value, str)

    def test_organization_type_enum_values_are_strings(self):
        """Test that all enum values are strings"""
        for org_type in OrganizationType:
            assert isinstance(org_type.value, str)
            assert len(org_type.value) > 0

    def test_organization_type_can_be_used_in_database(self, app):
        """Test that OrganizationType can be used in database columns"""
        from flask_app.models import Organization, db

        with app.app_context():
            # Test each enum value can be stored
            for org_type in OrganizationType:
                org = Organization(
                    name=f"Test {org_type.value}",
                    slug=f"test-{org_type.value}",
                    organization_type=org_type,
                )
                db.session.add(org)
                db.session.commit()

                # Verify it was stored correctly
                retrieved = db.session.get(Organization, org.id)
                assert retrieved.organization_type == org_type

                # Clean up
                db.session.delete(org)
                db.session.commit()


class TestVolunteerOrganizationStatus:
    """Test VolunteerOrganizationStatus enum"""

    def test_volunteer_organization_status_all_values_exist(self):
        """Test that all VolunteerOrganizationStatus enum values exist"""
        expected_values = {"current", "past"}
        actual_values = {vos.value for vos in VolunteerOrganizationStatus}

        assert actual_values == expected_values
        assert len(VolunteerOrganizationStatus) == 2

    def test_volunteer_organization_status_current(self):
        """Test CURRENT enum value"""
        assert VolunteerOrganizationStatus.CURRENT.value == "current"
        assert isinstance(VolunteerOrganizationStatus.CURRENT.value, str)

    def test_volunteer_organization_status_past(self):
        """Test PAST enum value"""
        assert VolunteerOrganizationStatus.PAST.value == "past"
        assert isinstance(VolunteerOrganizationStatus.PAST.value, str)

    def test_volunteer_organization_status_enum_values_are_strings(self):
        """Test that all enum values are strings"""
        for status in VolunteerOrganizationStatus:
            assert isinstance(status.value, str)
            assert len(status.value) > 0

    def test_volunteer_organization_status_can_be_used_in_application_logic(self, app):
        """Test that VolunteerOrganizationStatus can be used in application logic"""
        from datetime import date

        from flask_app.models import ContactOrganization, Organization, db

        with app.app_context():
            org1 = Organization(name="Test Org 1", slug="test-org-1")
            org2 = Organization(name="Test Org 2", slug="test-org-2")
            db.session.add(org1)
            db.session.add(org2)
            db.session.commit()

            # Create contact (minimal)
            from flask_app.models import Contact, ContactStatus, ContactType

            contact = Contact(
                first_name="Test",
                last_name="Contact",
                contact_type=ContactType.CONTACT,
                status=ContactStatus.ACTIVE,
            )
            db.session.add(contact)
            db.session.commit()

            # Test CURRENT status with org1
            link_current = ContactOrganization(
                contact_id=contact.id,
                organization_id=org1.id,
                end_date=None,  # Current
            )
            db.session.add(link_current)
            db.session.commit()

            status = link_current.get_status()
            assert status == VolunteerOrganizationStatus.CURRENT

            # Test PAST status with org2 (different organization to avoid unique constraint)
            link_past = ContactOrganization(
                contact_id=contact.id,
                organization_id=org2.id,
                end_date=date.today(),  # Past
            )
            db.session.add(link_past)
            db.session.commit()

            status = link_past.get_status()
            assert status == VolunteerOrganizationStatus.PAST
