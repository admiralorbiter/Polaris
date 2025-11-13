# tests/routes/test_data_quality_samples_routes.py
"""
Integration tests for data quality sampling API endpoints
"""

import json

import pytest
from flask import url_for


class TestDataQualitySamplesRoutes:
    """Test data quality samples API routes"""

    def test_get_samples_requires_auth(self, client):
        """Test that samples endpoint requires authentication"""
        response = client.get("/admin/data-quality/api/samples/contact")
        assert response.status_code == 302  # Redirect to login

    def test_get_samples_invalid_entity_type(self, logged_in_admin):
        """Test samples endpoint with invalid entity type"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/samples/invalid")
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_get_samples_valid_entity(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test samples endpoint with valid entity type"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/samples/contact")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "entity_type" in data
        assert "samples" in data
        assert "total_records" in data
        assert data["entity_type"] == "contact"

    def test_get_samples_with_sample_size(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test samples endpoint with custom sample size"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/samples/contact?sample_size=10")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["sample_size"] <= 10

    def test_get_statistics_requires_auth(self, client):
        """Test that statistics endpoint requires authentication"""
        response = client.get("/admin/data-quality/api/statistics/contact")
        assert response.status_code == 302  # Redirect to login

    def test_get_statistics_valid_entity(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test statistics endpoint with valid entity type"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/statistics/contact")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "entity_type" in data
        assert "statistics" in data
        assert data["entity_type"] == "contact"

    def test_get_edge_cases_requires_auth(self, client):
        """Test that edge cases endpoint requires authentication"""
        response = client.get("/admin/data-quality/api/edge-cases/contact")
        assert response.status_code == 302  # Redirect to login

    def test_get_edge_cases_valid_entity(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test edge cases endpoint with valid entity type"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/edge-cases/contact")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "entity_type" in data
        assert "edge_cases" in data
        assert data["entity_type"] == "contact"

    def test_get_edge_cases_with_limit(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test edge cases endpoint with custom limit"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/edge-cases/contact?limit=5")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["edge_cases"]) <= 5

    def test_export_samples_csv(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test export samples as CSV"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/export-samples/contact?format=csv")
        assert response.status_code == 200
        assert response.content_type == "text/csv; charset=utf-8"
        assert "Content-Disposition" in response.headers

    def test_export_samples_json(self, logged_in_admin, sample_contacts_for_dashboard):
        """Test export samples as JSON"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/export-samples/contact?format=json")
        assert response.status_code == 200
        assert response.content_type == "application/json"
        assert "Content-Disposition" in response.headers

    def test_export_samples_invalid_format(self, logged_in_admin):
        """Test export samples with invalid format"""
        client, admin_user = logged_in_admin

        response = client.get("/admin/data-quality/api/export-samples/contact?format=xml")
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
