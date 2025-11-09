# conftest.py

import os
import tempfile
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

# Set testing environment BEFORE importing app to prevent database corruption
# This ensures app.py uses TestingConfig when imported
os.environ["FLASK_ENV"] = "testing"

# Now import app and other modules after environment is set
from app import app as flask_app
from config import TestingConfig
from flask_app.models import (
    AdminLog,
    Contact,
    ContactAddress,
    ContactEmail,
    ContactOrganization,
    ContactPhone,
    ContactRole,
    ContactTag,
    EmergencyContact,
    Organization,
    OrganizationFeatureFlag,
    Permission,
    Role,
    RolePermission,
    Student,
    SystemFeatureFlag,
    SystemMetrics,
    Teacher,
    User,
    UserOrganization,
    Volunteer,
    VolunteerAvailability,
    VolunteerHours,
    VolunteerInterest,
    VolunteerSkill,
    db,
)


@pytest.fixture(scope="function")
def app():
    """Create and configure a test Flask application"""
    import uuid

    # Create a unique temporary database file for each test
    db_fd, temp_db = tempfile.mkstemp(suffix=f"_{uuid.uuid4().hex[:8]}.db")

    try:
        # Configure the app for testing with isolated database
        # Set DEBUG=True and SQLALCHEMY_ECHO=True to match development behavior
        # that tests expect, while still using isolated test database
        flask_app.config.update(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{temp_db}",
                "SQLALCHEMY_ECHO": True,  # Enable SQL echo for tests (like development)
                "SECRET_KEY": "test-secret-key-for-testing-only",
                "DEBUG": True,
                "TEMPLATES_AUTO_RELOAD": True,
                "MONITORING_ENABLED": False,
                "ERROR_ALERTING_ENABLED": False,
                "ENABLE_FILE_LOGGING": True,  # Enable file logging for tests
                "ENABLE_CONSOLE_LOGGING": True,  # Enable console logging for tests
                "LOG_LEVEL": "DEBUG",  # Set DEBUG level for tests
                "EMAIL_VALIDATION_CHECK_DELIVERABILITY": False,  # Skip DNS checks in tests
                "IMPORTER_ENABLED": False,
                "IMPORTER_ADAPTERS": (),
                "IMPORTER_WORKER_ENABLED": False,
            }
        )
        flask_app.jinja_env.auto_reload = True  # Ensure template recompilation during tests
        flask_app.jinja_env.cache = {}  # Clear any cached templates before running a test

        # Re-initialize logging with updated config to pick up LOG_LEVEL=DEBUG
        from flask_app.utils.logging_config import setup_logging

        setup_logging(flask_app)

        with flask_app.app_context():
            flask_app.jinja_env.cache = {}  # Clear template cache inside app context as well
            # Drop any existing tables to ensure clean state
            db.drop_all()
            # Create all tables
            db.create_all()
            yield flask_app
            # Clean up: remove all data and drop tables
            flask_app.jinja_env.cache = {}  # Ensure cache is clear for subsequent tests
            db.session.remove()
            db.session.close()
            db.drop_all()
    finally:
        # Always close and remove the temporary database file, even on error
        try:
            os.close(db_fd)
        except OSError:
            pass
        try:
            if os.path.exists(temp_db):
                os.unlink(temp_db)
        except OSError:
            pass


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
        username="testuser",
        email="test@example.com",
        password_hash=generate_password_hash("testpass123"),
        first_name="Test",
        last_name="User",
        is_active=True,
        is_super_admin=False,
    )
    return user


@pytest.fixture
def admin_user():
    """Create an admin user fixture"""
    user = User(
        username="admin",
        email="admin@example.com",
        password_hash=generate_password_hash("adminpass123"),
        first_name="Admin",
        last_name="User",
        is_super_admin=True,
    )
    return user


@pytest.fixture
def super_admin_user():
    """Create a super admin user fixture"""
    user = User(
        username="superadmin",
        email="superadmin@example.com",
        password_hash=generate_password_hash("superpass123"),
        first_name="Super",
        last_name="Admin",
        is_super_admin=True,
        is_active=True,
    )
    return user


@pytest.fixture
def test_organization(app):
    """Create a test organization fixture
    Note: app_context fixture is autouse, so app context is already available
    """
    org = Organization(
        name="Test Organization",
        slug="test-organization",
        description="A test organization",
        is_active=True,
    )
    db.session.add(org)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return org


@pytest.fixture
def test_organization_inactive(app):
    """Create an inactive test organization fixture
    Note: app_context fixture is autouse, so app context is already available
    """
    org = Organization(
        name="Inactive Organization",
        slug="inactive-organization",
        description="An inactive organization",
        is_active=False,
    )
    db.session.add(org)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return org


@pytest.fixture
def test_role(app):
    """Create a test role fixture
    Note: app_context fixture is autouse, so app context is already available
    """
    role = Role(
        name="volunteer",
        display_name="Volunteer",
        description="A volunteer role",
        is_system_role=True,
    )
    db.session.add(role)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return role


@pytest.fixture
def test_permission(app):
    """Create a test permission fixture
    Note: app_context fixture is autouse, so app context is already available
    """
    permission = Permission(
        name="view_volunteers",
        display_name="View Volunteers",
        description="Can view volunteers",
        category="volunteers",
    )
    db.session.add(permission)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return permission


@pytest.fixture
def test_role_with_permission(app, test_role, test_permission):
    """Create a role with a permission attached
    Note: app_context fixture is autouse, so app context is already available
    """
    # Use IDs directly
    role_permission = RolePermission(role_id=test_role.id, permission_id=test_permission.id)
    db.session.add(role_permission)
    db.session.commit()
    # Re-query to get role with relationships loaded
    role = db.session.get(Role, test_role.id)
    return role


