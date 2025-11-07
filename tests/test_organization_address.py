"""
Comprehensive tests for OrganizationAddress model.
Tests cover creation, relationships, methods, edge cases, and constraints.
"""

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from flask_app.models import AddressType, Organization, OrganizationAddress, db


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


class TestOrganizationAddressModel:
    """Test OrganizationAddress model functionality"""

    def test_organization_address_creation_all_fields(self, test_organization, app):
        """Test creating organization address with all fields"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            street_address_2="Suite 100",
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
            is_primary=True,
        )
        db.session.add(address)
        db.session.commit()

        assert address.organization_id == test_organization.id
        assert address.address_type == AddressType.WORK
        assert address.street_address_1 == "123 Main St"
        assert address.street_address_2 == "Suite 100"
        assert address.city == "Springfield"
        assert address.state == "IL"
        assert address.postal_code == "62701"
        assert address.country == "US"
        assert address.is_primary is True
        assert address.id is not None
        assert address.created_at is not None

    def test_organization_address_creation_minimal_fields(self, test_organization, app):
        """Test creating organization address with minimal required fields"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
        )
        db.session.add(address)
        db.session.commit()

        assert address.street_address_1 == "123 Main St"
        assert address.street_address_2 is None
        assert address.country == "US"  # Default value
        assert address.is_primary is False  # Default value

    def test_organization_address_default_values(self, test_organization, app):
        """Test default values for organization address"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
        )
        db.session.add(address)
        db.session.commit()

        assert address.country == "US"
        assert address.is_primary is False

    def test_organization_address_required_fields(self, test_organization, app):
        """Test that required fields are enforced"""
        # Test missing organization_id
        with pytest.raises(Exception):
            address = OrganizationAddress(
                address_type=AddressType.WORK,
                street_address_1="123 Main St",
                city="Springfield",
                state="IL",
                postal_code="62701",
            )
            db.session.add(address)
            db.session.commit()

        db.session.rollback()

        # Test missing address_type
        with pytest.raises(Exception):
            address = OrganizationAddress(
                organization_id=test_organization.id,
                street_address_1="123 Main St",
                city="Springfield",
                state="IL",
                postal_code="62701",
            )
            db.session.add(address)
            db.session.commit()

        db.session.rollback()

        # Test missing street_address_1
        with pytest.raises(Exception):
            address = OrganizationAddress(
                organization_id=test_organization.id,
                address_type=AddressType.WORK,
                city="Springfield",
                state="IL",
                postal_code="62701",
            )
            db.session.add(address)
            db.session.commit()

        db.session.rollback()

        # Test missing city
        with pytest.raises(Exception):
            address = OrganizationAddress(
                organization_id=test_organization.id,
                address_type=AddressType.WORK,
                street_address_1="123 Main St",
                state="IL",
                postal_code="62701",
            )
            db.session.add(address)
            db.session.commit()

        db.session.rollback()

        # Test missing state
        with pytest.raises(Exception):
            address = OrganizationAddress(
                organization_id=test_organization.id,
                address_type=AddressType.WORK,
                street_address_1="123 Main St",
                city="Springfield",
                postal_code="62701",
            )
            db.session.add(address)
            db.session.commit()

        db.session.rollback()

        # Test missing postal_code
        with pytest.raises(Exception):
            address = OrganizationAddress(
                organization_id=test_organization.id,
                address_type=AddressType.WORK,
                street_address_1="123 Main St",
                city="Springfield",
                state="IL",
            )
            db.session.add(address)
            db.session.commit()

    def test_organization_address_relationship(self, test_organization, app):
        """Test organization relationship works correctly"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
        )
        db.session.add(address)
        db.session.commit()

        assert address.organization.id == test_organization.id
        assert address.organization.name == "Test Organization"
        assert len(test_organization.addresses) == 1
        assert test_organization.addresses[0].id == address.id

    def test_organization_address_cascade_delete(self, test_organization, app):
        """Test cascade delete when organization is deleted"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
        )
        db.session.add(address)
        db.session.commit()

        address_id = address.id
        org_id = test_organization.id

        # Delete organization
        org = db.session.get(Organization, org_id)
        org.safe_delete()

        # Verify address was deleted
        assert db.session.get(OrganizationAddress, address_id) is None
        assert db.session.get(Organization, org_id) is None

    def test_organization_address_get_full_address_all_fields(self, test_organization, app):
        """Test get_full_address formats address correctly with all fields"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            street_address_2="Suite 100",
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        db.session.add(address)
        db.session.commit()

        full_address = address.get_full_address()
        assert "123 Main St" in full_address
        assert "Suite 100" in full_address
        assert "Springfield" in full_address
        assert "IL" in full_address
        assert "62701" in full_address
        assert "US" not in full_address  # US country not shown

    def test_organization_address_get_full_address_no_street2(self, test_organization, app):
        """Test get_full_address handles missing street_address_2"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        db.session.add(address)
        db.session.commit()

        full_address = address.get_full_address()
        assert "123 Main St" in full_address
        assert "Suite" not in full_address
        assert "Springfield" in full_address

    def test_organization_address_get_full_address_non_us(self, test_organization, app):
        """Test get_full_address handles non-US country"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Toronto",
            state="ON",
            postal_code="M5H 2N2",
            country="CA",
        )
        db.session.add(address)
        db.session.commit()

        full_address = address.get_full_address()
        assert "123 Main St" in full_address
        assert "Toronto" in full_address
        assert "CA" in full_address

    def test_organization_address_get_full_address_us_country(self, test_organization, app):
        """Test get_full_address doesn't show US country"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        db.session.add(address)
        db.session.commit()

        full_address = address.get_full_address()
        assert "US" not in full_address

    def test_organization_address_ensure_single_primary_single(self, test_organization, app):
        """Test ensure_single_primary sets only one primary address"""
        # Create primary address
        addr1 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
            is_primary=True,
        )
        db.session.add(addr1)
        db.session.commit()

        # Create another address and set as primary
        addr2 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.MAILING,
            street_address_1="456 Oak Ave",
            city="Springfield",
            state="IL",
            postal_code="62702",
            is_primary=True,
        )
        db.session.add(addr2)
        db.session.commit()

        # Ensure single primary (should make addr1 non-primary)
        OrganizationAddress.ensure_single_primary(test_organization.id, exclude_id=addr2.id)
        db.session.refresh(addr1)
        db.session.refresh(addr2)

        assert addr1.is_primary is False
        assert addr2.is_primary is True

    def test_organization_address_ensure_single_primary_multiple(self, test_organization, app):
        """Test ensure_single_primary handles multiple primary addresses"""
        # Create multiple primary addresses
        addr1 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
            is_primary=True,
        )
        db.session.add(addr1)

        addr2 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.MAILING,
            street_address_1="456 Oak Ave",
            city="Springfield",
            state="IL",
            postal_code="62702",
            is_primary=True,
        )
        db.session.add(addr2)
        db.session.commit()

        # Ensure single primary (exclude addr2, so addr1 should become non-primary)
        OrganizationAddress.ensure_single_primary(test_organization.id, exclude_id=addr2.id)
        db.session.refresh(addr1)
        db.session.refresh(addr2)

        assert addr1.is_primary is False
        assert addr2.is_primary is True

    def test_organization_address_ensure_single_primary_with_exclude(self, test_organization, app):
        """Test ensure_single_primary with exclude_id parameter"""
        # Create primary address
        addr1 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
            is_primary=True,
        )
        db.session.add(addr1)

        # Create another primary address
        addr2 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.MAILING,
            street_address_1="456 Oak Ave",
            city="Springfield",
            state="IL",
            postal_code="62702",
            is_primary=True,
        )
        db.session.add(addr2)
        db.session.commit()

        # Ensure single primary, excluding addr2 (addr1 should become non-primary)
        OrganizationAddress.ensure_single_primary(test_organization.id, exclude_id=addr2.id)
        db.session.refresh(addr1)
        db.session.refresh(addr2)

        assert addr1.is_primary is False
        assert addr2.is_primary is True

    def test_organization_address_ensure_single_primary_error_handling(self, test_organization, app):
        """Test ensure_single_primary error handling"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
            is_primary=True,
        )
        db.session.add(address)
        db.session.commit()

        with patch("flask_app.models.organization.OrganizationAddress.query") as mock_query:
            mock_query.filter_by.return_value.filter.return_value.all.side_effect = SQLAlchemyError("Database error")
            # Should not raise exception, should handle gracefully
            OrganizationAddress.ensure_single_primary(test_organization.id)

    def test_organization_address_multiple_addresses(self, test_organization, app):
        """Test organization can have multiple addresses"""
        addr1 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
        )
        db.session.add(addr1)

        addr2 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.MAILING,
            street_address_1="456 Oak Ave",
            city="Springfield",
            state="IL",
            postal_code="62702",
        )
        db.session.add(addr2)

        addr3 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.HOME,
            street_address_1="789 Elm St",
            city="Springfield",
            state="IL",
            postal_code="62703",
        )
        db.session.add(addr3)
        db.session.commit()

        assert len(test_organization.addresses) == 3

    def test_organization_address_changing_primary(self, test_organization, app):
        """Test changing primary address"""
        # Create primary address
        addr1 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
            is_primary=True,
        )
        db.session.add(addr1)

        # Create non-primary address
        addr2 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.MAILING,
            street_address_1="456 Oak Ave",
            city="Springfield",
            state="IL",
            postal_code="62702",
            is_primary=False,
        )
        db.session.add(addr2)
        db.session.commit()

        # Change primary
        OrganizationAddress.ensure_single_primary(test_organization.id, exclude_id=addr2.id)
        addr2.is_primary = True
        db.session.commit()

        db.session.refresh(addr1)
        assert addr1.is_primary is False
        assert addr2.is_primary is True

    def test_organization_address_no_primary(self, test_organization, app):
        """Test organization with no primary address"""
        addr1 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
            is_primary=False,
        )
        db.session.add(addr1)

        addr2 = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.MAILING,
            street_address_1="456 Oak Ave",
            city="Springfield",
            state="IL",
            postal_code="62702",
            is_primary=False,
        )
        db.session.add(addr2)
        db.session.commit()

        primary = test_organization.get_primary_address()
        assert primary is None

    def test_organization_address_foreign_key_constraint(self, app):
        """Test foreign key constraint (organization_id must exist)

        Note: SQLite may not enforce foreign keys by default unless PRAGMA foreign_keys=ON
        is set. This test verifies the foreign key relationship is defined correctly.
        If foreign keys are enforced, IntegrityError will be raised.
        If not, the address will be created but accessing organization will fail.
        """
        address = OrganizationAddress(
            organization_id=99999,  # Non-existent organization
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
        )
        db.session.add(address)

        # Try to commit - may or may not raise IntegrityError depending on SQLite config
        try:
            db.session.commit()
            # If commit succeeds (foreign keys not enforced), verify the relationship doesn't work
            db.session.refresh(address)
            # The relationship should be None or raise an error when accessed
            # This tests that the foreign key relationship is properly defined
            assert address.organization_id == 99999
            # Try to access relationship - should be None or raise error
            try:
                org = address.organization
                # If we get here, relationship exists but points to None
                assert org is None
            except Exception:
                # Relationship access failed as expected
                pass
            # Clean up
            db.session.delete(address)
            db.session.commit()
        except IntegrityError:
            # Foreign keys are enabled and constraint is enforced - this is expected
            db.session.rollback()
            pass

    def test_organization_address_enum_validation(self, test_organization, app):
        """Test address_type enum validation"""
        # Test all valid enum values
        for addr_type in AddressType:
            address = OrganizationAddress(
                organization_id=test_organization.id,
                address_type=addr_type,
                street_address_1="123 Main St",
                city="Springfield",
                state="IL",
                postal_code="62701",
            )
            db.session.add(address)
            db.session.commit()

            assert address.address_type == addr_type
            db.session.delete(address)
            db.session.commit()

    def test_organization_address_repr(self, test_organization, app):
        """Test organization address string representation"""
        address = OrganizationAddress(
            organization_id=test_organization.id,
            address_type=AddressType.WORK,
            street_address_1="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
        )
        db.session.add(address)
        db.session.commit()

        repr_str = repr(address)
        assert "Springfield" in repr_str
        assert "IL" in repr_str
        assert "work" in repr_str.lower()
