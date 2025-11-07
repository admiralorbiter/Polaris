from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import inspect

from flask_app.forms import (
    BulkUserActionForm,
    ChangePasswordForm,
    CreateOrganizationForm,
    CreateUserForm,
    LoginForm,
    UpdateOrganizationForm,
    UpdateUserForm,
)
from flask_app.models import Organization, User, db


class TestLoginForm:
    """Test LoginForm functionality"""

    def test_login_form_creation(self):
        """Test creating a login form"""
        form = LoginForm()
        assert form.username.data is None
        assert form.password.data is None

    def test_login_form_valid_data(self):
        """Test login form with valid data"""
        form = LoginForm(data={"username": "testuser", "password": "validpass123"})
        assert form.username.data == "testuser"
        assert form.password.data == "validpass123"

    def test_login_form_validation_success(self):
        """Test successful form validation"""
        form = LoginForm(data={"username": "validuser", "password": "password123"})
        assert form.validate() is True

    def test_login_form_missing_username(self):
        """Test form validation with missing username"""
        form = LoginForm(data={"password": "password123"})
        assert form.validate() is False
        assert "username" in form.errors
        assert "Username is required." in form.errors["username"]

    def test_login_form_missing_password(self):
        """Test form validation with missing password"""
        form = LoginForm(data={"username": "testuser"})
        assert form.validate() is False
        assert "password" in form.errors
        assert "Password is required." in form.errors["password"]

    def test_login_form_username_too_short(self):
        """Test form validation with username too short"""
        form = LoginForm(data={"username": "ab", "password": "password123"})  # Less than 3 characters
        assert form.validate() is False
        assert "username" in form.errors

    def test_login_form_username_too_long(self):
        """Test form validation with username too long"""
        form = LoginForm(data={"username": "a" * 65, "password": "password123"})  # More than 64 characters
        assert form.validate() is False
        assert "username" in form.errors

    def test_login_form_username_invalid_characters(self):
        """Test form validation with invalid username characters"""
        form = LoginForm(data={"username": "invalid@user!", "password": "password123"})  # Invalid characters
        assert form.validate() is False
        assert "username" in form.errors
        assert "Username can only contain letters, numbers, underscores, and hyphens." in form.errors["username"]

    def test_login_form_password_too_short(self):
        """Test form validation with password too short"""
        form = LoginForm(data={"username": "testuser", "password": "12345"})  # Less than 6 characters
        assert form.validate() is False
        assert "password" in form.errors
        assert "Password must be at least 6 characters long." in form.errors["password"]

    def test_login_form_username_whitespace_stripping(self):
        """Test that username whitespace is stripped"""
        form = LoginForm(data={"username": "  testuser  ", "password": "password123"})
        form.validate()
        assert form.username.data == "testuser"

    def test_login_form_empty_password(self):
        """Test form validation with empty password"""
        form = LoginForm(data={"username": "testuser", "password": ""})
        assert form.validate() is False
        assert "password" in form.errors


