"""Organization Modal Functionality Tests

This module contains tests for the organization creation modal functionality.
Note: Full modal UI testing (opening/closing) would require Selenium/Playwright.
These tests focus on API endpoints and HTML structure.
"""

import pytest
from werkzeug.security import generate_password_hash

from flask_app.models import Organization, User, db


class TestOrganizationModalStructure:
    """Test that organization modal structure exists in HTML"""

    def test_create_org_modal_structure_exists(self, client, super_admin_user, app):
        """Verify create organization modal structure exists in create user page"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that modal structure exists
            assert "createOrgModal" in html or "create-org-modal" in html.lower()
            assert "modal" in html.lower()

    def test_create_org_modal_form_fields_present(self, client, super_admin_user, app):
        """Verify modal form fields are present in HTML"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            response = client.get("/admin/users/create")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            # Check that modal form fields exist
            assert "newOrgName" in html or "organization name" in html.lower()
            assert "newOrgDescription" in html or "description" in html.lower()


class TestOrganizationModalAPI:
    """Test organization creation via modal API endpoint"""

    def test_create_org_via_modal_api(self, client, super_admin_user, app):
        """Test creating organization via API endpoint (used by modal)"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            # Create organization via API (as modal would)
            response = client.post(
                "/api/organizations/create",
                json={"name": "Modal Test Org", "description": "Created via modal API"},
                content_type="application/json",
            )
            assert response.status_code == 200
            assert response.is_json
            data = response.get_json()
            assert data["success"] is True
            assert "organization" in data
            assert data["organization"]["name"] == "Modal Test Org"

            # Verify organization was created in database
            org = Organization.query.filter_by(slug="modal-test-org").first()
            assert org is not None
            assert org.name == "Modal Test Org"

    def test_organization_auto_selected_after_creation(self, client, super_admin_user, app):
        """Test that organization can be retrieved after creation (for auto-selection)"""
        with app.app_context():
            super_admin_user.password_hash = generate_password_hash("superpass123")
            db.session.add(super_admin_user)
            db.session.commit()

            client.post("/login", data={"username": "superadmin", "password": "superpass123"})

            # Create organization via API
            response = client.post(
                "/api/organizations/create",
                json={"name": "Auto Select Org"},
                content_type="application/json",
            )
            assert response.status_code == 200
            data = response.get_json()
            org_id = data["organization"]["id"]

            # Verify organization can be retrieved (for auto-selection in form)
            org = db.session.get(Organization, org_id)
            assert org is not None
            assert org.name == "Auto Select Org"

            # Verify organization appears in search API (for Select2 dropdown)
            search_response = client.get(f"/api/organizations/search?q=Auto")
            assert search_response.status_code == 200
            search_data = search_response.get_json()
            assert "results" in search_data
            # Organization should be in search results
            org_names = [r["name"] for r in search_data["results"]]
            assert "Auto Select Org" in org_names

