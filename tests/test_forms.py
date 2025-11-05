import pytest
from unittest.mock import patch, MagicMock
from flask_app.forms import LoginForm, CreateUserForm, UpdateUserForm, ChangePasswordForm, BulkUserActionForm
from flask_app.models import User


class TestLoginForm:
    """Test LoginForm functionality"""
    
    def test_login_form_creation(self):
        """Test creating a login form"""
        form = LoginForm()
        assert form.username.data is None
        assert form.password.data is None
    
    def test_login_form_valid_data(self):
        """Test login form with valid data"""
        form = LoginForm(data={
            'username': 'testuser',
            'password': 'validpass123'
        })
        assert form.username.data == 'testuser'
        assert form.password.data == 'validpass123'
    
    def test_login_form_validation_success(self):
        """Test successful form validation"""
        form = LoginForm(data={
            'username': 'validuser',
            'password': 'password123'
        })
        assert form.validate() is True
    
    def test_login_form_missing_username(self):
        """Test form validation with missing username"""
        form = LoginForm(data={
            'password': 'password123'
        })
        assert form.validate() is False
        assert 'username' in form.errors
        assert 'Username is required.' in form.errors['username']
    
    def test_login_form_missing_password(self):
        """Test form validation with missing password"""
        form = LoginForm(data={
            'username': 'testuser'
        })
        assert form.validate() is False
        assert 'password' in form.errors
        assert 'Password is required.' in form.errors['password']
    
    def test_login_form_username_too_short(self):
        """Test form validation with username too short"""
        form = LoginForm(data={
            'username': 'ab',  # Less than 3 characters
            'password': 'password123'
        })
        assert form.validate() is False
        assert 'username' in form.errors
    
    def test_login_form_username_too_long(self):
        """Test form validation with username too long"""
        form = LoginForm(data={
            'username': 'a' * 65,  # More than 64 characters
            'password': 'password123'
        })
        assert form.validate() is False
        assert 'username' in form.errors
    
    def test_login_form_username_invalid_characters(self):
        """Test form validation with invalid username characters"""
        form = LoginForm(data={
            'username': 'invalid@user!',  # Invalid characters
            'password': 'password123'
        })
        assert form.validate() is False
        assert 'username' in form.errors
        assert 'Username can only contain letters, numbers, underscores, and hyphens.' in form.errors['username']
    
    def test_login_form_password_too_short(self):
        """Test form validation with password too short"""
        form = LoginForm(data={
            'username': 'testuser',
            'password': '12345'  # Less than 6 characters
        })
        assert form.validate() is False
        assert 'password' in form.errors
        assert 'Password must be at least 6 characters long.' in form.errors['password']
    
    def test_login_form_username_whitespace_stripping(self):
        """Test that username whitespace is stripped"""
        form = LoginForm(data={
            'username': '  testuser  ',
            'password': 'password123'
        })
        form.validate()
        assert form.username.data == 'testuser'
    
    def test_login_form_empty_password(self):
        """Test form validation with empty password"""
        form = LoginForm(data={
            'username': 'testuser',
            'password': ''
        })
        assert form.validate() is False
        assert 'password' in form.errors


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
        assert form.is_admin.data is False
    
    def test_create_user_form_valid_data(self):
        """Test create user form with valid data"""
        form = CreateUserForm(data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'first_name': 'New',
            'last_name': 'User',
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123',
            'is_active': True,
            'is_admin': False
        })
        assert form.username.data == 'newuser'
        assert form.email.data == 'newuser@example.com'
        assert form.first_name.data == 'New'
        assert form.last_name.data == 'User'
        assert form.password.data == 'SecurePass123'
        assert form.confirm_password.data == 'SecurePass123'
        assert form.is_active.data is True
        assert form.is_admin.data is False
    
    @patch('flask_app.models.User.find_by_username')
    def test_create_user_form_validation_success(self, mock_find_username):
        """Test successful form validation"""
        mock_find_username.return_value = None  # Username doesn't exist
        
        with patch('flask_app.models.User.find_by_email') as mock_find_email:
            mock_find_email.return_value = None  # Email doesn't exist
            
            form = CreateUserForm(data={
                'username': 'newuser',
                'email': 'newuser@example.com',
                'first_name': 'New',
                'last_name': 'User',
                'password': 'SecurePass123',
                'confirm_password': 'SecurePass123',
                'is_active': True,
                'is_admin': False
            })
            assert form.validate() is True
    
    def test_create_user_form_missing_username(self):
        """Test form validation with missing username"""
        form = CreateUserForm(data={
            'email': 'newuser@example.com',
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123'
        })
        assert form.validate() is False
        assert 'username' in form.errors
    
    def test_create_user_form_missing_email(self):
        """Test form validation with missing email"""
        form = CreateUserForm(data={
            'username': 'newuser',
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123'
        })
        assert form.validate() is False
        assert 'email' in form.errors
    
    def test_create_user_form_invalid_email(self):
        """Test form validation with invalid email"""
        form = CreateUserForm(data={
            'username': 'newuser',
            'email': 'invalid-email',
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123'
        })
        assert form.validate() is False
        assert 'email' in form.errors
        assert 'Invalid email address.' in form.errors['email']
    
    def test_create_user_form_password_mismatch(self):
        """Test form validation with password mismatch"""
        form = CreateUserForm(data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'SecurePass123',
            'confirm_password': 'DifferentPass123'
        })
        assert form.validate() is False
        assert 'confirm_password' in form.errors
        assert 'Passwords must match.' in form.errors['confirm_password']
    
    def test_create_user_form_password_too_short(self):
        """Test form validation with password too short"""
        form = CreateUserForm(data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'short',
            'confirm_password': 'short'
        })
        assert form.validate() is False
        assert 'password' in form.errors
        assert 'Password must be at least 8 characters long.' in form.errors['password']
    
    def test_create_user_form_password_no_uppercase(self):
        """Test form validation with password missing uppercase"""
        form = CreateUserForm(data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'lowercase123',
            'confirm_password': 'lowercase123'
        })
        assert form.validate() is False
        assert 'password' in form.errors
        assert 'Password must contain at least one uppercase letter.' in form.errors['password']
    
    def test_create_user_form_password_no_lowercase(self):
        """Test form validation with password missing lowercase"""
        form = CreateUserForm(data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'UPPERCASE123',
            'confirm_password': 'UPPERCASE123'
        })
        assert form.validate() is False
        assert 'password' in form.errors
        assert 'Password must contain at least one lowercase letter.' in form.errors['password']
    
    def test_create_user_form_password_no_digit(self):
        """Test form validation with password missing digit"""
        form = CreateUserForm(data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'NoNumbers',
            'confirm_password': 'NoNumbers'
        })
        assert form.validate() is False
        assert 'password' in form.errors
        assert 'Password must contain at least one digit.' in form.errors['password']
    
    @patch('flask_app.models.User.find_by_username')
    def test_create_user_form_username_exists(self, mock_find_username):
        """Test form validation with existing username"""
        mock_user = MagicMock()
        mock_find_username.return_value = mock_user
        
        form = CreateUserForm(data={
            'username': 'existinguser',
            'email': 'newuser@example.com',
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123'
        })
        assert form.validate() is False
        assert 'username' in form.errors
        assert 'Username already exists.' in form.errors['username']
    
    @patch('flask_app.models.User.find_by_email')
    def test_create_user_form_email_exists(self, mock_find_email):
        """Test form validation with existing email"""
        mock_user = MagicMock()
        mock_find_email.return_value = mock_user
        
        form = CreateUserForm(data={
            'username': 'newuser',
            'email': 'existing@example.com',
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123'
        })
        assert form.validate() is False
        assert 'email' in form.errors
        assert 'Email already exists.' in form.errors['email']
    
    def test_create_user_form_username_invalid_characters(self):
        """Test form validation with invalid username characters"""
        form = CreateUserForm(data={
            'username': 'invalid@user!',
            'email': 'newuser@example.com',
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123'
        })
        assert form.validate() is False
        assert 'username' in form.errors
        assert 'Username can only contain letters, numbers, underscores, and hyphens.' in form.errors['username']
    
    def test_create_user_form_field_lengths(self):
        """Test form validation with fields too long"""
        form = CreateUserForm(data={
            'username': 'a' * 65,  # Too long
            'email': 'a' * 121 + '@example.com',  # Too long
            'first_name': 'a' * 65,  # Too long
            'last_name': 'a' * 65,  # Too long
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123'
        })
        assert form.validate() is False
        assert 'username' in form.errors
        assert 'email' in form.errors
        assert 'first_name' in form.errors
        assert 'last_name' in form.errors