@pytest.fixture
def test_user_organization(app, test_user, test_organization, test_role):
    """Create a user-organization relationship fixture
    Note: app_context fixture is autouse, so app context is already available
    """
    db.session.add(test_user)
    db.session.commit()

    user_org = UserOrganization(
        user_id=test_user.id,
        organization_id=test_organization.id,
        role_id=test_role.id,
        is_active=True,
    )
    db.session.add(user_org)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return user_org


@pytest.fixture
def test_system_feature_flag(app):
    """Create a test system feature flag fixture
    Note: app_context fixture is autouse, so app context is already available
    """
    flag = SystemFeatureFlag(
        flag_name="test_feature",
        flag_value="true",
        flag_type="boolean",
        description="A test feature flag",
    )
    db.session.add(flag)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return flag


@pytest.fixture
def test_organization_feature_flag(app, test_organization):
    """Create a test organization feature flag fixture
    Note: app_context fixture is autouse, so app context is already available
    """
    flag = OrganizationFeatureFlag(
        organization_id=test_organization.id,
        flag_name="org_test_feature",
        flag_value="true",
        flag_type="boolean",
    )
    db.session.add(flag)
    db.session.commit()
    # Object stays in session since we're in the same app_context as tests
    return flag


@pytest.fixture
def inactive_user():
    """Create an inactive user fixture"""
    user = User(
        username="inactiveuser",
        email="inactive@example.com",
        password_hash=generate_password_hash("userpass123"),
        is_active=False,
    )
    return user


@pytest.fixture
def sample_users(app):
    """Create multiple sample users for testing"""
    users = []
    for i in range(5):
        user = User(
            username=f"sampleuser{i}",
            email=f"sample{i}@example.com",
            password_hash=generate_password_hash("userpass123"),
            first_name=f"Sample{i}",
            last_name="User",
        )
        users.append(user)
    return users


@pytest.fixture
def logged_in_user(client, test_user, app):
    """Fixture that logs in a user and returns the client"""
    with app.app_context():
        db.session.add(test_user)
        db.session.commit()

        client.post("/login", data={"username": "testuser", "password": "testpass123"})

        yield client, test_user


@pytest.fixture
def logged_in_admin(client, admin_user, app):
    """Fixture that logs in an admin user and returns the client"""
    with app.app_context():
        db.session.add(admin_user)
        db.session.commit()

        client.post("/login", data={"username": "admin", "password": "adminpass123"})

        yield client, admin_user


@pytest.fixture
def mock_logger():
    """Mock logger for testing"""
    with patch("flask_app.utils.logging_config.current_app.logger") as mock_log:
        yield mock_log


@pytest.fixture
def mock_email():
    """Mock email sending for testing"""
    with patch("flask_app.utils.error_handler.send_email") as mock_send:
        yield mock_send


@pytest.fixture
def mock_metrics():
    """Mock system metrics for testing"""
    with patch("flask_app.utils.monitoring.collect_system_metrics") as mock_collect:
        mock_collect.return_value = {
            "cpu_percent": 25.5,
            "memory_percent": 60.2,
            "disk_percent": 45.8,
            "timestamp": "2024-01-01T00:00:00Z",
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
        actions = ["CREATE_USER", "UPDATE_USER", "DELETE_USER", "CHANGE_PASSWORD"]

        for i, action in enumerate(actions):
            log = AdminLog(
                admin_user_id=admin_user.id,
                action=action,
                target_user_id=test_user.id if i < 3 else None,
                details=f"Test {action} action",
                ip_address="192.168.1.1",
                user_agent="Test Agent",
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
            ("total_users", 100),
            ("active_users", 85),
            ("admin_users", 5),
            ("login_attempts", 1250),
            ("error_count", 12),
        ]

        for name, value in metric_data:
            metric = SystemMetrics(
                metric_name=name,
                metric_value=value,
                metric_data='{"timestamp": "2024-01-01T00:00:00Z"}',
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
    with patch("flask_app.models.db.session.commit") as mock_commit:
        mock_commit.side_effect = Exception("Database connection error")
        yield mock_commit


@pytest.fixture
def mock_user_query():
    """Mock user query methods for testing"""
    with patch("flask_app.models.User.query") as mock_query:
        yield mock_query


@pytest.fixture
def mock_current_user():
    """Mock current_user for testing"""
    with patch("flask_login.current_user") as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_super_admin = False
        mock_user.id = 1
        mock_user.username = "testuser"
        yield mock_user


@pytest.fixture
def mock_current_admin():
    """Mock current_user as admin for testing"""
    with patch("flask_login.current_user") as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_super_admin = True
        mock_user.id = 1
        mock_user.username = "admin"
        yield mock_user


@pytest.fixture
def mock_request():
    """Mock Flask request for testing"""
    with patch("flask.request") as mock_req:
        mock_req.remote_addr = "192.168.1.1"
        mock_req.headers = {"User-Agent": "Test Browser"}
        yield mock_req


@pytest.fixture
def mock_flash():
    """Mock Flask flash messages for testing"""
    with patch("flask.flash") as mock_flash:
        yield mock_flash


@pytest.fixture
def mock_redirect():
    """Mock Flask redirect for testing"""
    with patch("flask.redirect") as mock_redirect:
        yield mock_redirect


@pytest.fixture
def mock_render_template():
    """Mock Flask render_template for testing"""
    with patch("flask.render_template") as mock_render:
        mock_render.return_value = "Mocked template content"
        yield mock_render


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers and ensure testing environment"""
    # Ensure FLASK_ENV is set to testing before any tests run
    # This is a safety measure in case conftest imports happen in unexpected order
    os.environ["FLASK_ENV"] = "testing"

    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers"""
    for item in items:
        # Add slow marker to integration tests
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.slow)
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.unit)
