# conftest.py

import pytest
import os
import tempfile
from unittest.mock import patch
from app import app as flask_app
from flask_app.models import db, User, AdminLog, SystemMetrics
from config import TestingConfig
from werkzeug.security import generate_password_hash

@pytest.fixture(scope='function')
def app():
    """Create and configure a test Flask application"""
    # Create a new app instance for each test
    from app import app as flask_app
    import tempfile
    import uuid
    
    # Create a unique temporary database file for each test
    db_fd, temp_db = tempfile.mkstemp(suffix=f'_{uuid.uuid4().hex[:8]}.db')
    
    # Configure the app for testing
    flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{temp_db}',
        'SECRET_KEY': 'test-secret-key-for-testing-only',
        'DEBUG': True,
        'MONITORING_ENABLED': False,
        'ERROR_ALERTING_ENABLED': False
    })

    with flask_app.app_context():
        # Create all tables
        db.create_all()
        yield flask_app
        # Drop all tables
        db.session.remove()
        db.drop_all()
    
    # Close the temporary database file
    os.close(db_fd)
    os.unlink(temp_db)

@pytest.fixture(autouse=True)
def app_context(app):
    """Automatically provide app context for all tests"""
    with app.app_context():
        yield

@pytest.fixture
def client(app):
    """Create a test client for the Flask application"""
    return app.test_client()

@pytest.fixture
def runner(app):
    """Create a test CLI runner for the Flask application"""
    return app.test_cli_runner()

@pytest.fixture
def test_user():
    """Create a test user fixture"""
    user = User(
        username='testuser',
        email='test@example.com',
        password_hash=generate_password_hash('testpass123'),
        first_name='Test',
        last_name='User',
        is_active=True,
        is_admin=False
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

@pytest.fixture
def inactive_user():
    """Create an inactive user fixture"""
    user = User(
        username='inactiveuser',
        email='inactive@example.com',
        password_hash=generate_password_hash('userpass123'),
        is_active=False
    )
    return user

@pytest.fixture
def sample_users(app):
    """Create multiple sample users for testing"""
    users = []
    for i in range(5):
        user = User(
            username=f'sampleuser{i}',
            email=f'sample{i}@example.com',
            password_hash=generate_password_hash('userpass123'),
            first_name=f'Sample{i}',
            last_name='User'
        )
        users.append(user)
    return users

@pytest.fixture
def logged_in_user(client, test_user, app):
    """Fixture that logs in a user and returns the client"""
    with app.app_context():
        db.session.add(test_user)
        db.session.commit()
        
        client.post('/login', data={
            'username': 'testuser',
            'password': 'testpass123'
        })
        
        yield client, test_user

@pytest.fixture
def logged_in_admin(client, admin_user, app):
    """Fixture that logs in an admin user and returns the client"""
    with app.app_context():
        db.session.add(admin_user)
        db.session.commit()
        
        client.post('/login', data={
            'username': 'admin',
            'password': 'adminpass123'
        })
        
        yield client, admin_user

@pytest.fixture
def mock_logger():
    """Mock logger for testing"""
    with patch('flask_app.utils.logging_config.current_app.logger') as mock_log:
        yield mock_log

@pytest.fixture
def mock_email():
    """Mock email sending for testing"""
    with patch('flask_app.utils.error_handler.send_email') as mock_send:
        yield mock_send

@pytest.fixture
def mock_metrics():
    """Mock system metrics for testing"""
    with patch('flask_app.utils.monitoring.collect_system_metrics') as mock_collect:
        mock_collect.return_value = {
            'cpu_percent': 25.5,
            'memory_percent': 60.2,
            'disk_percent': 45.8,
            'timestamp': '2024-01-01T00:00:00Z'
        }
        yield mock_collect

@pytest.fixture
def sample_admin_logs(app, admin_user, test_user):
    """Create sample admin logs for testing"""
    with app.app_context():
        db.session.add(admin_user)
        db.session.add(test_user)
        db.session.commit()
        
        logs = []
        actions = ['CREATE_USER', 'UPDATE_USER', 'DELETE_USER', 'CHANGE_PASSWORD']
        
        for i, action in enumerate(actions):
            log = AdminLog(
                admin_user_id=admin_user.id,
                action=action,
                target_user_id=test_user.id if i < 3 else None,
                details=f'Test {action} action',
                ip_address='192.168.1.1',
                user_agent='Test Agent'
            )
            logs.append(log)
            db.session.add(log)
        
        db.session.commit()
        return logs

@pytest.fixture
def sample_system_metrics(app):
    """Create sample system metrics for testing"""
    with app.app_context():
        metrics = []
        metric_data = [
            ('total_users', 100),
            ('active_users', 85),
            ('admin_users', 5),
            ('login_attempts', 1250),
            ('error_count', 12)
        ]
        
        for name, value in metric_data:
            metric = SystemMetrics(
                metric_name=name,
                metric_value=value,
                metric_data=f'{{"timestamp": "2024-01-01T00:00:00Z"}}'
            )
            metrics.append(metric)
            db.session.add(metric)
        
        db.session.commit()
        return metrics

@pytest.fixture
def clean_database(app):
    """Fixture to ensure clean database state"""
    with app.app_context():
        # Drop all tables
        db.drop_all()
        # Recreate all tables
        db.create_all()
        yield
        # Clean up after test
        db.session.remove()
        db.drop_all()

@pytest.fixture
def mock_database_error():
    """Mock database errors for testing"""
    with patch('flask_app.models.db.session.commit') as mock_commit:
        mock_commit.side_effect = Exception("Database connection error")
        yield mock_commit

@pytest.fixture
def mock_user_query():
    """Mock user query methods for testing"""
    with patch('flask_app.models.User.query') as mock_query:
        yield mock_query

@pytest.fixture
def mock_current_user():
    """Mock current_user for testing"""
    with patch('flask_login.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_admin = False
        mock_user.id = 1
        mock_user.username = 'testuser'
        yield mock_user

@pytest.fixture
def mock_current_admin():
    """Mock current_user as admin for testing"""
    with patch('flask_login.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.id = 1
        mock_user.username = 'admin'
        yield mock_user

@pytest.fixture
def mock_request():
    """Mock Flask request for testing"""
    with patch('flask.request') as mock_req:
        mock_req.remote_addr = '192.168.1.1'
        mock_req.headers = {'User-Agent': 'Test Browser'}
        yield mock_req

@pytest.fixture
def mock_flash():
    """Mock Flask flash messages for testing"""
    with patch('flask.flash') as mock_flash:
        yield mock_flash

@pytest.fixture
def mock_redirect():
    """Mock Flask redirect for testing"""
    with patch('flask.redirect') as mock_redirect:
        yield mock_redirect

@pytest.fixture
def mock_render_template():
    """Mock Flask render_template for testing"""
    with patch('flask.render_template') as mock_render:
        mock_render.return_value = 'Mocked template content'
        yield mock_render

# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )

def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers"""
    for item in items:
        # Add slow marker to integration tests
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.slow)
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.unit)