class TestUpdateUserForm:
    """Test UpdateUserForm functionality"""
    
    def test_update_user_form_creation(self):
        """Test creating an update user form"""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = 'existinguser'
        mock_user.email = 'existing@example.com'
        
        form = UpdateUserForm(user=mock_user)
        assert form.user == mock_user
        assert form.username.data is None
        assert form.email.data is None
    
    def test_update_user_form_valid_data(self):
        """Test update user form with valid data"""
        mock_user = MagicMock()
        mock_user.id = 1
        
        form = UpdateUserForm(user=mock_user, data={
            'username': 'updateduser',
            'email': 'updated@example.com',
            'first_name': 'Updated',
            'last_name': 'User',
            'is_active': True,
            'is_admin': False
        })
        assert form.username.data == 'updateduser'
        assert form.email.data == 'updated@example.com'
        assert form.first_name.data == 'Updated'
        assert form.last_name.data == 'User'
        assert form.is_active.data is True
        assert form.is_admin.data is False
    
    @patch('flask_app.models.User.find_by_username')
    def test_update_user_form_validation_success(self, mock_find_username):
        """Test successful form validation"""
        mock_find_username.return_value = None  # Username doesn't exist
        
        with patch('flask_app.models.User.find_by_email') as mock_find_email:
            mock_find_email.return_value = None  # Email doesn't exist
            
            mock_user = MagicMock()
            mock_user.id = 1
            
            form = UpdateUserForm(user=mock_user, data={
                'username': 'updateduser',
                'email': 'updated@example.com',
                'first_name': 'Updated',
                'last_name': 'User',
                'is_active': True,
                'is_admin': False
            })
            assert form.validate() is True
    
    @patch('flask_app.models.User.find_by_username')
    def test_update_user_form_same_user_username(self, mock_find_username):
        """Test form validation with same user's username"""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_find_username.return_value = mock_user  # Return same user
        
        with patch('flask_app.models.User.find_by_email') as mock_find_email:
            mock_find_email.return_value = None
            
            form = UpdateUserForm(user=mock_user, data={
                'username': 'existinguser',
                'email': 'updated@example.com',
                'is_active': True,
                'is_admin': False
            })
            assert form.validate() is True
    
    @patch('flask_app.models.User.find_by_username')
    def test_update_user_form_different_user_username(self, mock_find_username):
        """Test form validation with different user's username"""
        mock_user = MagicMock()
        mock_user.id = 1
        
        different_user = MagicMock()
        different_user.id = 2
        mock_find_username.return_value = different_user  # Return different user
        
        form = UpdateUserForm(user=mock_user, data={
            'username': 'existinguser',
            'email': 'updated@example.com',
            'is_active': True,
            'is_admin': False
        })
        assert form.validate() is False
        assert 'username' in form.errors
        assert 'Username already exists.' in form.errors['username']
    
    @patch('flask_app.models.User.find_by_email')
    def test_update_user_form_same_user_email(self, mock_find_email):
        """Test form validation with same user's email"""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_find_email.return_value = mock_user  # Return same user
        
        with patch('flask_app.models.User.find_by_username') as mock_find_username:
            mock_find_username.return_value = None
            
            form = UpdateUserForm(user=mock_user, data={
                'username': 'updateduser',
                'email': 'existing@example.com',
                'is_active': True,
                'is_admin': False
            })
            assert form.validate() is True
    
    @patch('flask_app.models.User.find_by_email')
    def test_update_user_form_different_user_email(self, mock_find_email):
        """Test form validation with different user's email"""
        mock_user = MagicMock()
        mock_user.id = 1
        
        different_user = MagicMock()
        different_user.id = 2
        mock_find_email.return_value = different_user  # Return different user
        
        form = UpdateUserForm(user=mock_user, data={
            'username': 'updateduser',
            'email': 'existing@example.com',
            'is_active': True,
            'is_admin': False
        })
        assert form.validate() is False
        assert 'email' in form.errors
        assert 'Email already exists.' in form.errors['email']