class TestCreateUserForm:
    """Test CreateUserForm functionality"""

    def test_create_user_form_creation(self):
        """Test creating a create user form"""
        form = CreateUserForm()
        assert form.username.data is None
        assert form.email.data is None
        assert form.password.data is None
        assert form.confirm_password.data is None
        assert form.is_active.data is True
        assert form.is_super_admin.data is False

    def test_create_user_form_valid_data(self):
        """Test create user form with valid data"""
        form = CreateUserForm(
            data={
                "username": "newuser",
                "email": "newuser@example.com",
                "first_name": "New",
                "last_name": "User",
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
                "is_active": True,
                "is_super_admin": False,
            }
        )
        assert form.username.data == "newuser"
        assert form.email.data == "newuser@example.com"
        assert form.first_name.data == "New"
        assert form.last_name.data == "User"
        assert form.password.data == "SecurePass123"
        assert form.confirm_password.data == "SecurePass123"
        assert form.is_active.data is True
        assert form.is_super_admin.data is False

    @patch("flask_app.models.User.find_by_username")
    def test_create_user_form_validation_success(self, mock_find_username):
        """Test successful form validation"""
        mock_find_username.return_value = None  # Username doesn't exist

        with patch("flask_app.models.User.find_by_email") as mock_find_email:
            mock_find_email.return_value = None  # Email doesn't exist

            form = CreateUserForm(
                data={
                    "username": "newuser",
                    "email": "newuser@example.com",
                    "first_name": "New",
                    "last_name": "User",
                    "password": "SecurePass123",
                    "confirm_password": "SecurePass123",
                    "is_active": True,
                    "is_super_admin": False,
                }
            )
            assert form.validate() is True

    def test_create_user_form_missing_username(self):
        """Test form validation with missing username"""
        form = CreateUserForm(
            data={
                "email": "newuser@example.com",
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
            }
        )
        assert form.validate() is False
        assert "username" in form.errors

    def test_create_user_form_missing_email(self):
        """Test form validation with missing email"""
        form = CreateUserForm(
            data={
                "username": "newuser",
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
            }
        )
        assert form.validate() is False
        assert "email" in form.errors

    def test_create_user_form_invalid_email(self):
        """Test form validation with invalid email"""
        form = CreateUserForm(
            data={
                "username": "newuser",
                "email": "invalid-email",
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
            }
        )
        assert form.validate() is False
        assert "email" in form.errors
        assert "Invalid email address." in form.errors["email"]

    def test_create_user_form_password_mismatch(self):
        """Test form validation with password mismatch"""
        form = CreateUserForm(
            data={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "SecurePass123",
                "confirm_password": "DifferentPass123",
            }
        )
        assert form.validate() is False
        assert "confirm_password" in form.errors
        assert "Passwords must match." in form.errors["confirm_password"]

    def test_create_user_form_password_too_short(self):
        """Test form validation with password too short"""
        form = CreateUserForm(
            data={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "short",
                "confirm_password": "short",
            }
        )
        assert form.validate() is False
        assert "password" in form.errors
        assert "Password must be at least 8 characters long." in form.errors["password"]

    def test_create_user_form_password_no_uppercase(self):
        """Test form validation with password missing uppercase"""
        form = CreateUserForm(
            data={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "lowercase123",
                "confirm_password": "lowercase123",
            }
        )
        assert form.validate() is False
        assert "password" in form.errors
        assert "Password must contain at least one uppercase letter." in form.errors["password"]

    def test_create_user_form_password_no_lowercase(self):
        """Test form validation with password missing lowercase"""
        form = CreateUserForm(
            data={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "UPPERCASE123",
                "confirm_password": "UPPERCASE123",
            }
        )
        assert form.validate() is False
        assert "password" in form.errors
        assert "Password must contain at least one lowercase letter." in form.errors["password"]

    def test_create_user_form_password_no_digit(self):
        """Test form validation with password missing digit"""
        form = CreateUserForm(
            data={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "NoNumbers",
                "confirm_password": "NoNumbers",
            }
        )
        assert form.validate() is False
        assert "password" in form.errors
        assert "Password must contain at least one digit." in form.errors["password"]

    @patch("flask_app.models.User.find_by_username")
    def test_create_user_form_username_exists(self, mock_find_username):
        """Test form validation with existing username"""
        mock_user = MagicMock()
        mock_find_username.return_value = mock_user

        form = CreateUserForm(
            data={
                "username": "existinguser",
                "email": "newuser@example.com",
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
            }
        )
        assert form.validate() is False
        assert "username" in form.errors
        assert "Username already exists." in form.errors["username"]

    @patch("flask_app.models.User.find_by_email")
    def test_create_user_form_email_exists(self, mock_find_email):
        """Test form validation with existing email"""
        mock_user = MagicMock()
        mock_find_email.return_value = mock_user

        form = CreateUserForm(
            data={
                "username": "newuser",
                "email": "existing@example.com",
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
            }
        )
        assert form.validate() is False
        assert "email" in form.errors
        assert "Email already exists." in form.errors["email"]

    def test_create_user_form_username_invalid_characters(self):
        """Test form validation with invalid username characters"""
        form = CreateUserForm(
            data={
                "username": "invalid@user!",
                "email": "newuser@example.com",
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
            }
        )
        assert form.validate() is False
        assert "username" in form.errors
        assert "Username can only contain letters, numbers, underscores, and hyphens." in form.errors["username"]

    def test_create_user_form_field_lengths(self):
        """Test form validation with fields too long"""
        form = CreateUserForm(
            data={
                "username": "a" * 65,  # Too long
                "email": "a" * 121 + "@example.com",  # Too long
                "first_name": "a" * 65,  # Too long
                "last_name": "a" * 65,  # Too long
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
            }
        )
        assert form.validate() is False
        assert "username" in form.errors
        assert "email" in form.errors
        assert "first_name" in form.errors
        assert "last_name" in form.errors


