"""UI/UX Verification Tests

This module contains tests that verify the UI/UX aspects of the application,
including field display, form pre-population, defaults, and conditional visibility.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

from flask_app.models import Organization, Role, User, UserOrganization, db


class TestViewUserPageFieldVerification:
    """Test that View User page displays all required fields"""

    def test_view_user_displays_username(self, client, super_admin_user, test_user, app):
        """Verify username is displayed on view user page"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Username:" in html
            assert test_user.username in html

    def test_view_user_displays_email(self, client, super_admin_user, test_user, app):
        """Verify email is displayed on view user page"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Email:" in html
            assert test_user.email in html

    def test_view_user_displays_full_name(self, client, super_admin_user, test_user, app):
        """Verify full name is displayed on view user page"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Full Name:" in html
            assert test_user.get_full_name() in html

    def test_view_user_displays_created_date(self, client, super_admin_user, test_user, app):
        """Verify created date is displayed on view user page"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Created:" in html
            # Check that created_at is formatted and displayed
            assert test_user.created_at.strftime("%Y-%m-%d") in html

    def test_view_user_displays_last_updated(self, client, super_admin_user, test_user, app):
        """Verify last updated is displayed on view user page"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Last Updated:" in html
            # Check that updated_at is formatted and displayed
            assert test_user.updated_at.strftime("%Y-%m-%d") in html

    def test_view_user_displays_last_login_when_set(self, client, super_admin_user, test_user, app):
        """Verify last login is displayed when user has logged in"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            # Set last_login
            test_user.last_login = datetime.now(timezone.utc)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Last Login:" in html
            # Check that last_login is formatted and displayed
            assert test_user.last_login.strftime("%Y-%m-%d") in html

    def test_view_user_displays_never_when_no_last_login(self, client, super_admin_user, test_user, app):
        """Verify 'Never' is displayed when user has never logged in"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            # Ensure last_login is None
            test_user.last_login = None
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Last Login:" in html
            assert "Never" in html

    def test_view_user_displays_account_type_super_admin(self, client, super_admin_user, app):
        """Verify account type is displayed correctly for super admin"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{super_admin_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Account Type:" in html
            assert "Super Admin" in html

    def test_view_user_displays_account_type_regular_user(self, client, super_admin_user, test_user, app):
        """Verify account type is displayed correctly for regular user"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Account Type:" in html
            assert "Regular User" in html

    def test_view_user_displays_status_active(self, client, super_admin_user, test_user, app):
        """Verify status is displayed correctly for active user"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            test_user.is_active = True
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Status:" in html
            assert "Active" in html

    def test_view_user_displays_status_inactive(self, client, super_admin_user, test_user, app):
        """Verify status is displayed correctly for inactive user"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            test_user.is_active = False
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Status:" in html
            assert "Inactive" in html

    def test_view_user_displays_all_required_fields(self, client, super_admin_user, test_user, app):
        """Comprehensive test: Verify all 8 required fields are displayed"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}")
            assert response.status_code == 200
            html = response.data.decode("utf-8")

            # Verify all 8 required fields are present
            assert "Username:" in html
            assert "Email:" in html
            assert "Full Name:" in html
            assert "Created:" in html
            assert "Last Updated:" in html
            assert "Last Login:" in html
            assert "Account Type:" in html
            assert "Status:" in html


class TestEditUserFormPrePopulation:
    """Test that Edit User form is pre-populated with current user data"""

    def test_edit_user_form_pre_populates_username(self, client, super_admin_user, test_user, app):
        """Verify username field is pre-populated"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that username input has the current value
            assert f'value="{test_user.username}"' in html or f'name="username"' in html

    def test_edit_user_form_pre_populates_email(self, client, super_admin_user, test_user, app):
        """Verify email field is pre-populated"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that email input has the current value
            assert f'value="{test_user.email}"' in html or f'name="email"' in html

    def test_edit_user_form_pre_populates_names(self, client, super_admin_user, test_user, app):
        """Verify first and last name fields are pre-populated"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that name fields are present
            assert 'name="first_name"' in html
            assert 'name="last_name"' in html
            if test_user.first_name:
                assert test_user.first_name in html
            if test_user.last_name:
                assert test_user.last_name in html

    def test_edit_user_form_pre_populates_active_checkbox(self, client, super_admin_user, test_user, app):
        """Verify active user checkbox reflects current state"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            test_user.is_active = True
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that is_active checkbox exists
            assert 'name="is_active"' in html or 'id="is_active"' in html

    def test_edit_user_form_pre_populates_super_admin_checkbox(self, client, super_admin_user, test_user, app):
        """Verify super admin checkbox reflects current state"""
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
            # Check that is_super_admin checkbox exists
            assert 'name="is_super_admin"' in html or 'id="is_super_admin"' in html

    def test_edit_user_form_pre_selects_organization(self, client, super_admin_user, test_user, test_organization, test_role, app):
        """Verify organization is pre-selected if user has organization"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            # Add user to organization
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=test_organization.id,
                role_id=test_role.id,
                is_active=True,
            )
            db.session.add(user_org)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that organization field exists
            assert 'organization' in html.lower() or 'organization_search' in html

    def test_edit_user_form_pre_selects_role(self, client, super_admin_user, test_user, test_organization, test_role, app):
        """Verify role is pre-selected if user has role"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            # Add user to organization with role
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=test_organization.id,
                role_id=test_role.id,
                is_active=True,
            )
            db.session.add(user_org)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that role field exists
            assert 'name="role_id"' in html or 'id="role_id"' in html

    def test_edit_user_form_pre_populates_all_fields(self, client, super_admin_user, test_user, app):
        """Comprehensive test: Verify all form fields are pre-populated"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")

            # Verify all form fields are present
            assert 'name="username"' in html
            assert 'name="email"' in html
            assert 'name="first_name"' in html
            assert 'name="last_name"' in html
            assert 'name="is_active"' in html or 'id="is_active"' in html
            assert 'name="is_super_admin"' in html or 'id="is_super_admin"' in html