class TestChangePasswordForm:
    """Test ChangePasswordForm functionality"""
    
    def test_change_password_form_creation(self):
        """Test creating a change password form"""
        form = ChangePasswordForm()
        assert form.new_password.data is None
        assert form.confirm_password.data is None
    
    def test_change_password_form_valid_data(self):
        """Test change password form with valid data"""
        form = ChangePasswordForm(data={
            'new_password': 'NewSecurePass123',
            'confirm_password': 'NewSecurePass123'
        })
        assert form.new_password.data == 'NewSecurePass123'
        assert form.confirm_password.data == 'NewSecurePass123'
    
    def test_change_password_form_validation_success(self):
        """Test successful form validation"""
        form = ChangePasswordForm(data={
            'new_password': 'NewSecurePass123',
            'confirm_password': 'NewSecurePass123'
        })
        assert form.validate() is True
    
    def test_change_password_form_missing_password(self):
        """Test form validation with missing password"""
        form = ChangePasswordForm(data={
            'confirm_password': 'NewSecurePass123'
        })
        assert form.validate() is False
        assert 'new_password' in form.errors
    
    def test_change_password_form_missing_confirm(self):
        """Test form validation with missing confirm password"""
        form = ChangePasswordForm(data={
            'new_password': 'NewSecurePass123'
        })
        assert form.validate() is False
        assert 'confirm_password' in form.errors
    
    def test_change_password_form_password_mismatch(self):
        """Test form validation with password mismatch"""
        form = ChangePasswordForm(data={
            'new_password': 'NewSecurePass123',
            'confirm_password': 'DifferentPass123'
        })
        assert form.validate() is False
        assert 'confirm_password' in form.errors
        assert 'Passwords must match.' in form.errors['confirm_password']
    
    def test_change_password_form_password_too_short(self):
        """Test form validation with password too short"""
        form = ChangePasswordForm(data={
            'new_password': 'short',
            'confirm_password': 'short'
        })
        assert form.validate() is False
        assert 'new_password' in form.errors
        assert 'Password must be at least 8 characters long.' in form.errors['new_password']
    
    def test_change_password_form_password_no_uppercase(self):
        """Test form validation with password missing uppercase"""
        form = ChangePasswordForm(data={
            'new_password': 'lowercase123',
            'confirm_password': 'lowercase123'
        })
        assert form.validate() is False
        assert 'new_password' in form.errors
        assert 'Password must contain at least one uppercase letter.' in form.errors['new_password']
    
    def test_change_password_form_password_no_lowercase(self):
        """Test form validation with password missing lowercase"""
        form = ChangePasswordForm(data={
            'new_password': 'UPPERCASE123',
            'confirm_password': 'UPPERCASE123'
        })
        assert form.validate() is False
        assert 'new_password' in form.errors
        assert 'Password must contain at least one lowercase letter.' in form.errors['new_password']
    
    def test_change_password_form_password_no_digit(self):
        """Test form validation with password missing digit"""
        form = ChangePasswordForm(data={
            'new_password': 'NoNumbers',
            'confirm_password': 'NoNumbers'
        })
        assert form.validate() is False
        assert 'new_password' in form.errors
        assert 'Password must contain at least one digit.' in form.errors['new_password']


