import pytest
from flask import g, session

from flask_app.middleware.org_context import init_org_context_middleware
from flask_app.models import Organization, Role, User, UserOrganization, db
from flask_app.utils.permissions import get_current_organization


class TestOrganizationContextMiddleware:
    """Test organization context middleware"""

    def test_set_organization_from_org_id_param(self, client, test_user, test_organization, app):
        """Test setting organization from org_id URL parameter"""
        with app.app_context():
            # Store org attributes to avoid detached instance
            org_id = test_organization.id
            org_slug = test_organization.slug
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get(f"/?org_id={org_id}")
            assert response.status_code == 200

            # Check session
            with client.session_transaction() as sess:
                assert sess.get("current_organization_id") == org_id
                assert sess.get("current_organization_slug") == org_slug

    def test_set_organization_from_org_slug_param(self, client, test_user, test_organization, app):
        """Test setting organization from org_slug URL parameter"""
        with app.app_context():
            # Store org attributes to avoid detached instance
            org_id = test_organization.id
            org_slug = test_organization.slug
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get(f"/?org_slug={org_slug}")
            assert response.status_code == 200

            with client.session_transaction() as sess:
                assert sess.get("current_organization_id") == org_id

    def test_set_organization_from_session(self, client, test_user, test_organization, app):
        """Test setting organization from session"""
        with app.app_context():
            # Store org attributes to avoid detached instance
            org_id = test_organization.id
            org_slug = test_organization.slug
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            # Set in session
            with client.session_transaction() as sess:
                sess["current_organization_id"] = org_id
                sess["current_organization_slug"] = org_slug

            response = client.get("/")
            assert response.status_code == 200

    def test_auto_select_single_organization(
        self, client, test_user, test_organization, test_role, app
    ):
        """Test auto-selecting organization when user has only one"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            db.session.add(test_user)
            db.session.commit()

            # Add user to organization
            user_org = UserOrganization(
                user_id=test_user.id, organization_id=org_id, role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get("/")
            assert response.status_code == 200

            with client.session_transaction() as sess:
                assert sess.get("current_organization_id") == org_id

    def test_handles_inactive_organization(
        self, client, test_user, test_organization_inactive, app
    ):
        """Test middleware handles inactive organizations"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization_inactive.id
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get(f"/?org_id={org_id}")
            assert response.status_code == 200

            # Should not set inactive organization
            with client.session_transaction() as sess:
                assert sess.get("current_organization_id") != org_id

    def test_handles_nonexistent_organization(self, client, test_user, app):
        """Test middleware handles non-existent organizations"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get("/?org_id=99999")
            assert response.status_code == 200

            with client.session_transaction() as sess:
                assert sess.get("current_organization_id") is None

    def test_handles_invalid_org_id(self, client, test_user, app):
        """Test middleware handles invalid organization ID"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "testuser", "password": "testpass123"})

            response = client.get("/?org_id=invalid")
            assert response.status_code == 200  # Should not crash

    def test_skips_static_files(self, client, app):
        """Test middleware skips static files"""
        with app.app_context():
            # Should not set organization context for static files
            response = client.get("/static/css/style.css")
            # Should either serve file or 404, but not crash
            assert response.status_code in [200, 404]

    def test_skips_login_route(self, client, app):
        """Test middleware skips login route"""
        with app.app_context():
            response = client.get("/login")
            assert response.status_code == 200
            # Should not set organization context