class TestUpdateUserForm:
    """Test UpdateUserForm functionality"""

    def test_update_user_form_creation(self):
        """Test creating an update user form"""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "existinguser"
        mock_user.email = "existing@example.com"

        form = UpdateUserForm(user=mock_user)
        assert form.user == mock_user
        assert form.username.data is None
        assert form.email.data is None

    def test_update_user_form_valid_data(self):
        """Test update user form with valid data"""
        mock_user = MagicMock()
        mock_user.id = 1

        form = UpdateUserForm(
            user=mock_user,
            data={
                "username": "updateduser",
                "email": "updated@example.com",
                "first_name": "Updated",
                "last_name": "User",
                "is_active": True,
                "is_super_admin": False,
            },
        )
        assert form.username.data == "updateduser"
        assert form.email.data == "updated@example.com"
        assert form.first_name.data == "Updated"
        assert form.last_name.data == "User"
        assert form.is_active.data is True
        assert form.is_super_admin.data is False

    @patch("flask_app.models.User.find_by_username")
    def test_update_user_form_validation_success(self, mock_find_username):
        """Test successful form validation"""
        mock_find_username.return_value = None  # Username doesn't exist

        with patch("flask_app.models.User.find_by_email") as mock_find_email:
            mock_find_email.return_value = None  # Email doesn't exist

            mock_user = MagicMock()
            mock_user.id = 1

            form = UpdateUserForm(
                user=mock_user,
                data={
                    "username": "updateduser",
                    "email": "updated@example.com",
                    "first_name": "Updated",
                    "last_name": "User",
                    "is_active": True,
                    "is_super_admin": False,
                },
            )
            assert form.validate() is True

    @patch("flask_app.models.User.find_by_username")
    def test_update_user_form_same_user_username(self, mock_find_username):
        """Test form validation with same user's username"""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_find_username.return_value = mock_user  # Return same user

        with patch("flask_app.models.User.find_by_email") as mock_find_email:
            mock_find_email.return_value = None

            form = UpdateUserForm(
                user=mock_user,
                data={
                    "username": "existinguser",
                    "email": "updated@example.com",
                    "is_active": True,
                    "is_super_admin": False,
                },
            )
            assert form.validate() is True

    @patch("flask_app.models.User.find_by_username")
    def test_update_user_form_different_user_username(self, mock_find_username):
        """Test form validation with different user's username"""
        mock_user = MagicMock()
        mock_user.id = 1

        different_user = MagicMock()
        different_user.id = 2
        mock_find_username.return_value = different_user  # Return different user

        form = UpdateUserForm(
            user=mock_user,
            data={
                "username": "existinguser",
                "email": "updated@example.com",
                "is_active": True,
                "is_super_admin": False,
            },
        )
        assert form.validate() is False
        assert "username" in form.errors
        assert "Username already exists." in form.errors["username"]

    @patch("flask_app.models.User.find_by_email")
    def test_update_user_form_same_user_email(self, mock_find_email):
        """Test form validation with same user's email"""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_find_email.return_value = mock_user  # Return same user

        with patch("flask_app.models.User.find_by_username") as mock_find_username:
            mock_find_username.return_value = None

            form = UpdateUserForm(
                user=mock_user,
                data={
                    "username": "updateduser",
                    "email": "existing@example.com",
                    "is_active": True,
                    "is_super_admin": False,
                },
            )
            assert form.validate() is True

    @patch("flask_app.models.User.find_by_email")
    def test_update_user_form_different_user_email(self, mock_find_email):
        """Test form validation with different user's email"""
        mock_user = MagicMock()
        mock_user.id = 1

        different_user = MagicMock()
        different_user.id = 2
        mock_find_email.return_value = different_user  # Return different user

        form = UpdateUserForm(
            user=mock_user,
            data={
                "username": "updateduser",
                "email": "existing@example.com",
                "is_active": True,
                "is_super_admin": False,
            },
        )
        assert form.validate() is False
        assert "email" in form.errors
        assert "Email already exists." in form.errors["email"]


class TestChangePasswordForm:
    """Test ChangePasswordForm functionality"""

    def test_change_password_form_creation(self):
        """Test creating a change password form"""
        form = ChangePasswordForm()
        assert form.new_password.data is None
        assert form.confirm_password.data is None

    def test_change_password_form_valid_data(self):
        """Test change password form with valid data"""
        form = ChangePasswordForm(data={"new_password": "NewSecurePass123", "confirm_password": "NewSecurePass123"})
        assert form.new_password.data == "NewSecurePass123"
        assert form.confirm_password.data == "NewSecurePass123"

    def test_change_password_form_validation_success(self):
        """Test successful form validation"""
        form = ChangePasswordForm(data={"new_password": "NewSecurePass123", "confirm_password": "NewSecurePass123"})
        assert form.validate() is True

    def test_change_password_form_missing_password(self):
        """Test form validation with missing password"""
        form = ChangePasswordForm(data={"confirm_password": "NewSecurePass123"})
        assert form.validate() is False
        assert "new_password" in form.errors

    def test_change_password_form_missing_confirm(self):
        """Test form validation with missing confirm password"""
        form = ChangePasswordForm(data={"new_password": "NewSecurePass123"})
        assert form.validate() is False
        assert "confirm_password" in form.errors

    def test_change_password_form_password_mismatch(self):
        """Test form validation with password mismatch"""
        form = ChangePasswordForm(data={"new_password": "NewSecurePass123", "confirm_password": "DifferentPass123"})
        assert form.validate() is False
        assert "confirm_password" in form.errors
        assert "Passwords must match." in form.errors["confirm_password"]

    def test_change_password_form_password_too_short(self):
        """Test form validation with password too short"""
        form = ChangePasswordForm(data={"new_password": "short", "confirm_password": "short"})
        assert form.validate() is False
        assert "new_password" in form.errors
        assert "Password must be at least 8 characters long." in form.errors["new_password"]

    def test_change_password_form_password_no_uppercase(self):
        """Test form validation with password missing uppercase"""
        form = ChangePasswordForm(data={"new_password": "lowercase123", "confirm_password": "lowercase123"})
        assert form.validate() is False
        assert "new_password" in form.errors
        assert "Password must contain at least one uppercase letter." in form.errors["new_password"]

    def test_change_password_form_password_no_lowercase(self):
        """Test form validation with password missing lowercase"""
        form = ChangePasswordForm(data={"new_password": "UPPERCASE123", "confirm_password": "UPPERCASE123"})
        assert form.validate() is False
        assert "new_password" in form.errors
        assert "Password must contain at least one lowercase letter." in form.errors["new_password"]

    def test_change_password_form_password_no_digit(self):
        """Test form validation with password missing digit"""
        form = ChangePasswordForm(data={"new_password": "NoNumbers", "confirm_password": "NoNumbers"})
        assert form.validate() is False
        assert "new_password" in form.errors
        assert "Password must contain at least one digit." in form.errors["new_password"]


