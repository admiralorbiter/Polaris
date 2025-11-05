import pytest
from unittest.mock import patch, MagicMock
from flask import Flask, url_for
from flask_app.models.user import User
from flask_app.models.base import db
from datetime import datetime, timezone
import app as main_app


@pytest.fixture
def app():
    """Use the main app with admin blueprint registered"""
    return main_app.app


@pytest.fixture
def admin_user(app):
    """Create an admin user for testing"""
    with app.app_context():
        # Use a unique username to avoid conflicts
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        user = User(
            username=f'admin_{unique_id}',
            email=f'admin_{unique_id}@test.com',
            password_hash='hashed_password',
            is_admin=True,
            is_active=True
        )
        db.session.add(user)
        db.session.commit()
        # Refresh the user to ensure it's properly attached to the session
        db.session.refresh(user)
        return user


class TestAdminSimple:
    """Simple tests for admin routes to improve coverage"""

    def _login_user(self, client, user):
        """Helper method to login a user"""
        with client.session_transaction() as sess:
            # Get the user ID before the session is closed
            user_id = user.id
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_admin_dashboard_success(self, app, admin_user):
        """Test admin dashboard success case"""
        with app.test_client() as client:
            with app.app_context():
                with patch('flask_login.utils._get_user') as mock_get_user:
                    mock_get_user.return_value = admin_user
                    
                    self._login_user(client, admin_user)
                    response = client.get('/admin')
                    
                    assert response.status_code == 200

    def test_admin_users_success(self, app, admin_user):
        """Test admin users page success case"""
        with app.test_client() as client:
            with app.app_context():
                with patch('flask_login.utils._get_user') as mock_get_user:
                    mock_get_user.return_value = admin_user
                    
                    self._login_user(client, admin_user)
                    response = client.get('/admin/users')
                    
                    assert response.status_code == 200

    def test_admin_logs_success(self, app, admin_user):
        """Test admin logs page success case"""
        with app.test_client() as client:
            with app.app_context():
                with patch('flask_login.utils._get_user') as mock_get_user:
                    mock_get_user.return_value = admin_user
                    
                    self._login_user(client, admin_user)
                    response = client.get('/admin/logs')
                    
                    assert response.status_code == 200

    def test_admin_stats_success(self, app, admin_user):
        """Test admin stats page success case"""
        with app.test_client() as client:
            with app.app_context():
                with patch('flask_login.utils._get_user') as mock_get_user:
                    mock_get_user.return_value = admin_user
                    
                    self._login_user(client, admin_user)
                    response = client.get('/admin/stats')
                    
                    assert response.status_code == 200

    def test_admin_dashboard_exception(self, app, admin_user):
        """Test admin dashboard exception handling"""
        with app.test_client() as client:
            with app.app_context():
                with patch('flask_login.utils._get_user') as mock_get_user:
                    mock_get_user.return_value = admin_user
                    
                    # Mock an exception during dashboard loading
                    with patch('flask_app.routes.admin.User.query') as mock_query:
                        mock_query.count.side_effect = Exception("Database error")
                        self._login_user(client, admin_user)
                        response = client.get('/admin')
                        
                        assert response.status_code == 200