class TestBulkUserActionForm:
    """Test BulkUserActionForm functionality"""
    
    def test_bulk_user_action_form_creation(self):
        """Test creating a bulk user action form"""
        form = BulkUserActionForm()
        assert form.action.data is None
        assert form.user_ids.data is None
    
    def test_bulk_user_action_form_valid_data(self):
        """Test bulk user action form with valid data"""
        form = BulkUserActionForm(data={
            'action': 'activate',
            'user_ids': '1,2,3'
        })
        assert form.action.data == 'activate'
        assert form.user_ids.data == '1,2,3'
    
    def test_bulk_user_action_form_validation_success(self):
        """Test successful form validation"""
        form = BulkUserActionForm(data={
            'action': 'activate',
            'user_ids': '1,2,3'
        })
        assert form.validate() is True
        assert hasattr(form, 'user_ids_list')
        assert form.user_ids_list == [1, 2, 3]
    
    def test_bulk_user_action_form_missing_action(self):
        """Test form validation with missing action"""
        form = BulkUserActionForm(data={
            'user_ids': '1,2,3'
        })
        assert form.validate() is False
        assert 'action' in form.errors
    
    def test_bulk_user_action_form_missing_user_ids(self):
        """Test form validation with missing user IDs"""
        form = BulkUserActionForm(data={
            'action': 'activate'
        })
        assert form.validate() is False
        assert 'user_ids' in form.errors
    
    def test_bulk_user_action_form_invalid_user_ids(self):
        """Test form validation with invalid user IDs"""
        form = BulkUserActionForm(data={
            'action': 'activate',
            'user_ids': '1,abc,3'
        })
        assert form.validate() is False
        assert 'user_ids' in form.errors
        assert 'User IDs must be numbers separated by commas.' in form.errors['user_ids']
    
    def test_bulk_user_action_form_empty_user_ids(self):
        """Test form validation with empty user IDs"""
        form = BulkUserActionForm(data={
            'action': 'activate',
            'user_ids': ''
        })
        assert form.validate() is False
        assert 'user_ids' in form.errors
    
    def test_bulk_user_action_form_whitespace_user_ids(self):
        """Test form validation with whitespace-only user IDs"""
        form = BulkUserActionForm(data={
            'action': 'activate',
            'user_ids': '   ,  ,  '
        })
        assert form.validate() is False
        assert 'user_ids' in form.errors
        # Check that we get a validation error for invalid user IDs
        assert len(form.errors['user_ids']) > 0
    
    def test_bulk_user_action_form_valid_actions(self):
        """Test form validation with all valid actions"""
        valid_actions = ['activate', 'deactivate', 'delete', 'export']
        
        for action in valid_actions:
            form = BulkUserActionForm(data={
                'action': action,
                'user_ids': '1,2,3'
            })
            assert form.validate() is True
    
    def test_bulk_user_action_form_user_ids_whitespace_handling(self):
        """Test form validation with user IDs containing whitespace"""
        form = BulkUserActionForm(data={
            'action': 'activate',
            'user_ids': ' 1 , 2 , 3 '
        })
        assert form.validate() is True
        assert form.user_ids_list == [1, 2, 3]