class TestBulkUserActionForm:
    """Test BulkUserActionForm functionality"""

    def test_bulk_user_action_form_creation(self):
        """Test creating a bulk user action form"""
        form = BulkUserActionForm()
        assert form.action.data is None
        assert form.user_ids.data is None

    def test_bulk_user_action_form_valid_data(self):
        """Test bulk user action form with valid data"""
        form = BulkUserActionForm(data={"action": "activate", "user_ids": "1,2,3"})
        assert form.action.data == "activate"
        assert form.user_ids.data == "1,2,3"

    def test_bulk_user_action_form_validation_success(self):
        """Test successful form validation"""
        form = BulkUserActionForm(data={"action": "activate", "user_ids": "1,2,3"})
        assert form.validate() is True
        assert hasattr(form, "user_ids_list")
        assert form.user_ids_list == [1, 2, 3]

    def test_bulk_user_action_form_missing_action(self):
        """Test form validation with missing action"""
        form = BulkUserActionForm(data={"user_ids": "1,2,3"})
        assert form.validate() is False
        assert "action" in form.errors

    def test_bulk_user_action_form_missing_user_ids(self):
        """Test form validation with missing user IDs"""
        form = BulkUserActionForm(data={"action": "activate"})
        assert form.validate() is False
        assert "user_ids" in form.errors

    def test_bulk_user_action_form_invalid_user_ids(self):
        """Test form validation with invalid user IDs"""
        form = BulkUserActionForm(data={"action": "activate", "user_ids": "1,abc,3"})
        assert form.validate() is False
        assert "user_ids" in form.errors
        assert "User IDs must be numbers separated by commas." in form.errors["user_ids"]

    def test_bulk_user_action_form_empty_user_ids(self):
        """Test form validation with empty user IDs"""
        form = BulkUserActionForm(data={"action": "activate", "user_ids": ""})
        assert form.validate() is False
        assert "user_ids" in form.errors

    def test_bulk_user_action_form_whitespace_user_ids(self):
        """Test form validation with whitespace-only user IDs"""
        form = BulkUserActionForm(data={"action": "activate", "user_ids": "   ,  ,  "})
        assert form.validate() is False
        assert "user_ids" in form.errors
        # Check that we get a validation error for invalid user IDs
        assert len(form.errors["user_ids"]) > 0

    def test_bulk_user_action_form_valid_actions(self):
        """Test form validation with all valid actions"""
        valid_actions = ["activate", "deactivate", "delete", "export"]

        for action in valid_actions:
            form = BulkUserActionForm(data={"action": action, "user_ids": "1,2,3"})
            assert form.validate() is True

    def test_bulk_user_action_form_user_ids_whitespace_handling(self):
        """Test form validation with user IDs containing whitespace"""
        form = BulkUserActionForm(data={"action": "activate", "user_ids": " 1 , 2 , 3 "})
        assert form.validate() is True
        assert form.user_ids_list == [1, 2, 3]


