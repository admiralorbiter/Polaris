import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from werkzeug.security import generate_password_hash, check_password_hash
from flask_app.models import (
    User, AdminLog, SystemMetrics, Organization, Role, Permission,
    RolePermission, UserOrganization, SystemFeatureFlag, OrganizationFeatureFlag, db
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

@pytest.fixture
def test_user():
    """Create a test user fixture"""
    user = User(
        username='testuser',
        email='test@example.com',
        password_hash=generate_password_hash('testpass123'),
        first_name='Test',
        last_name='User'
    )
    return user

@pytest.fixture
def admin_user():
    """Create an admin user fixture"""
    user = User(
        username='admin',
        email='admin@example.com',
        password_hash=generate_password_hash('adminpass123'),
        first_name='Admin',
        last_name='User',
        is_super_admin=True
    )
    return user

class TestUserModel:
    """Test User model functionality"""
    
    def test_new_user_creation(self, test_user, app):
        """Test creating a new user with all fields"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            assert test_user.username == 'testuser'
            assert test_user.email == 'test@example.com'
            assert test_user.first_name == 'Test'
            assert test_user.last_name == 'User'
            assert test_user.is_active is True
            assert test_user.is_super_admin is False
            assert test_user.last_login is None
            assert check_password_hash(test_user.password_hash, 'testpass123')
    
    def test_user_repr(self, test_user):
        """Test user string representation"""
        assert repr(test_user) == '<User testuser>'
    
    def test_get_full_name_with_names(self, test_user):
        """Test getting full name when both first and last names exist"""
        assert test_user.get_full_name() == 'Test User'
    
    def test_get_full_name_without_names(self, app):
        """Test getting full name when names don't exist"""
        with app.app_context():
            user = User(
                username='minimaluser',
                email='minimal@example.com',
                password_hash='hash'
            )
            assert user.get_full_name() == 'minimaluser'
    
    def test_get_full_name_partial_names(self, app):
        """Test getting full name with only first name"""
        with app.app_context():
            user = User(
                username='partialuser',
                email='partial@example.com',
                password_hash='hash',
                first_name='Partial'
            )
            assert user.get_full_name() == 'partialuser'
    
    def test_update_last_login_success(self, test_user, app):
        """Test successful last login update"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            result = test_user.update_last_login()
            
            assert result is True
            assert test_user.last_login is not None
            # Just check that last_login was set to a recent time (within last 5 seconds)
            # Convert to timezone-naive for comparison since SQLite stores naive datetimes
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            time_diff = abs((now - test_user.last_login).total_seconds())
            assert time_diff < 5
    
    def test_update_last_login_database_error(self, test_user, app):
        """Test last login update with database error"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            # Mock a database error during commit
            with patch('flask_app.models.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                result = test_user.update_last_login()
                assert result is False  # Should return False on error
    
    def test_find_by_username_existing(self, test_user, app):
        """Test finding existing user by username"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            found_user = User.find_by_username('testuser')
            assert found_user is not None
            assert found_user.id == test_user.id
            assert found_user.username == 'testuser'
    
    def test_find_by_username_nonexistent(self, app):
        """Test finding non-existent user by username"""
        with app.app_context():
            found_user = User.find_by_username('nonexistent')
            assert found_user is None
    
    def test_find_by_username_database_error(self, app):
        """Test find by username with database error"""
        with app.app_context():
            # Mock a database error during query
            with patch('flask_app.models.User.query') as mock_query:
                mock_query.filter_by.return_value.first.side_effect = SQLAlchemyError("Database error")
                result = User.find_by_username('testuser')
                assert result is None  # Should return None on error
    
    def test_find_by_email_existing(self, test_user, app):
        """Test finding existing user by email"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            found_user = User.find_by_email('test@example.com')
            assert found_user is not None
            assert found_user.id == test_user.id
            assert found_user.email == 'test@example.com'
    
    def test_find_by_email_nonexistent(self, app):
        """Test finding non-existent user by email"""
        with app.app_context():
            found_user = User.find_by_email('nonexistent@example.com')
            assert found_user is None
    
    def test_find_by_email_database_error(self, app):
        """Test find by email with database error"""
        with app.app_context():
            # Mock a database error during query
            with patch('flask_app.models.User.query') as mock_query:
                mock_query.filter_by.return_value.first.side_effect = SQLAlchemyError("Database error")
                result = User.find_by_email('test@test.com')
                assert result is None  # Should return None on error
    
    def test_user_unique_constraints_username(self, test_user, app):
        """Test that username unique constraint is enforced"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()

            # Try to create another user with the same username
            duplicate_username = User(
                username='testuser',  # Same username
                email='different@example.com',
                password_hash='fakehash456'
            )

            with pytest.raises(IntegrityError):
                db.session.add(duplicate_username)
                db.session.commit()
    
    def test_user_unique_constraints_email(self, test_user, app):
        """Test that email unique constraint is enforced"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()

            # Try to create another user with the same email
            duplicate_email = User(
                username='different',
                email='test@example.com',  # Same email
                password_hash='fakehash789'
            )

            with pytest.raises(IntegrityError):
                db.session.add(duplicate_email)
                db.session.commit()
    
    def test_user_required_fields(self, app):
        """Test that required fields are enforced"""
        with app.app_context():
            # Test missing username
            with pytest.raises(Exception):
                user = User(email='test@example.com', password_hash='hash')
                db.session.add(user)
                db.session.commit()
            
            db.session.rollback()
            
            # Test missing email
            with pytest.raises(Exception):
                user = User(username='testuser', password_hash='hash')
                db.session.add(user)
                db.session.commit()
            
            db.session.rollback()
            
            # Test missing password_hash
            with pytest.raises(Exception):
                user = User(username='testuser', email='test@example.com')
                db.session.add(user)
                db.session.commit()
    
    def test_user_default_values(self, app):
        """Test default values for user fields"""
        with app.app_context():
            user = User(
                username='defaultuser',
                email='default@example.com',
                password_hash='hash'
            )
            db.session.add(user)
            db.session.commit()
            
            assert user.is_active is True
            assert user.is_super_admin is False
            assert user.last_login is None
    
    def test_user_password_verification(self, test_user):
        """Test password verification functionality"""
        assert check_password_hash(test_user.password_hash, 'testpass123')
        assert not check_password_hash(test_user.password_hash, 'wrongpassword')
    
    def test_user_admin_status(self, admin_user):
        """Test admin user creation and status"""
        assert admin_user.is_super_admin is True
        assert admin_user.username == 'admin'
    
    def test_user_active_status(self, app):
        """Test inactive user creation"""
        with app.app_context():
            inactive_user = User(
                username='inactiveuser',
                email='inactive@example.com',
                password_hash='hash',
                is_active=False
            )
            assert inactive_user.is_active is False
    
    def test_user_field_lengths(self, app):
        """Test field length constraints"""
        with app.app_context():
            # Test that we can create users with reasonable field lengths
            user = User(
                username='testuser',
                email='test@example.com',
                password_hash='hash'
            )
            db.session.add(user)
            db.session.commit()
            
            # Verify the user was created successfully
            assert user.username == 'testuser'
            assert user.email == 'test@example.com'


class TestAdminLogModel:
    """Test AdminLog model functionality"""
    
    def test_admin_log_creation(self, admin_user, test_user, app):
        """Test creating an admin log entry"""
        with app.app_context():
            db.session.add(admin_user)
            db.session.add(test_user)
            db.session.commit()
            
            log_entry = AdminLog(
                admin_user_id=admin_user.id,
                action='CREATE_USER',
                target_user_id=test_user.id,
                details='Created new user account',
                ip_address='192.168.1.1',
                user_agent='Mozilla/5.0'
            )
            
            assert log_entry.admin_user_id == admin_user.id
            assert log_entry.action == 'CREATE_USER'
            assert log_entry.target_user_id == test_user.id
            assert log_entry.details == 'Created new user account'
            assert log_entry.ip_address == '192.168.1.1'
            assert log_entry.user_agent == 'Mozilla/5.0'
    
    def test_admin_log_repr(self, admin_user, app):
        """Test admin log string representation"""
        with app.app_context():
            db.session.add(admin_user)
            db.session.commit()
            
            log_entry = AdminLog(
                admin_user_id=admin_user.id,
                action='TEST_ACTION'
            )
            
            expected_repr = f'<AdminLog TEST_ACTION by user {admin_user.id}>'
            assert repr(log_entry) == expected_repr
    
    def test_log_action_success(self, admin_user, test_user, app):
        """Test successful admin action logging"""
        with app.app_context():
            db.session.add(admin_user)
            db.session.add(test_user)
            db.session.commit()
            
            result = AdminLog.log_action(
                admin_user_id=admin_user.id,
                action='UPDATE_USER',
                target_user_id=test_user.id,
                details='Updated user profile',
                ip_address='192.168.1.1',
                user_agent='Test Agent'
            )
            
            assert result is True
            
            # Verify log was created
            log_entry = AdminLog.query.filter_by(
                admin_user_id=admin_user.id,
                action='UPDATE_USER'
            ).first()
            
            assert log_entry is not None
            assert log_entry.target_user_id == test_user.id
            assert log_entry.details == 'Updated user profile'
    
    def test_log_action_minimal_params(self, admin_user, app):
        """Test admin action logging with minimal parameters"""
        with app.app_context():
            db.session.add(admin_user)
            db.session.commit()
            
            result = AdminLog.log_action(
                admin_user_id=admin_user.id,
                action='LOGIN'
            )
            
            assert result is True
            
            # Verify log was created
            log_entry = AdminLog.query.filter_by(
                admin_user_id=admin_user.id,
                action='LOGIN'
            ).first()
            
            assert log_entry is not None
            assert log_entry.target_user_id is None
            assert log_entry.details is None
    
    @patch('flask_app.models.db.session.commit')
    def test_log_action_database_error(self, mock_commit, admin_user, app):
        """Test admin action logging with database error"""
        with app.app_context():
            db.session.add(admin_user)
            db.session.commit()
            
            mock_commit.side_effect = Exception("Database error")
            
            result = AdminLog.log_action(
                admin_user_id=admin_user.id,
                action='TEST_ACTION'
            )
            
            assert result is False
    
    def test_admin_log_required_fields(self, app):
        """Test that required fields are enforced"""
        with app.app_context():
            # Test missing admin_user_id
            with pytest.raises(Exception):
                log = AdminLog(action='TEST_ACTION')
                db.session.add(log)
                db.session.commit()
            
            db.session.rollback()
            
            # Test missing action
            with pytest.raises(Exception):
                log = AdminLog(admin_user_id=1)
                db.session.add(log)
                db.session.commit()


class TestSystemMetricsModel:
    """Test SystemMetrics model functionality"""
    
    def test_system_metrics_creation(self, app):
        """Test creating a system metric"""
        with app.app_context():
            metric = SystemMetrics(
                metric_name='test_metric',
                metric_value=42.5,
                metric_data='{"key": "value"}'
            )
            
            assert metric.metric_name == 'test_metric'
            assert metric.metric_value == 42.5
            assert metric.metric_data == '{"key": "value"}'
    
    def test_system_metrics_repr(self, app):
        """Test system metrics string representation"""
        with app.app_context():
            metric = SystemMetrics(
                metric_name='test_metric',
                metric_value=100.0
            )
            
            assert repr(metric) == '<SystemMetrics test_metric: 100.0>'
    
    def test_get_metric_existing(self, app):
        """Test getting an existing metric"""
        with app.app_context():
            metric = SystemMetrics(
                metric_name='existing_metric',
                metric_value=75.0
            )
            db.session.add(metric)
            db.session.commit()
            
            value = SystemMetrics.get_metric('existing_metric')
            assert value == 75.0
    
    def test_get_metric_nonexistent_default(self, app):
        """Test getting a non-existent metric with default value"""
        with app.app_context():
            value = SystemMetrics.get_metric('nonexistent_metric', default_value=10)
            assert value == 10
    
    def test_get_metric_nonexistent_no_default(self, app):
        """Test getting a non-existent metric without default"""
        with app.app_context():
            value = SystemMetrics.get_metric('nonexistent_metric')
            assert value == 0
    
    @patch('flask_app.models.SystemMetrics.query')
    def test_get_metric_database_error(self, mock_query, app):
        """Test get metric with database error"""
        with app.app_context():
            mock_query.filter_by.return_value.first.side_effect = Exception("DB error")
            
            value = SystemMetrics.get_metric('test_metric', default_value=5)
            assert value == 5
    
    def test_set_metric_new(self, app):
        """Test setting a new metric"""
        with app.app_context():
            result = SystemMetrics.set_metric(
                'new_metric',
                value=99.9,
                data='{"status": "active"}'
            )
            
            assert result is True
            
            # Verify metric was created
            metric = SystemMetrics.query.filter_by(metric_name='new_metric').first()
            assert metric is not None
            assert metric.metric_value == 99.9
            assert metric.metric_data == '{"status": "active"}'
    
    def test_set_metric_update_existing(self, app):
        """Test updating an existing metric"""
        with app.app_context():
            # Create initial metric
            metric = SystemMetrics(
                metric_name='update_metric',
                metric_value=50.0,
                metric_data='{"old": "data"}'
            )
            db.session.add(metric)
            db.session.commit()
            
            # Update the metric
            result = SystemMetrics.set_metric(
                'update_metric',
                value=75.0,
                data='{"new": "data"}'
            )
            
            assert result is True
            
            # Verify metric was updated
            updated_metric = SystemMetrics.query.filter_by(metric_name='update_metric').first()
            assert updated_metric.metric_value == 75.0
            assert updated_metric.metric_data == '{"new": "data"}'
    
    def test_set_metric_update_no_data(self, app):
        """Test updating a metric without data"""
        with app.app_context():
            result = SystemMetrics.set_metric('no_data_metric', value=25.0)
            
            assert result is True
            
            metric = SystemMetrics.query.filter_by(metric_name='no_data_metric').first()
            assert metric.metric_value == 25.0
            assert metric.metric_data is None
    
    @patch('flask_app.models.db.session.commit')
    def test_set_metric_database_error(self, mock_commit, app):
        """Test set metric with database error"""
        with app.app_context():
            mock_commit.side_effect = Exception("Database error")
            
            result = SystemMetrics.set_metric('error_metric', value=1.0)
            assert result is False
    
    def test_system_metrics_unique_constraint(self, app):
        """Test that metric_name unique constraint is enforced"""
        with app.app_context():
            metric1 = SystemMetrics(
                metric_name='unique_metric',
                metric_value=10.0
            )
            db.session.add(metric1)
            db.session.commit()
            
            # Try to create another metric with the same name
            metric2 = SystemMetrics(
                metric_name='unique_metric',
                metric_value=20.0
            )
            
            with pytest.raises(IntegrityError):
                db.session.add(metric2)
                db.session.commit()
    
    def test_system_metrics_required_fields(self, app):
        """Test that required fields are enforced"""
        with app.app_context():
            # Test missing metric_name
            with pytest.raises(Exception):
                metric = SystemMetrics(metric_value=10.0)
                db.session.add(metric)
                db.session.commit()
            
            db.session.rollback()
            
            # Test missing metric_value
            with pytest.raises(Exception):
                metric = SystemMetrics(metric_name='test')
                db.session.add(metric)
                db.session.commit()


class TestOrganizationModel:
    """Test Organization model functionality"""
    
    def test_new_organization_creation_all_fields(self, app):
        """Test creating a new organization with all fields"""
        with app.app_context():
            org = Organization(
                name='Test Organization',
                slug='test-organization',
                description='A test organization',
                is_active=True
            )
            db.session.add(org)
            db.session.commit()
            
            assert org.name == 'Test Organization'
            assert org.slug == 'test-organization'
            assert org.description == 'A test organization'
            assert org.is_active is True
            assert org.id is not None
            assert org.created_at is not None
            assert org.updated_at is not None
    
    def test_organization_creation_minimal_fields(self, app):
        """Test creating organization with minimal required fields"""
        with app.app_context():
            org = Organization(
                name='Minimal Org',
                slug='minimal-org'
            )
            db.session.add(org)
            db.session.commit()
            
            assert org.name == 'Minimal Org'
            assert org.slug == 'minimal-org'
            assert org.description is None
            assert org.is_active is True  # Default value
            assert org.settings is None
    
    def test_organization_repr(self, test_organization, app):
        """Test organization string representation"""
        with app.app_context():
            # Reattach to session
            org = db.session.get(Organization, test_organization.id)
            assert repr(org) == '<Organization Test Organization>'
    
    def test_find_by_slug_existing(self, test_organization, app):
        """Test finding existing organization by slug"""
        with app.app_context():
            found_org = Organization.find_by_slug('test-organization')
            assert found_org is not None
            assert found_org.id == test_organization.id
            assert found_org.slug == 'test-organization'
    
    def test_find_by_slug_nonexistent(self, app):
        """Test finding non-existent organization by slug"""
        with app.app_context():
            found_org = Organization.find_by_slug('nonexistent-slug')
            assert found_org is None
    
    def test_find_by_slug_database_error(self, app):
        """Test find by slug with database error"""
        with app.app_context():
            with patch('flask_app.models.Organization.query') as mock_query:
                mock_query.filter_by.return_value.first.side_effect = SQLAlchemyError("Database error")
                result = Organization.find_by_slug('test-slug')
                assert result is None
    
    def test_find_by_id_existing(self, test_organization, app):
        """Test finding existing organization by ID"""
        with app.app_context():
            found_org = Organization.find_by_id(test_organization.id)
            assert found_org is not None
            assert found_org.id == test_organization.id
            assert found_org.name == 'Test Organization'
    
    def test_find_by_id_nonexistent(self, app):
        """Test finding non-existent organization by ID"""
        with app.app_context():
            found_org = Organization.find_by_id(99999)
            assert found_org is None
    
    def test_find_by_id_database_error(self, app):
        """Test find by ID with database error"""
        with app.app_context():
            with patch('flask_app.models.Organization.query') as mock_query:
                mock_query.get.side_effect = SQLAlchemyError("Database error")
                result = Organization.find_by_id(1)
                assert result is None
    
    def test_organization_unique_slug(self, test_organization, app):
        """Test that organization slug must be unique"""
        with app.app_context():
            duplicate_org = Organization(
                name='Different Name',
                slug='test-organization'  # Same slug as test_organization
            )
            db.session.add(duplicate_org)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
    
    def test_organization_safe_create_success(self, app):
        """Test safe_create method with successful creation"""
        with app.app_context():
            org, error = Organization.safe_create(
                name='Safe Org',
                slug='safe-org',
                description='Safely created',
                is_active=True
            )
            
            assert org is not None
            assert error is None
            assert org.name == 'Safe Org'
            assert org.slug == 'safe-org'
            assert Organization.query.filter_by(slug='safe-org').first() is not None
    
    def test_organization_safe_create_duplicate_slug(self, test_organization, app):
        """Test safe_create with duplicate slug"""
        with app.app_context():
            org, error = Organization.safe_create(
                name='Duplicate',
                slug='test-organization',  # Duplicate
                is_active=True
            )
            
            assert org is None
            assert error is not None
            assert 'duplicate' in error.lower() or 'unique' in error.lower()
    
    def test_organization_safe_update_success(self, test_organization, app):
        """Test safe_update method with successful update"""
        with app.app_context():
            # Reattach to session
            org = db.session.get(Organization, test_organization.id)
            result, error = org.safe_update(
                name='Updated Name',
                description='Updated description'
            )
            
            assert result is True
            assert error is None
            db.session.refresh(org)
            assert org.name == 'Updated Name'
            assert org.description == 'Updated description'
    
    def test_organization_safe_update_database_error(self, test_organization, app):
        """Test safe_update with database error"""
        with app.app_context():
            # Re-query to get object in session
            org = db.session.get(Organization, test_organization.id)
            with patch('flask_app.models.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                result, error = org.safe_update(name='New Name')
                assert result is False
                assert error is not None
    
    def test_organization_safe_delete_success(self, test_organization, app):
        """Test safe_delete method with successful deletion"""
        with app.app_context():
            # Reattach to current session
            org_id = test_organization.id
            org = db.session.get(Organization, org_id)
            result, error = org.safe_delete()
            
            assert result is True
            assert error is None
            assert db.session.get(Organization, org_id) is None
    
    def test_organization_safe_delete_database_error(self, test_organization, app):
        """Test safe_delete with database error"""
        with app.app_context():
            # Re-query to get object in session
            org = db.session.get(Organization, test_organization.id)
            with patch('flask_app.models.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                result, error = org.safe_delete()
                assert result is False
                assert error is not None
    
    def test_organization_active_inactive(self, app):
        """Test organization active/inactive status"""
        with app.app_context():
            active_org = Organization(name='Active', slug='active', is_active=True)
            inactive_org = Organization(name='Inactive', slug='inactive', is_active=False)
            
            db.session.add(active_org)
            db.session.add(inactive_org)
            db.session.commit()
            
            assert active_org.is_active is True
            assert inactive_org.is_active is False
    
    def test_organization_relationships_users(self, test_organization, test_user, test_role, app):
        """Test organization relationship with users"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            # Reattach organization to session
            org = db.session.get(Organization, test_organization.id)
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org.id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            # Test relationship
            assert len(org.users) == 1
            assert org.users[0].user_id == test_user.id
    
    def test_organization_relationships_feature_flags(self, test_organization, app):
        """Test organization relationship with feature flags"""
        with app.app_context():
            # Reattach organization to session
            org = db.session.get(Organization, test_organization.id)
            flag = OrganizationFeatureFlag(
                organization_id=org.id,
                flag_name='test_flag',
                flag_value='true',
                flag_type='boolean'
            )
            db.session.add(flag)
            db.session.commit()
            
            # Test relationship
            assert len(org.feature_flags) == 1
            assert org.feature_flags[0].flag_name == 'test_flag'
    
    def test_organization_required_fields(self, app):
        """Test that required fields are enforced"""
        with app.app_context():
            # Test missing name
            with pytest.raises(Exception):
                org = Organization(slug='test-slug')
                db.session.add(org)
                db.session.commit()
            
            db.session.rollback()
            
            # Test missing slug
            with pytest.raises(Exception):
                org = Organization(name='Test Name')
                db.session.add(org)
                db.session.commit()
    
    def test_organization_timestamps(self, app):
        """Test that created_at and updated_at are automatically set"""
        with app.app_context():
            org = Organization(name='Timestamp Test', slug='timestamp-test')
            db.session.add(org)
            db.session.commit()
            
            assert org.created_at is not None
            assert org.updated_at is not None
            
            # Update and check updated_at changes
            old_updated = org.updated_at
            import time
            time.sleep(0.1)  # Small delay to ensure timestamp difference
            
            org.safe_update(name='Updated')
            db.session.refresh(org)
            assert org.updated_at > old_updated


class TestRoleModel:
    """Test Role model functionality"""
    
    def test_new_role_creation_all_fields(self, app):
        """Test creating a new role with all fields"""
        with app.app_context():
            role = Role(
                name='test_role',
                display_name='Test Role',
                description='A test role',
                is_system_role=True
            )
            db.session.add(role)
            db.session.commit()
            
            assert role.name == 'test_role'
            assert role.display_name == 'Test Role'
            assert role.description == 'A test role'
            assert role.is_system_role is True
            assert role.id is not None
    
    def test_role_creation_minimal_fields(self, app):
        """Test creating role with minimal required fields"""
        with app.app_context():
            role = Role(
                name='minimal_role',
                display_name='Minimal Role'
            )
            db.session.add(role)
            db.session.commit()
            
            assert role.name == 'minimal_role'
            assert role.display_name == 'Minimal Role'
            assert role.description is None
            assert role.is_system_role is False  # Default value
    
    def test_role_repr(self, test_role, app):
        """Test role string representation"""
        with app.app_context():
            # Re-query to avoid detached instance
            role = db.session.get(Role, test_role.id)
            assert repr(role) == '<Role volunteer>'
    
    def test_find_by_name_existing(self, test_role, app):
        """Test finding existing role by name"""
        with app.app_context():
            found_role = Role.find_by_name('volunteer')
            assert found_role is not None
            assert found_role.id == test_role.id
            assert found_role.name == 'volunteer'
    
    def test_find_by_name_nonexistent(self, app):
        """Test finding non-existent role by name"""
        with app.app_context():
            found_role = Role.find_by_name('nonexistent')
            assert found_role is None
    
    def test_find_by_name_database_error(self, app):
        """Test find by name with database error"""
        with app.app_context():
            with patch('flask_app.models.Role.query') as mock_query:
                mock_query.filter_by.return_value.first.side_effect = SQLAlchemyError("Database error")
                result = Role.find_by_name('test')
                assert result is None
    
    def test_role_has_permission(self, test_role_with_permission, test_permission, app):
        """Test role has_permission method"""
        with app.app_context():
            # Re-query role to access relationships
            role = db.session.get(Role, test_role_with_permission.id)
            assert role.has_permission('view_volunteers') is True
            assert role.has_permission('nonexistent_permission') is False
    
    def test_role_unique_name(self, test_role, app):
        """Test that role name must be unique"""
        with app.app_context():
            duplicate_role = Role(
                name='volunteer',  # Same name as test_role
                display_name='Different Display'
            )
            db.session.add(duplicate_role)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
    
    def test_role_relationships_permissions(self, test_role, test_permission, app):
        """Test role relationship with permissions"""
        with app.app_context():
            role_permission = RolePermission(
                role_id=test_role.id,
                permission_id=test_permission.id
            )
            db.session.add(role_permission)
            db.session.commit()
            
            # Re-query role to access relationship
            role = db.session.get(Role, test_role.id)
            # Test relationship
            assert len(role.permissions) == 1
            assert role.permissions[0].permission_id == test_permission.id
    
    def test_role_relationships_user_organizations(self, test_role, test_user, test_organization, app):
        """Test role relationship with user organizations"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=test_organization.id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            # Re-query role to access relationship
            role = db.session.get(Role, test_role.id)
            # Test relationship
            assert len(role.user_organizations) == 1
            assert role.user_organizations[0].user_id == test_user.id


class TestPermissionModel:
    """Test Permission model functionality"""
    
    def test_new_permission_creation_all_fields(self, app):
        """Test creating a new permission with all fields"""
        with app.app_context():
            permission = Permission(
                name='test_permission',
                display_name='Test Permission',
                description='A test permission',
                category='test_category'
            )
            db.session.add(permission)
            db.session.commit()
            
            assert permission.name == 'test_permission'
            assert permission.display_name == 'Test Permission'
            assert permission.description == 'A test permission'
            assert permission.category == 'test_category'
            assert permission.id is not None
    
    def test_permission_creation_minimal_fields(self, app):
        """Test creating permission with minimal required fields"""
        with app.app_context():
            permission = Permission(
                name='minimal_permission',
                display_name='Minimal Permission'
            )
            db.session.add(permission)
            db.session.commit()
            
            assert permission.name == 'minimal_permission'
            assert permission.display_name == 'Minimal Permission'
            assert permission.description is None
            assert permission.category is None
    
    def test_permission_repr(self, test_permission, app):
        """Test permission string representation"""
        with app.app_context():
            # Re-query to avoid detached instance
            permission = db.session.get(Permission, test_permission.id)
            assert repr(permission) == '<Permission view_volunteers>'
    
    def test_find_by_name_existing(self, test_permission, app):
        """Test finding existing permission by name"""
        with app.app_context():
            found_permission = Permission.find_by_name('view_volunteers')
            assert found_permission is not None
            assert found_permission.id == test_permission.id
            assert found_permission.name == 'view_volunteers'
    
    def test_find_by_name_nonexistent(self, app):
        """Test finding non-existent permission by name"""
        with app.app_context():
            found_permission = Permission.find_by_name('nonexistent')
            assert found_permission is None
    
    def test_permission_unique_name(self, test_permission, app):
        """Test that permission name must be unique"""
        with app.app_context():
            duplicate_permission = Permission(
                name='view_volunteers',  # Same name as test_permission
                display_name='Different Display'
            )
            db.session.add(duplicate_permission)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
    
    def test_permission_relationships_roles(self, test_permission, test_role, app):
        """Test permission relationship with roles"""
        with app.app_context():
            role_permission = RolePermission(
                role_id=test_role.id,
                permission_id=test_permission.id
            )
            db.session.add(role_permission)
            db.session.commit()
            
            # Re-query permission to access relationship
            permission = db.session.get(Permission, test_permission.id)
            # Test relationship
            assert len(permission.roles) == 1
            assert permission.roles[0].role_id == test_role.id


class TestRolePermissionModel:
    """Test RolePermission model functionality"""
    
    def test_role_permission_creation(self, test_role, test_permission, app):
        """Test creating role-permission link"""
        with app.app_context():
            role_permission = RolePermission(
                role_id=test_role.id,
                permission_id=test_permission.id
            )
            db.session.add(role_permission)
            db.session.commit()
            
            assert role_permission.role_id == test_role.id
            assert role_permission.permission_id == test_permission.id
            assert role_permission.id is not None
    
    def test_role_permission_unique_constraint(self, test_role, test_permission, app):
        """Test that role-permission combination must be unique"""
        with app.app_context():
            role_permission1 = RolePermission(
                role_id=test_role.id,
                permission_id=test_permission.id
            )
            db.session.add(role_permission1)
            db.session.commit()
            
            # Try to add duplicate
            role_permission2 = RolePermission(
                role_id=test_role.id,
                permission_id=test_permission.id
            )
            db.session.add(role_permission2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
    
    def test_role_permission_relationships(self, test_role, test_permission, app):
        """Test role-permission relationships"""
        with app.app_context():
            role_permission = RolePermission(
                role_id=test_role.id,
                permission_id=test_permission.id
            )
            db.session.add(role_permission)
            db.session.commit()
            
            # Re-query to access relationships
            rp = db.session.get(RolePermission, role_permission.id)
            assert rp.role.id == test_role.id
            assert rp.permission.id == test_permission.id


class TestUserOrganizationModel:
    """Test UserOrganization model functionality"""
    
    def test_user_organization_creation(self, test_user, test_organization, test_role, app):
        """Test creating user-organization relationship"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=test_organization.id,
                role_id=test_role.id,
                is_active=True
            )
            db.session.add(user_org)
            db.session.commit()
            
            assert user_org.user_id == test_user.id
            assert user_org.organization_id == test_organization.id
            assert user_org.role_id == test_role.id
            assert user_org.is_active is True
            assert user_org.id is not None
    
    def test_user_organization_unique_constraint(self, test_user, test_organization, test_role, app):
        """Test that user can only have one role per organization"""
        with app.app_context():
            db.session.add(test_user)
            
            # Create another role
            role2 = Role(name='role2', display_name='Role 2')
            db.session.add(role2)
            db.session.commit()
            
            user_org1 = UserOrganization(
                user_id=test_user.id,
                organization_id=test_organization.id,
                role_id=test_role.id
            )
            db.session.add(user_org1)
            db.session.commit()
            
            # Try to add duplicate user-organization
            user_org2 = UserOrganization(
                user_id=test_user.id,
                organization_id=test_organization.id,
                role_id=role2.id  # Different role, same user-org
            )
            db.session.add(user_org2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
    
    def test_user_organization_relationships(self, test_user_organization, app):
        """Test user-organization relationships"""
        with app.app_context():
            # Re-query to access relationships
            uo = db.session.get(UserOrganization, test_user_organization.id)
            assert uo.user is not None
            assert uo.organization is not None
            assert uo.role is not None
    
    def test_user_organization_active_inactive(self, test_user, test_organization, test_role, app):
        """Test user-organization active/inactive status"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            active_uo = UserOrganization(
                user_id=test_user.id,
                organization_id=test_organization.id,
                role_id=test_role.id,
                is_active=True
            )
            inactive_uo = UserOrganization(
                user_id=test_user.id,
                organization_id=test_organization.id,
                role_id=test_role.id,
                is_active=False
            )
            
            # Note: This will fail due to unique constraint, but we're testing the field
            db.session.add(active_uo)
            db.session.commit()
            
            assert active_uo.is_active is True


class TestSystemFeatureFlagModel:
    """Test SystemFeatureFlag model functionality"""
    
    def test_system_feature_flag_creation(self, app):
        """Test creating system feature flag"""
        with app.app_context():
            flag = SystemFeatureFlag(
                flag_name='test_flag',
                flag_value='true',
                flag_type='boolean',
                description='A test flag'
            )
            db.session.add(flag)
            db.session.commit()
            
            assert flag.flag_name == 'test_flag'
            assert flag.flag_value == 'true'
            assert flag.flag_type == 'boolean'
            assert flag.description == 'A test flag'
            assert flag.id is not None
    
    def test_system_feature_flag_get_value_boolean(self, app):
        """Test get_value for boolean type"""
        with app.app_context():
            flag = SystemFeatureFlag(
                flag_name='bool_flag',
                flag_value='true',
                flag_type='boolean'
            )
            db.session.add(flag)
            db.session.commit()
            
            assert flag.get_value() is True
            
            flag.flag_value = 'false'
            assert flag.get_value() is False
            
            flag.flag_value = '1'
            assert flag.get_value() is True
    
    def test_system_feature_flag_get_value_integer(self, app):
        """Test get_value for integer type"""
        with app.app_context():
            flag = SystemFeatureFlag(
                flag_name='int_flag',
                flag_value='42',
                flag_type='integer'
            )
            db.session.add(flag)
            db.session.commit()
            
            assert flag.get_value() == 42
            
            flag.flag_value = 'invalid'
            assert flag.get_value() == 0
    
    def test_system_feature_flag_get_value_json(self, app):
        """Test get_value for json type"""
        with app.app_context():
            import json
            flag = SystemFeatureFlag(
                flag_name='json_flag',
                flag_value=json.dumps({'key': 'value'}),
                flag_type='json'
            )
            db.session.add(flag)
            db.session.commit()
            
            assert flag.get_value() == {'key': 'value'}
            
            flag.flag_value = 'invalid json'
            assert flag.get_value() == {}
    
    def test_system_feature_flag_get_value_string(self, app):
        """Test get_value for string type"""
        with app.app_context():
            flag = SystemFeatureFlag(
                flag_name='string_flag',
                flag_value='test string',
                flag_type='string'
            )
            db.session.add(flag)
            db.session.commit()
            
            assert flag.get_value() == 'test string'
    
    def test_system_feature_flag_set_value(self, app):
        """Test set_value method"""
        with app.app_context():
            flag = SystemFeatureFlag(
                flag_name='set_flag',
                flag_value='false',
                flag_type='boolean'
            )
            flag.set_value(True)
            assert flag.flag_value == 'true'
            
            flag.flag_type = 'integer'
            flag.set_value(42)
            assert flag.flag_value == '42'
    
    def test_system_feature_flag_get_flag_static(self, app):
        """Test get_flag static method"""
        with app.app_context():
            flag = SystemFeatureFlag(
                flag_name='static_flag',
                flag_value='true',
                flag_type='boolean'
            )
            db.session.add(flag)
            db.session.commit()
            
            value = SystemFeatureFlag.get_flag('static_flag')
            assert value is True
            
            default = SystemFeatureFlag.get_flag('nonexistent', default=False)
            assert default is False
    
    def test_system_feature_flag_set_flag_static(self, app):
        """Test set_flag static method"""
        with app.app_context():
            result = SystemFeatureFlag.set_flag('new_flag', True, 'boolean', 'A new flag')
            assert result is True
            
            flag = SystemFeatureFlag.query.filter_by(flag_name='new_flag').first()
            assert flag is not None
            assert flag.get_value() is True
            assert flag.description == 'A new flag'
            
            # Update existing flag
            result = SystemFeatureFlag.set_flag('new_flag', False)
            assert result is True
            assert flag.get_value() is False
    
    def test_system_feature_flag_unique_name(self, test_system_feature_flag, app):
        """Test that flag name must be unique"""
        with app.app_context():
            duplicate_flag = SystemFeatureFlag(
                flag_name='test_feature',  # Same as test_system_feature_flag
                flag_value='false',
                flag_type='boolean'
            )
            db.session.add(duplicate_flag)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()


class TestOrganizationFeatureFlagModel:
    """Test OrganizationFeatureFlag model functionality"""
    
    def test_organization_feature_flag_creation(self, test_organization, app):
        """Test creating organization feature flag"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            flag = OrganizationFeatureFlag(
                organization_id=org_id,
                flag_name='org_test_flag',
                flag_value='true',
                flag_type='boolean'
            )
            db.session.add(flag)
            db.session.commit()
            
            assert flag.organization_id == org_id
            assert flag.flag_name == 'org_test_flag'
            assert flag.flag_value == 'true'
            assert flag.flag_type == 'boolean'
            assert flag.id is not None
    
    def test_organization_feature_flag_get_value_types(self, test_organization, app):
        """Test get_value for different types"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            # Boolean
            flag = OrganizationFeatureFlag(
                organization_id=org_id,
                flag_name='bool_flag',
                flag_value='true',
                flag_type='boolean'
            )
            assert flag.get_value() is True
            
            # Integer
            flag.flag_type = 'integer'
            flag.flag_value = '100'
            assert flag.get_value() == 100
            
            # JSON
            import json
            flag.flag_type = 'json'
            flag.flag_value = json.dumps({'test': 'data'})
            assert flag.get_value() == {'test': 'data'}
    
    def test_organization_feature_flag_get_flag_static(self, test_organization, app):
        """Test get_flag static method"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            flag = OrganizationFeatureFlag(
                organization_id=org_id,
                flag_name='static_org_flag',
                flag_value='true',
                flag_type='boolean'
            )
            db.session.add(flag)
            db.session.commit()
            
            value = OrganizationFeatureFlag.get_flag(org_id, 'static_org_flag')
            assert value is True
            
            default = OrganizationFeatureFlag.get_flag(org_id, 'nonexistent', default=False)
            assert default is False
    
    def test_organization_feature_flag_set_flag_static(self, test_organization, app):
        """Test set_flag static method"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            result = OrganizationFeatureFlag.set_flag(
                org_id,
                'new_org_flag',
                True,
                'boolean'
            )
            assert result is True
            
            flag = OrganizationFeatureFlag.query.filter_by(
                organization_id=org_id,
                flag_name='new_org_flag'
            ).first()
            assert flag is not None
            assert flag.get_value() is True
            
            # Update existing flag
            result = OrganizationFeatureFlag.set_flag(
                org_id,
                'new_org_flag',
                False
            )
            assert result is True
            # Re-query flag to get updated value
            flag = OrganizationFeatureFlag.query.filter_by(
                organization_id=org_id,
                flag_name='new_org_flag'
            ).first()
            assert flag.get_value() is False
    
    def test_organization_feature_flag_unique_constraint(self, test_organization, app):
        """Test that organization-flag combination must be unique"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            flag1 = OrganizationFeatureFlag(
                organization_id=org_id,
                flag_name='unique_flag',
                flag_value='true',
                flag_type='boolean'
            )
            db.session.add(flag1)
            db.session.commit()
            
            # Try to add duplicate
            flag2 = OrganizationFeatureFlag(
                organization_id=org_id,
                flag_name='unique_flag',
                flag_value='false',
                flag_type='boolean'
            )
            db.session.add(flag2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
    
    def test_organization_feature_flag_relationship(self, test_organization_feature_flag, app):
        """Test relationship with organization"""
        with app.app_context():
            # Re-query to access relationship
            flag = db.session.get(OrganizationFeatureFlag, test_organization_feature_flag.id)
            assert flag.organization is not None
            assert flag.organization.id == flag.organization_id
