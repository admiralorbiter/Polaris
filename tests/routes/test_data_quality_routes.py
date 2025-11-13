"""Tests for data quality dashboard routes"""

import json
from unittest.mock import patch

import pytest

from flask_app.models import AdminLog, Contact, ContactEmail, Organization, SystemFeatureFlag, User, db
from flask_app.services.data_quality_field_config_service import DataQualityFieldConfigService


@pytest.fixture
def sample_contacts_for_dashboard(app, test_organization):
    """Create sample contacts for dashboard testing"""
    contacts = []
    for i in range(5):
        contact = Contact(
            first_name=f"Contact{i}",
            last_name="Test",
            organization_id=test_organization.id if i < 3 else None,
        )
        contacts.append(contact)
        db.session.add(contact)
        db.session.flush()  # Flush to get contact.id

        # Add email to first 3 contacts
        if i < 3:
            email = ContactEmail(
                contact_id=contact.id,
                email=f"contact{i}@example.com",
                email_type="PERSONAL",
            )
            db.session.add(email)

    db.session.commit()
    return contacts


class TestDataQualityRoutes:
    """Tests for data quality dashboard routes"""

    def test_data_quality_dashboard_requires_auth(self, client):
        """Test that data quality dashboard requires authentication"""
        response = client.get("/admin/data-quality")
        assert response.status_code in {302, 401, 403}

    def test_data_quality_dashboard_renders(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test that data quality dashboard renders successfully"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality")
        assert response.status_code == 200
        assert b"Data Quality Dashboard" in response.data
        assert b"Overall Data Quality Health Score" in response.data

    def test_data_quality_metrics_api(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test metrics API endpoint"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/metrics")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "overall_health_score" in data
        assert "total_entities" in data
        assert "entity_metrics" in data
        assert "timestamp" in data
        assert isinstance(data["overall_health_score"], (int, float))
        assert isinstance(data["total_entities"], int)
        assert isinstance(data["entity_metrics"], list)

    def test_data_quality_metrics_api_with_org(self, logged_in_admin, sample_contacts_for_dashboard, test_organization):
        """Test metrics API endpoint with organization filter"""
        client, admin_user = logged_in_admin

        response = client.get(f"/admin/data-quality/api/metrics?organization_id={test_organization.id}")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "overall_health_score" in data
        assert "entity_metrics" in data

    def test_data_quality_entity_metrics_api(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test entity metrics API endpoint"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/entity/contact")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["entity_type"] == "contact"
        assert "total_records" in data
        assert "overall_completeness" in data
        assert "fields" in data
        assert "key_metrics" in data
        assert isinstance(data["fields"], list)

    def test_data_quality_entity_metrics_api_invalid_type(self, logged_in_admin):
        """Test entity metrics API endpoint with invalid entity type"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/entity/invalid_type")
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data
        assert "Invalid entity type" in data["error"]

    def test_data_quality_entity_metrics_api_with_org(
        self, logged_in_admin, sample_contacts_for_dashboard, test_organization
    ):
        """Test entity metrics API endpoint with organization filter"""
        client, admin_user = logged_in_admin

        response = client.get(f"/admin/data-quality/api/entity/contact?organization_id={test_organization.id}")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["entity_type"] == "contact"
        assert data["total_records"] >= 0

    def test_data_quality_export_csv(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test export CSV endpoint"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/export?format=csv")
        assert response.status_code == 200
        assert response.content_type == "text/csv; charset=utf-8"
        assert "Content-Disposition" in response.headers
        assert "attachment" in response.headers["Content-Disposition"]
        assert ".csv" in response.headers["Content-Disposition"]

        # Verify CSV content
        csv_content = response.data.decode("utf-8")
        assert "Entity Type" in csv_content
        assert "Field Name" in csv_content
        assert "Completeness Percentage" in csv_content

    def test_data_quality_export_json(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test export JSON endpoint"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/export?format=json")
        assert response.status_code == 200
        assert response.content_type == "application/json"
        assert "Content-Disposition" in response.headers
        assert "attachment" in response.headers["Content-Disposition"]
        assert ".json" in response.headers["Content-Disposition"]

        # Verify JSON content
        data = json.loads(response.data)
        assert "overall_health_score" in data
        assert "entity_metrics" in data

    def test_data_quality_export_invalid_format(self, logged_in_admin):
        """Test export endpoint with invalid format"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/export?format=invalid")
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data
        assert "Format must be 'csv' or 'json'" in data["error"]

    def test_data_quality_dashboard_logs_access(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test that dashboard access is logged"""
        client, admin_user = logged_in_admin

        # Clear existing logs
        AdminLog.query.delete()
        db.session.commit()

        response = client.get("/admin/data-quality")
        assert response.status_code == 200

        # Check that access was logged
        logs = AdminLog.query.filter_by(action="DATA_QUALITY_DASHBOARD_VIEW").all()
        assert len(logs) == 1
        assert logs[0].admin_user_id == admin_user.id

    def test_data_quality_export_logs_access(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test that export access is logged"""
        client, admin_user = logged_in_admin

        # Clear existing logs
        AdminLog.query.delete()
        db.session.commit()

        response = client.get("/admin/data-quality/api/export?format=json")
        assert response.status_code == 200

        # Check that export was logged
        logs = AdminLog.query.filter_by(action="DATA_QUALITY_EXPORT").all()
        assert len(logs) == 1
        assert logs[0].admin_user_id == admin_user.id

    def test_data_quality_metrics_api_error_handling(self, logged_in_admin):
        """Test metrics API error handling"""
        client, admin_user = logged_in_admin

        # Mock an error in the service
        with patch(
            "flask_app.services.data_quality_service.DataQualityService.get_overall_health_score"
        ) as mock_service:
            mock_service.side_effect = Exception("Database error")

            response = client.get("/admin/data-quality/api/metrics")
            assert response.status_code == 500

            data = json.loads(response.data)
            assert "error" in data
            assert "Failed to get data quality metrics" in data["error"]

    def test_data_quality_entity_metrics_api_error_handling(self, logged_in_admin):
        """Test entity metrics API error handling"""
        client, admin_user = logged_in_admin

        # Mock an error in the service
        with patch("flask_app.services.data_quality_service.DataQualityService.get_entity_metrics") as mock_service:
            mock_service.side_effect = Exception("Database error")

            response = client.get("/admin/data-quality/api/entity/contact")
            assert response.status_code == 500

            data = json.loads(response.data)
            assert "error" in data
            assert "Failed to get metrics for contact" in data["error"]

    def test_data_quality_dashboard_exception_handling(self, logged_in_admin):
        """Test dashboard exception handling"""
        client, admin_user = logged_in_admin

        # Mock an error in the route
        with patch("flask_app.routes.admin.get_current_organization") as mock_org:
            mock_org.side_effect = Exception("Organization error")

            response = client.get("/admin/data-quality")
            # Should redirect to admin dashboard on error
            assert response.status_code in {200, 302}

    def test_data_quality_dashboard_super_admin_org_filter(self, logged_in_admin, test_organization):
        """Test that super admin can filter by organization"""
        client, admin_user = logged_in_admin

        # Create another organization
        org2 = Organization(
            name="Test Org 2",
            slug="test-org-2",
            is_active=True,
        )
        db.session.add(org2)
        db.session.commit()

        # Super admin should see organization filter
        response = client.get("/admin/data-quality")
        assert response.status_code == 200
        assert b"filter-organization" in response.data or b"organization" in response.data.lower()

    def test_data_quality_metrics_api_all_entity_types(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test metrics API returns all entity types"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/metrics")
        assert response.status_code == 200

        data = json.loads(response.data)
        entity_types = [em["entity_type"] for em in data["entity_metrics"]]

        expected_types = ["contact", "volunteer", "student", "teacher", "event", "organization", "user"]
        for expected_type in expected_types:
            assert expected_type in entity_types

    def test_data_quality_entity_metrics_api_all_types(self, logged_in_admin):
        """Test entity metrics API for all entity types"""
        client, admin_user = logged_in_admin

        entity_types = ["contact", "volunteer", "student", "teacher", "event", "organization", "user"]

        for entity_type in entity_types:
            response = client.get(f"/admin/data-quality/api/entity/{entity_type}")
            assert response.status_code == 200

            data = json.loads(response.data)
            assert data["entity_type"] == entity_type
            assert "fields" in data
            assert isinstance(data["fields"], list)

    def test_data_quality_field_config_page_requires_auth(self, client):
        """Test that field configuration page requires authentication"""
        response = client.get("/admin/data-quality/fields")
        assert response.status_code in {302, 401, 403}

    def test_data_quality_field_config_page_renders(self, logged_in_admin):
        """Test that field configuration page renders successfully"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/fields")
        assert response.status_code == 200
        assert b"Field Configuration" in response.data
        assert b"Enable or disable fields" in response.data

    def test_data_quality_field_config_api_get(self, logged_in_admin):
        """Test getting field configuration via API"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/field-config")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "entity_types" in data
        assert "field_definitions" in data
        assert "organization_id" in data

        # Verify all entity types are present
        entity_types = data["entity_types"]
        assert "volunteer" in entity_types
        assert "contact" in entity_types
        assert "student" in entity_types
        assert "teacher" in entity_types
        assert "event" in entity_types
        assert "organization" in entity_types
        assert "user" in entity_types

    def test_data_quality_field_config_api_get_structure(self, logged_in_admin):
        """Test field configuration API response structure"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/field-config")
        assert response.status_code == 200

        data = json.loads(response.data)
        entity_types = data["entity_types"]

        # Check volunteer fields structure
        volunteer_fields = entity_types["volunteer"]
        assert "clearance_status" in volunteer_fields
        assert "enabled" in volunteer_fields["clearance_status"]
        assert "display_name" in volunteer_fields["clearance_status"]
        assert isinstance(volunteer_fields["clearance_status"]["enabled"], bool)
        assert isinstance(volunteer_fields["clearance_status"]["display_name"], str)

    def test_data_quality_field_config_api_update_single_field(self, logged_in_admin):
        """Test updating field configuration for a single field"""
        client, admin_user = logged_in_admin

        # Update a field
        response = client.post(
            "/admin/data-quality/api/field-config",
            json={
                "entity_type": "volunteer",
                "field_name": "title",
                "is_enabled": False,
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True
        assert data["config"]["entity_type"] == "volunteer"
        assert data["config"]["field_name"] == "title"
        assert data["config"]["is_enabled"] is False

        # Verify configuration was updated
        response = client.get("/admin/data-quality/api/field-config")
        data = json.loads(response.data)
        volunteer_fields = data["entity_types"]["volunteer"]
        assert volunteer_fields["title"]["enabled"] is False

    def test_data_quality_field_config_api_update_batch(self, logged_in_admin):
        """Test updating field configuration with batch update"""
        client, admin_user = logged_in_admin

        # Update multiple fields
        response = client.post(
            "/admin/data-quality/api/field-config",
            json={
                "changes": [
                    {
                        "entity_type": "volunteer",
                        "field_name": "title",
                        "is_enabled": False,
                    },
                    {
                        "entity_type": "contact",
                        "field_name": "notes",
                        "is_enabled": False,
                    },
                ],
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True
        assert "updated_fields" in data
        assert len(data["updated_fields"]) == 2

        # Verify configuration was updated
        response = client.get("/admin/data-quality/api/field-config")
        data = json.loads(response.data)
        assert data["entity_types"]["volunteer"]["title"]["enabled"] is False
        assert data["entity_types"]["contact"]["notes"]["enabled"] is False

    def test_data_quality_field_config_api_update_invalid_entity(self, logged_in_admin):
        """Test updating field configuration with invalid entity type"""
        client, admin_user = logged_in_admin

        response = client.post(
            "/admin/data-quality/api/field-config",
            json={
                "entity_type": "invalid_entity",
                "field_name": "field1",
                "is_enabled": False,
            },
            content_type="application/json",
        )
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data

    def test_data_quality_field_config_api_update_invalid_field(self, logged_in_admin):
        """Test updating field configuration with invalid field name"""
        client, admin_user = logged_in_admin

        response = client.post(
            "/admin/data-quality/api/field-config",
            json={
                "entity_type": "volunteer",
                "field_name": "invalid_field",
                "is_enabled": False,
            },
            content_type="application/json",
        )
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data

    def test_data_quality_field_config_api_get_entity_type(self, logged_in_admin):
        """Test getting field configuration for specific entity type"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/field-config/volunteer")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["entity_type"] == "volunteer"
        assert "fields" in data
        assert isinstance(data["fields"], dict)

        # Verify fields structure
        fields = data["fields"]
        assert "clearance_status" in fields
        assert "enabled" in fields["clearance_status"]
        assert "display_name" in fields["clearance_status"]

    def test_data_quality_field_config_api_get_invalid_entity_type(self, logged_in_admin):
        """Test getting field configuration for invalid entity type"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/field-config/invalid_entity")
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data

    def test_data_quality_field_config_api_get_definitions(self, logged_in_admin):
        """Test getting field definitions"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/field-definitions")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "field_definitions" in data
        assert "volunteer" in data["field_definitions"]
        assert "contact" in data["field_definitions"]

    def test_data_quality_field_config_api_get_definitions_specific_entity(self, logged_in_admin):
        """Test getting field definitions for specific entity type"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/field-definitions?entity_type=volunteer")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "field_definitions" in data
        assert "volunteer" in data["field_definitions"]
        assert len(data["field_definitions"]) == 1

    def test_data_quality_field_config_logs_access(self, logged_in_admin):
        """Test that field configuration access is logged"""
        client, admin_user = logged_in_admin

        # Clear existing logs
        AdminLog.query.delete()
        db.session.commit()

        response = client.get("/admin/data-quality/fields")
        assert response.status_code == 200

        # Check that access was logged
        logs = AdminLog.query.filter_by(action="DATA_QUALITY_FIELDS_VIEW").all()
        assert len(logs) == 1
        assert logs[0].admin_user_id == admin_user.id

    def test_data_quality_field_config_update_logs_action(self, logged_in_admin):
        """Test that field configuration updates are logged"""
        client, admin_user = logged_in_admin

        # Clear existing logs
        AdminLog.query.delete()
        db.session.commit()

        response = client.post(
            "/admin/data-quality/api/field-config",
            json={
                "entity_type": "volunteer",
                "field_name": "title",
                "is_enabled": False,
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        # Check that update was logged
        logs = AdminLog.query.filter_by(action="DATA_QUALITY_FIELD_CONFIG_UPDATE").all()
        assert len(logs) == 1
        assert logs[0].admin_user_id == admin_user.id
        assert "title" in logs[0].details

    def test_data_quality_metrics_exclude_disabled_fields(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test that metrics API excludes disabled fields"""
        client, admin_user = logged_in_admin

        # Set disabled fields
        config = {
            "contact": ["notes", "photo_url"],
        }
        DataQualityFieldConfigService.set_disabled_fields(config)

        # Get metrics
        response = client.get("/admin/data-quality/api/entity/contact")
        assert response.status_code == 200

        data = json.loads(response.data)
        field_names = [f["field_name"] for f in data["fields"]]

        # Verify disabled fields are not in the response
        assert "notes" not in field_names
        assert "photo_url" not in field_names

        # Verify enabled fields are still present
        assert "first_name" in field_names
        assert "email" in field_names

    def test_data_quality_overall_metrics_exclude_disabled_fields(
        self, logged_in_admin, sample_contacts_for_dashboard
    ):
        """Test that overall metrics API excludes disabled fields"""
        client, admin_user = logged_in_admin

        # Set disabled fields
        config = {
            "contact": ["notes"],
        }
        DataQualityFieldConfigService.set_disabled_fields(config)

        # Get overall metrics
        response = client.get("/admin/data-quality/api/metrics")
        assert response.status_code == 200

        data = json.loads(response.data)

        # Find contact entity metrics
        contact_metrics = next((em for em in data["entity_metrics"] if em["entity_type"] == "contact"), None)
        if contact_metrics:
            field_names = [f["field_name"] for f in contact_metrics["fields"]]
            assert "notes" not in field_names
