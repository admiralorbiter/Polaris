"""Edge Case Tests

This module contains tests for edge cases, null values, empty states, and boundary conditions.
"""

from datetime import datetime, timezone

import pytest
from werkzeug.security import generate_password_hash

from flask_app.models import Organization, Role, User, UserOrganization, db


class TestViewUserEdgeCases:
    """Test edge cases for View User page"""

    def test_view_user_shows_never_for_null_last_login(self, client, super_admin_user, test_user, app):
        """Verify 'Never' is displayed when last_login is null"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            # Explicitly set last_login to None
            test_user.last_login = None
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Last Login:" in html
            assert "Never" in html

    def test_view_user_with_no_organization(self, client, super_admin_user, test_user, app):
        """Verify view user page works for user with no organization"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            # Ensure user has no organizations
            test_user.is_super_admin = False
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Page should still display user information
            assert test_user.username in html

    def test_view_user_with_multiple_organizations(self, client, super_admin_user, test_user, test_role, app):
        """Verify view user page works for user with multiple organizations"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            # Create multiple organizations
            org1 = Organization(name="Org 1", slug="org-1", is_active=True)
            org2 = Organization(name="Org 2", slug="org-2", is_active=True)
            db.session.add_all([org1, org2])
            db.session.commit()

            # Add user to both organizations
            user_org1 = UserOrganization(
                user_id=test_user.id, organization_id=org1.id, role_id=test_role.id, is_active=True
            )
            user_org2 = UserOrganization(
                user_id=test_user.id, organization_id=org2.id, role_id=test_role.id, is_active=True
            )
            db.session.add_all([user_org1, user_org2])
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Should display organization memberships
            assert "Organization Memberships" in html or "organization" in html.lower()


class TestEditUserEdgeCases:
    """Test edge cases for Edit User form"""

    def test_edit_user_with_no_organization(self, client, super_admin_user, test_user, app):
        """Verify edit user form works for user with no organization"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            test_user.is_super_admin = False
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Form should still load
            assert 'name="username"' in html

    def test_edit_user_with_multiple_organizations(self, client, super_admin_user, test_user, test_role, app):
        """Verify edit user form works for user with multiple organizations"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            # Create multiple organizations
            org1 = Organization(name="Multi Org 1", slug="multi-org-1", is_active=True)
            org2 = Organization(name="Multi Org 2", slug="multi-org-2", is_active=True)
            db.session.add_all([org1, org2])
            db.session.commit()

            # Add user to both organizations
            user_org1 = UserOrganization(
                user_id=test_user.id, organization_id=org1.id, role_id=test_role.id, is_active=True
            )
            user_org2 = UserOrganization(
                user_id=test_user.id, organization_id=org2.id, role_id=test_role.id, is_active=True
            )
            db.session.add_all([user_org1, user_org2])
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Form should load
            assert 'name="username"' in html


class TestCreateUserEdgeCases:
    """Test edge cases for Create User form"""

    def test_create_user_with_empty_organization_list(self, client, super_admin_user, app):
        """Verify create user form works when no organizations exist"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            # Don't create any organizations
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Form should still load
            assert 'name="username"' in html
            # Organization field should exist (even if empty)
            assert "organization" in html.lower()

    def test_create_user_form_with_all_roles_created(self, client, super_admin_user, app):
        """Verify create user form works when all system roles exist"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            # Create all 5 system roles
            roles = [
                Role(name="SUPER_ADMIN", display_name="Super Administrator", is_system_role=True),
                Role(name="ORG_ADMIN", display_name="Organization Administrator", is_system_role=True),
                Role(name="COORDINATOR", display_name="Volunteer Coordinator", is_system_role=True),
                Role(name="VOLUNTEER", display_name="Volunteer", is_system_role=True),
                Role(name="VIEWER", display_name="Viewer", is_system_role=True),
            ]
            for role in roles:
                existing = Role.query.filter_by(name=role.name).first()
                if not existing:
                    db.session.add(role)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Form should load and show role dropdown
            assert 'name="role_id"' in html or 'id="role_id"' in html


class TestUserDataEdgeCases:
    """Test edge cases for user data display"""

    def test_view_user_with_minimal_data(self, client, super_admin_user, app):
        """Verify view user page works with minimal user data"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            # Create user with minimal data
            minimal_user = User(
                username="minimal",
                email="minimal@example.com",
                password_hash=generate_password_hash("pass123"),
                first_name=None,
                last_name=None,
            )
            db.session.add(minimal_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{minimal_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Should still display username and email
            assert minimal_user.username in html
            assert minimal_user.email in html
            # Full name should fallback to username
            assert "Full Name:" in html

    def test_edit_user_with_null_names(self, client, super_admin_user, app):
        """Verify edit user form works when first/last names are null"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            user = User(
                username="noname",
                email="noname@example.com",
                password_hash=generate_password_hash("pass123"),
                first_name=None,
                last_name=None,
            )
            db.session.add(user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Form should load with empty name fields
            assert 'name="first_name"' in html
            assert 'name="last_name"' in html