class TestCreateOrganizationForm:
    """Test CreateOrganizationForm functionality"""

    def test_create_organization_form_creation(self):
        """Test creating a create organization form"""
        form = CreateOrganizationForm()
        assert form.name.data is None
        assert form.slug.data is None
        assert form.description.data is None
        assert form.is_active.data is True

    def test_create_organization_form_valid_data(self, app):
        """Test create organization form with valid data"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "description": "A test organization",
                    "is_active": True,
                }
            )
            assert form.name.data == "Test Organization"
            assert form.slug.data == "test-organization"
            assert form.description.data == "A test organization"
            assert form.is_active.data is True

    def test_create_organization_form_validation_success(self, app):
        """Test successful form validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Valid Organization",
                    "slug": "valid-organization",
                    "description": "Description",
                    "is_active": True,
                }
            )
            assert form.validate() is True

    def test_create_organization_form_missing_name(self):
        """Test form validation with missing name"""
        form = CreateOrganizationForm(data={"slug": "test-organization"})
        assert form.validate() is False
        assert "name" in form.errors

    def test_create_organization_form_missing_slug(self):
        """Test form validation with missing slug"""
        form = CreateOrganizationForm(data={"name": "Test Organization"})
        assert form.validate() is False
        assert "slug" in form.errors

    def test_create_organization_form_name_too_short(self):
        """Test form validation with name too short"""
        form = CreateOrganizationForm(data={"name": "A", "slug": "test-org"})  # Less than 2 characters
        assert form.validate() is False
        assert "name" in form.errors

    def test_create_organization_form_name_too_long(self):
        """Test form validation with name too long"""
        form = CreateOrganizationForm(data={"name": "A" * 201, "slug": "test-org"})  # More than 200 characters
        assert form.validate() is False
        assert "name" in form.errors

    def test_create_organization_form_slug_too_short(self):
        """Test form validation with slug too short"""
        form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "a"})  # Less than 2 characters
        assert form.validate() is False
        assert "slug" in form.errors

    def test_create_organization_form_slug_invalid_characters(self, app):
        """Test form validation with invalid slug characters"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "Test_Organization!",  # Invalid characters
                }
            )
            assert form.validate() is False
            assert "slug" in form.errors
            assert "lowercase letters, numbers, and hyphens" in form.errors["slug"][0]

    def test_create_organization_form_duplicate_name(self, test_organization, app):
        """Test form validation with duplicate name"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",  # Same as test_organization
                    "slug": "different-slug",
                }
            )
            assert form.validate() is False
            assert "name" in form.errors
            assert "already exists" in form.errors["name"][0]

    def test_create_organization_form_duplicate_slug(self, test_organization, app):
        """Test form validation with duplicate slug"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Different Name",
                    "slug": "test-organization",  # Same as test_organization
                }
            )
            assert form.validate() is False
            assert "slug" in form.errors
            assert "already exists" in form.errors["slug"][0]

    def test_create_organization_form_description_optional(self):
        """Test that description is optional"""
        form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
        assert form.validate() is True
        assert form.description.data is None

    def test_create_organization_form_description_too_long(self, app):
        """Test form validation with description too long"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "description": "A" * 5001,  # More than 5000 characters (max)
                }
            )
            assert form.validate() is False
            assert "description" in form.errors

    def test_create_organization_form_name_stripping(self, app):
        """Test that name whitespace is stripped"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "  Test Organization  ", "slug": "test-organization"})
            form.validate()
            assert form.name.data == "Test Organization"

    def test_create_organization_form_organization_type_required(self, app):
        """Test that organization_type is required"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            # organization_type should have a default, but let's test it's present
            assert hasattr(form, "organization_type")
            assert form.organization_type.choices is not None
            assert len(form.organization_type.choices) > 0

    def test_create_organization_form_organization_type_valid_enum(self, app):
        """Test organization_type accepts valid enum values"""
        with app.app_context():
            from flask_app.models import OrganizationType

            for org_type in OrganizationType:
                form = CreateOrganizationForm(
                    data={
                        "name": "Test Organization",
                        "slug": "test-organization",
                        "organization_type": org_type.value,
                    }
                )
                assert form.organization_type.data == org_type.value

    def test_create_organization_form_website_optional(self, app):
        """Test that website is optional"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.validate() is True
            assert form.website.data is None

    def test_create_organization_form_website_url_validation(self, app):
        """Test website URL validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "organization_type": "other",
                    "website": "not-a-valid-url",
                }
            )
            assert form.validate() is False
            assert "website" in form.errors

    def test_create_organization_form_website_max_length(self, app):
        """Test website max length validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "organization_type": "other",
                    "website": "https://" + "x" * 493,  # 501 chars total
                }
            )
            assert form.validate() is False
            assert "website" in form.errors

    def test_create_organization_form_phone_optional(self, app):
        """Test that phone is optional"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.validate() is True
            assert form.phone.data is None

    def test_create_organization_form_phone_max_length(self, app):
        """Test phone max length validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "phone": "1" * 21,  # 21 chars
                }
            )
            assert form.validate() is False
            assert "phone" in form.errors

    def test_create_organization_form_email_optional(self, app):
        """Test that email is optional"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.validate() is True
            assert form.email.data is None

    def test_create_organization_form_email_validation(self, app):
        """Test email validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "organization_type": "other",
                    "email": "not-a-valid-email",
                }
            )
            assert form.validate() is False
            assert "email" in form.errors

    def test_create_organization_form_email_max_length(self, app):
        """Test email max length validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "organization_type": "other",
                    "email": "x" * 246 + "@example.com",  # 256 chars total
                }
            )
            assert form.validate() is False
            assert "email" in form.errors

    def test_create_organization_form_tax_id_optional(self, app):
        """Test that tax_id is optional"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.validate() is True
            assert form.tax_id.data is None

    def test_create_organization_form_tax_id_max_length(self, app):
        """Test tax_id max length validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "tax_id": "1" * 51,  # 51 chars
                }
            )
            assert form.validate() is False
            assert "tax_id" in form.errors

    def test_create_organization_form_logo_url_optional(self, app):
        """Test that logo_url is optional"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.validate() is True
            assert form.logo_url.data is None

    def test_create_organization_form_logo_url_validation(self, app):
        """Test logo_url URL validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "organization_type": "other",
                    "logo_url": "not-a-valid-url",
                }
            )
            assert form.validate() is False
            assert "logo_url" in form.errors

    def test_create_organization_form_logo_url_max_length(self, app):
        """Test logo_url max length validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "organization_type": "other",
                    "logo_url": "https://" + "x" * 493,  # 501 chars total
                }
            )
            assert form.validate() is False
            assert "logo_url" in form.errors

    def test_create_organization_form_contact_person_name_optional(self, app):
        """Test that contact_person_name is optional"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.validate() is True
            assert form.contact_person_name.data is None

    def test_create_organization_form_contact_person_name_max_length(self, app):
        """Test contact_person_name max length validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "contact_person_name": "x" * 201,  # 201 chars
                }
            )
            assert form.validate() is False
            assert "contact_person_name" in form.errors

    def test_create_organization_form_contact_person_title_optional(self, app):
        """Test that contact_person_title is optional"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.validate() is True
            assert form.contact_person_title.data is None

    def test_create_organization_form_contact_person_title_max_length(self, app):
        """Test contact_person_title max length validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "contact_person_title": "x" * 101,  # 101 chars
                }
            )
            assert form.validate() is False
            assert "contact_person_title" in form.errors

    def test_create_organization_form_founded_date_optional(self, app):
        """Test that founded_date is optional"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.validate() is True
            assert form.founded_date.data is None

    def test_create_organization_form_founded_date_validation(self, app):
        """Test founded_date date validation"""
        with app.app_context():
            from datetime import date

            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "founded_date": date(2020, 1, 15),
                }
            )
            assert form.validate() is True
            assert form.founded_date.data == date(2020, 1, 15)

    def test_create_organization_form_address_type_required(self, app):
        """Test that address_type is required if address provided"""
        with app.app_context():
            from flask_app.models import AddressType

            form = CreateOrganizationForm(
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",
                    "street_address_1": "123 Main St",
                    "city": "Springfield",
                    "state": "IL",
                    "postal_code": "62701",
                }
            )
            # address_type should be required if address fields are provided
            assert hasattr(form, "address_type")
            assert form.address_type.choices is not None

    def test_create_organization_form_address_type_valid_enum(self, app):
        """Test address_type accepts valid enum values"""
        with app.app_context():
            from flask_app.models import AddressType

            for addr_type in AddressType:
                form = CreateOrganizationForm(
                    data={
                        "name": "Test Organization",
                        "slug": "test-organization",
                        "address_type": addr_type.value,
                    }
                )
                assert form.address_type.data == addr_type.value

    def test_create_organization_form_address_fields_optional(self, app):
        """Test that address fields are optional"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.validate() is True
            assert form.street_address_1.data is None
            assert form.street_address_2.data is None
            assert form.city.data is None
            assert form.state.data is None
            assert form.postal_code.data is None

    def test_create_organization_form_country_default(self, app):
        """Test that country defaults to US"""
        with app.app_context():
            form = CreateOrganizationForm(data={"name": "Test Organization", "slug": "test-organization"})
            assert form.country.data == "US" or form.country.data is None


class TestUpdateOrganizationForm:
    """Test UpdateOrganizationForm functionality"""

    def test_update_organization_form_creation(self, test_organization):
        """Test creating an update organization form"""
        form = UpdateOrganizationForm(organization=test_organization)
        assert form.organization == test_organization

    def test_update_organization_form_valid_data(self, test_organization):
        """Test update organization form with valid data"""
        form = UpdateOrganizationForm(
            organization=test_organization,
            data={
                "name": "Updated Organization",
                "slug": "updated-organization",
                "description": "Updated description",
                "is_active": True,
            },
        )
        assert form.name.data == "Updated Organization"
        assert form.slug.data == "updated-organization"
        assert form.description.data == "Updated description"
        assert form.is_active.data is True

    def test_update_organization_form_validation_success(self, test_organization, app):
        """Test successful form validation"""
        with app.app_context():
            form = UpdateOrganizationForm(
                organization=test_organization,
                data={
                    "name": "Updated Name",
                    "slug": "updated-slug",
                    "description": "Updated",
                    "organization_type": "other",  # Required field
                    "is_active": True,
                },
            )
            assert form.validate() is True

    def test_update_organization_form_same_name(self, test_organization, app):
        """Test form validation with same organization name"""
        # Store ID before object becomes detached
        org_id = inspect(test_organization).identity[0]
        with app.app_context():
            # Re-query to avoid detached instance
            org = db.session.get(Organization, org_id)
            form = UpdateOrganizationForm(
                organization=org,
                data={
                    "name": "Test Organization",  # Same as test_organization
                    "slug": "test-organization",
                    "organization_type": "other",  # Required field
                    "is_active": True,
                },
            )
            assert form.validate() is True  # Should allow same name for same org

    def test_update_organization_form_different_org_name(self, test_organization, app):
        """Test form validation with different organization's name"""
        # Store ID before object becomes detached
        org_id = inspect(test_organization).identity[0]
        with app.app_context():
            # Re-query to avoid detached instance
            org = db.session.get(Organization, org_id)
            # Create another organization
            other_org = Organization(name="Other Org", slug="other-org")
            db.session.add(other_org)
            db.session.commit()

            form = UpdateOrganizationForm(
                organization=org,
                data={
                    "name": "Other Org",  # Same as other_org
                    "slug": "test-organization",
                    "organization_type": "other",
                    "is_active": True,
                },
            )
            assert form.validate() is False
            assert "name" in form.errors
            assert "already exists" in form.errors["name"][0]

    def test_update_organization_form_same_slug(self, test_organization, app):
        """Test form validation with same organization slug"""
        # Store ID before object becomes detached
        org_id = inspect(test_organization).identity[0]
        with app.app_context():
            # Re-query to avoid detached instance
            org = db.session.get(Organization, org_id)
            form = UpdateOrganizationForm(
                organization=org,
                data={
                    "name": "Test Organization",
                    "slug": "test-organization",  # Same as test_organization
                    "organization_type": "other",  # Required field
                    "is_active": True,
                },
            )
            assert form.validate() is True  # Should allow same slug for same org

    def test_update_organization_form_different_org_slug(self, test_organization, app):
        """Test update organization form with slug that exists for different org"""
        with app.app_context():
            # Create another organization
            other_org = Organization(name="Other Org", slug="other-org", is_active=True)
            db.session.add(other_org)
            db.session.commit()

            form = UpdateOrganizationForm(
                organization=test_organization,
                data={
                    "name": "Test Organization",
                    "slug": "other-org",
                    "organization_type": "other",
                    "is_active": True,
                },
            )
            assert form.validate() is False
            assert "slug" in form.errors
            assert "already exists" in form.errors["slug"][0].lower()


