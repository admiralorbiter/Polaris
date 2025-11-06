import json

import pytest
from sqlalchemy import inspect

from flask_app.models import Organization, OrganizationFeatureFlag, SystemFeatureFlag, db
from flask_app.utils.feature_flags import get_feature_flag, set_feature_flag


class TestFeatureFlagUtilities:
    """Test feature flag utility functions"""

    def test_get_feature_flag_system_exists(self, test_system_feature_flag, app):
        """Test get_feature_flag for system flag that exists"""
        with app.app_context():
            value = get_feature_flag("test_feature")
            assert value is True

    def test_get_feature_flag_system_not_exists(self, app):
        """Test get_feature_flag for system flag that doesn't exist"""
        with app.app_context():
            value = get_feature_flag("nonexistent_flag", default=False)
            assert value is False

    def test_get_feature_flag_organization_exists(
        self, test_organization, test_organization_feature_flag, app
    ):
        """Test get_feature_flag for organization flag that exists"""
        # Store ID before object becomes detached (using inspect to avoid lazy loading)
        org_id = inspect(test_organization).identity[0]
        with app.app_context():
            value = get_feature_flag("org_test_feature", organization_id=org_id)
            assert value is True

    def test_get_feature_flag_organization_not_exists(self, test_organization, app):
        """Test get_feature_flag for organization flag that doesn't exist"""
        # Store ID before object becomes detached (using inspect to avoid lazy loading)
        org_id = inspect(test_organization).identity[0]
        with app.app_context():
            value = get_feature_flag("nonexistent_flag", organization_id=org_id, default=False)
            assert value is False

    def test_set_feature_flag_system_new(self, app):
        """Test set_feature_flag for new system flag"""
        with app.app_context():
            result = set_feature_flag("new_system_flag", True, is_system_flag=True)
            assert result is True

            flag = SystemFeatureFlag.query.filter_by(flag_name="new_system_flag").first()
            assert flag is not None
            assert flag.get_value() is True

    def test_set_feature_flag_system_update(self, test_system_feature_flag, app):
        """Test set_feature_flag for existing system flag"""
        # Store ID before object becomes detached (using inspect to avoid lazy loading)
        flag_id = inspect(test_system_feature_flag).identity[0]
        with app.app_context():
            result = set_feature_flag("test_feature", False, is_system_flag=True)
            assert result is True

            # Re-query to avoid detached instance
            flag = db.session.get(SystemFeatureFlag, flag_id)
            assert flag.get_value() is False

    def test_set_feature_flag_organization_new(self, test_organization, app):
        """Test set_feature_flag for new organization flag"""
        # Store ID before object becomes detached (using inspect to avoid lazy loading)
        org_id = inspect(test_organization).identity[0]
        with app.app_context():
            result = set_feature_flag("new_org_flag", True, organization_id=org_id)
            assert result is True

            flag = OrganizationFeatureFlag.query.filter_by(
                organization_id=org_id, flag_name="new_org_flag"
            ).first()
            assert flag is not None
            assert flag.get_value() is True

    def test_set_feature_flag_type_conversion(self, app):
        """Test set_feature_flag with different types"""
        with app.app_context():
            # Boolean
            set_feature_flag("bool_flag", True, flag_type="boolean", is_system_flag=True)
            assert get_feature_flag("bool_flag") is True

            # Integer
            set_feature_flag("int_flag", 42, flag_type="integer", is_system_flag=True)
            assert get_feature_flag("int_flag") == 42

            # String
            set_feature_flag("string_flag", "test", flag_type="string", is_system_flag=True)
            assert get_feature_flag("string_flag") == "test"

            # JSON
            data = {"key": "value", "number": 123}
            set_feature_flag("json_flag", data, flag_type="json", is_system_flag=True)
            assert get_feature_flag("json_flag") == data

    def test_feature_flag_default_values(self, app):
        """Test feature flag default values"""
        with app.app_context():
            # System flag
            assert get_feature_flag("nonexistent", default=True) is True
            assert get_feature_flag("nonexistent", default=42) == 42

            # Organization flag
            org = Organization(name="Test", slug="test")
            db.session.add(org)
            db.session.commit()
            assert get_feature_flag("nonexistent", organization_id=org.id, default=False) is False
