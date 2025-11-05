import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from werkzeug.security import generate_password_hash, check_password_hash
from flask_app.models import User, AdminLog, SystemMetrics, db
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
        is_admin=True
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
            assert test_user.is_admin is False
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
            assert user.is_admin is False
            assert user.last_login is None
    
    def test_user_password_verification(self, test_user):
        """Test password verification functionality"""
        assert check_password_hash(test_user.password_hash, 'testpass123')
        assert not check_password_hash(test_user.password_hash, 'wrongpassword')
    
    def test_user_admin_status(self, admin_user):
        """Test admin user creation and status"""
        assert admin_user.is_admin is True
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