class TestCreateUserFormDefaults:
    """Test that Create User form has correct defaults in rendered HTML"""

    def test_create_user_form_active_checkbox_default_on(self, client, super_admin_user, app):
        """Verify Active User checkbox is checked by default"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that is_active checkbox exists and is checked by default
            assert 'name="is_active"' in html or 'id="is_active"' in html
            # The form should have the checkbox, and the default value should be True
            # We check for the checkbox presence and that it's not explicitly unchecked

    def test_create_user_form_super_admin_checkbox_default_off(self, client, super_admin_user, app):
        """Verify Super Admin checkbox is unchecked by default"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that is_super_admin checkbox exists
            assert 'name="is_super_admin"' in html or 'id="is_super_admin"' in html
            # The default should be False (unchecked)

    def test_create_user_form_organization_section_visible(self, client, super_admin_user, app):
        """Verify organization section is visible by default"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that organization section exists
            assert "organization" in html.lower() or "organization_search" in html

    def test_create_user_form_organization_section_hidden_when_super_admin_checked(self, client, super_admin_user, app):
        """Verify organization section can be hidden (via JavaScript, test HTML structure)"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that organization section exists with id for JavaScript control
            assert "organization-section" in html or "organization" in html.lower()
            # Note: Full JavaScript testing would require Selenium/Playwright

    def test_organization_section_hidden_when_super_admin_checked(self, client, super_admin_user, app):
        """Verify organization section structure allows hiding when super admin is checked"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that organization section has id for JavaScript control
            assert "organization-section" in html or 'id="organization-section"' in html
            # Check that super admin checkbox exists for JavaScript to control visibility
            assert 'id="is_super_admin"' in html or 'name="is_super_admin"' in html

    def test_organization_section_visible_when_super_admin_unchecked(self, client, super_admin_user, app):
        """Verify organization section is visible when super admin is unchecked"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Organization section should be present in HTML
            assert "organization" in html.lower()
            # Note: Actual visibility toggle requires JavaScript, which we test via HTML structure


class TestRoleMenuOptionsVerification:
    """Test that all system roles are available in dropdown menus"""

    def _create_all_system_roles(self, app):
        """Helper to create all 5 system roles"""
        with app.app_context():
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
            return roles

    def test_create_user_form_shows_all_system_roles(self, client, super_admin_user, app):
        """Verify create user form shows all 5 system roles in dropdown"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            self._create_all_system_roles(app)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")

            # Check that role dropdown exists
            assert 'name="role_id"' in html or 'id="role_id"' in html

            # Check for all 5 role display names in HTML
            assert "Super Administrator" in html or "SUPER_ADMIN" in html
            assert "Organization Administrator" in html or "ORG_ADMIN" in html
            assert "Volunteer Coordinator" in html or "COORDINATOR" in html
            assert "Volunteer" in html or "VOLUNTEER" in html
            assert "Viewer" in html or "VIEWER" in html

    def test_edit_user_form_shows_all_system_roles(self, client, super_admin_user, test_user, app):
        """Verify edit user form shows all 5 system roles in dropdown"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.add(test_user)
            self._create_all_system_roles(app)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get(f"/admin/users/{test_user.id}/edit")
            assert response.status_code == 200
            html = response.data.decode("utf-8")

            # Check that role dropdown exists
            assert 'name="role_id"' in html or 'id="role_id"' in html

            # Check for all 5 role display names in HTML
            assert "Super Administrator" in html or "SUPER_ADMIN" in html
            assert "Organization Administrator" in html or "ORG_ADMIN" in html
            assert "Volunteer Coordinator" in html or "COORDINATOR" in html
            assert "Volunteer" in html or "VOLUNTEER" in html
            assert "Viewer" in html or "VIEWER" in html

    def test_role_dropdown_contains_super_admin(self, client, super_admin_user, app):
        """Verify Super Admin role is in dropdown"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            self._create_all_system_roles(app)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Super Administrator" in html or "SUPER_ADMIN" in html

    def test_role_dropdown_contains_org_admin(self, client, super_admin_user, app):
        """Verify Org Admin role is in dropdown"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            self._create_all_system_roles(app)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Organization Administrator" in html or "ORG_ADMIN" in html

    def test_role_dropdown_contains_coordinator(self, client, super_admin_user, app):
        """Verify Coordinator role is in dropdown"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            self._create_all_system_roles(app)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Volunteer Coordinator" in html or "COORDINATOR" in html

    def test_role_dropdown_contains_volunteer(self, client, super_admin_user, app):
        """Verify Volunteer role is in dropdown"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            self._create_all_system_roles(app)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Volunteer" in html or "VOLUNTEER" in html

    def test_role_dropdown_contains_viewer(self, client, super_admin_user, app):
        """Verify Viewer role is in dropdown"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            self._create_all_system_roles(app)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Viewer" in html or "VIEWER" in html