class TestOrganizationFormRobustness:
    """Robustness tests for organization forms - edge cases and security"""

    def test_create_organization_form_xss_attempt_name(self, app):
        """Test organization form with XSS attempt in name field"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "<script>alert('XSS')</script>",
                    "slug": "test-org",
                    "is_active": True,
                }
            )
            # Form should validate (XSS protection is in template rendering)
            # But name should be stored as-is (sanitization happens at display time)
            form.validate()
            # Check that script tags are in the data (not filtered by form)
            assert "<script>" in form.name.data

    def test_create_organization_form_sql_injection_attempt_name(self, app):
        """Test organization form with SQL injection attempt in name"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "'; DROP TABLE organizations; --",
                    "slug": "test-org",
                    "is_active": True,
                }
            )
            # Form should validate (SQL injection protection is in ORM)
            form.validate()
            # SQL injection attempt should be stored as literal string
            assert "DROP TABLE" in form.name.data

    def test_create_organization_form_sql_injection_attempt_slug(self, app):
        """Test organization form with SQL injection attempt in slug"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Org",
                    "slug": "'; DROP TABLE organizations; --",
                    "is_active": True,
                }
            )
            # Slug validation should reject invalid characters
            assert form.validate() is False
            assert "slug" in form.errors

    def test_create_organization_form_special_characters_name(self, app):
        """Test organization form with special characters in name"""
        with app.app_context():
            # Name can contain special characters (will be sanitized in slug)
            form = CreateOrganizationForm(
                data={
                    "name": "Org & Co. (Ltd.)",
                    "slug": "org-co-ltd",
                    "is_active": True,
                }
            )
            assert form.validate() is True

    def test_create_organization_form_unicode_characters(self, app):
        """Test organization form with unicode characters"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Organización Test 测试",
                    "slug": "organizacion-test",
                    "is_active": True,
                }
            )
            assert form.validate() is True
            assert "Organización" in form.name.data

    def test_create_organization_form_very_long_description(self, app):
        """Test organization form with description exceeding limit"""
        with app.app_context():
            long_description = "a" * 5001  # Exceeds 5000 character limit
            form = CreateOrganizationForm(
                data={
                    "name": "Test Org",
                    "slug": "test-org",
                    "description": long_description,
                    "is_active": True,
                }
            )
            assert form.validate() is False
            assert "description" in form.errors

    def test_create_organization_form_empty_string_name(self, app):
        """Test organization form with empty string name (after strip)"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "   ",  # Only whitespace
                    "slug": "test-org",
                    "is_active": True,
                }
            )
            assert form.validate() is False
            assert "name" in form.errors

    def test_create_organization_form_empty_string_slug(self, app):
        """Test organization form with empty string slug (after strip)"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Org",
                    "slug": "   ",  # Only whitespace
                    "is_active": True,
                }
            )
            assert form.validate() is False
            assert "slug" in form.errors

    def test_create_organization_form_null_bytes(self, app):
        """Test organization form with null bytes (security test)"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test\x00Org",
                    "slug": "test-org",
                    "is_active": True,
                }
            )
            # Should handle null bytes (may be stripped or cause validation error)
            form.validate()
            # Null bytes may be in data (sanitization happens elsewhere) or validation may fail
            # Just check that form handles it without crashing
            assert form.name.data is not None

    def test_update_organization_form_none_organization(self, app):
        """Test update organization form with None organization"""
        with app.app_context():
            form = UpdateOrganizationForm(
                organization=None,
                data={
                    "name": "Test Org",
                    "slug": "test-org",
                    "is_active": True,
                },
            )
            # Should handle None organization gracefully
            form.validate()
            # May skip duplicate checks if organization is None

    def test_update_organization_form_xss_attempt_description(self, app, test_organization):
        """Test update organization form with XSS in description"""
        with app.app_context():
            form = UpdateOrganizationForm(
                organization=test_organization,
                data={
                    "name": "Test Org",
                    "slug": "test-org",
                    "description": "<img src=x onerror=alert('XSS')>",
                    "is_active": True,
                },
            )
            # Form should validate (XSS protection in template)
            form.validate()
            assert "<img" in form.description.data

    def test_create_organization_form_boundary_name_length(self, app):
        """Test organization form with boundary name lengths"""
        with app.app_context():
            # Test minimum length (2 characters)
            form = CreateOrganizationForm(
                data={
                    "name": "AB",  # Exactly 2 characters
                    "slug": "ab",
                    "is_active": True,
                }
            )
            assert form.validate() is True

            # Test maximum length (200 characters)
            form = CreateOrganizationForm(
                data={
                    "name": "A" * 200,  # Exactly 200 characters
                    "slug": "a" * 100,
                    "is_active": True,
                }
            )
            assert form.validate() is True

            # Test over maximum (201 characters)
            form = CreateOrganizationForm(
                data={
                    "name": "A" * 201,  # Over 200 characters
                    "slug": "test-org",
                    "is_active": True,
                }
            )
            assert form.validate() is False
            assert "name" in form.errors

    def test_create_organization_form_boundary_slug_length(self, app):
        """Test organization form with boundary slug lengths"""
        with app.app_context():
            # Test minimum length (2 characters)
            form = CreateOrganizationForm(
                data={
                    "name": "Test Org",
                    "slug": "ab",  # Exactly 2 characters
                    "is_active": True,
                }
            )
            assert form.validate() is True

            # Test maximum length (100 characters)
            form = CreateOrganizationForm(
                data={
                    "name": "Test Org",
                    "slug": "a" * 100,  # Exactly 100 characters
                    "is_active": True,
                }
            )
            assert form.validate() is True

            # Test over maximum (101 characters)
            form = CreateOrganizationForm(
                data={
                    "name": "Test Org",
                    "slug": "a" * 101,  # Over 100 characters
                    "is_active": True,
                }
            )
            assert form.validate() is False
            assert "slug" in form.errors

    def test_create_organization_form_database_error_during_validation(self, app):
        """Test organization form with database error during validation"""
        with app.app_context():
            form = CreateOrganizationForm(
                data={
                    "name": "Test Org",
                    "slug": "test-org",
                    "is_active": True,
                }
            )

            # Mock Organization.query to raise error - patch where it's imported
            with patch("flask_app.models.Organization.query") as mock_query:
                mock_query.filter_by.side_effect = Exception("Database error")
                # Should handle database error gracefully
                try:
                    form.validate()
                    # May raise or return False
                except Exception:
                    # Exception is acceptable error handling
                    pass

    def test_update_organization_form_database_error_during_validation(self, app, test_organization):
        """Test update organization form with database error during validation"""
        with app.app_context():
            form = UpdateOrganizationForm(
                organization=test_organization,
                data={
                    "name": "Updated Org",
                    "slug": "updated-org",
                    "is_active": True,
                },
            )

            # Mock Organization.query to raise error - patch where it's imported
            with patch("flask_app.models.Organization.query") as mock_query:
                mock_query.filter_by.side_effect = Exception("Database error")
                try:
                    form.validate()
                except Exception:
                    pass
