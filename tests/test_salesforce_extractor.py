from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests

from flask_app.importer.adapters.salesforce import extractor
from flask_app.importer.adapters.salesforce.extractor import (
    SalesforceBatch,
    SalesforceExtractor,
    build_contacts_soql,
    build_sessions_soql,
)


class FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, text: str = "", headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.headers = headers or {}
        self.ok = status_code < 400  # Add 'ok' attribute for requests compatibility

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self):
        return self._json_data


class FakeSession:
    def __init__(self, validate_soql=False):
        self.post_calls = []
        self.get_calls = []
        self.state_calls = 0
        self.result_calls = 0
        self.validate_soql = validate_soql
        # Known invalid fields that would cause 400 errors in real Salesforce
        self.invalid_fields = [
            "npe01__Home_Street__c",
            "npe01__Home_City__c",
            "npe01__Home_State__c",
            "npe01__Home_Postal_Code__c",
            "npe01__Home_Country__c",
            "npe01__Work_Street__c",
            "npe01__Work_City__c",
            "npe01__Work_State__c",
            "npe01__Work_Postal_Code__c",
            "npe01__Work_Country__c",
            "npe01__Other_Street__c",
            "npe01__Other_City__c",
            "npe01__Other_State__c",
            "npe01__Other_Postal_Code__c",
            "npe01__Other_Country__c",
            "npe01__Primary_Address_Type__c",
            "npe01__Secondary_Address_Type__c",
        ]

    def post(self, url, headers=None, json=None):
        self.post_calls.append((url, headers, json))

        # Validate SOQL query if enabled
        if self.validate_soql and json and "query" in json:
            soql = json["query"]
            for invalid_field in self.invalid_fields:
                if invalid_field in soql:
                    # Simulate Salesforce API error for invalid fields
                    error_response = FakeResponse(
                        status_code=400,
                        json_data=[
                            {
                                "errorCode": "API_ERROR",
                                "message": (
                                    f"\nERROR at Row:1:Column:871\n"
                                    f"No such column '{invalid_field}' on entity 'Contact'."
                                ),
                            }
                        ],
                    )
                    return error_response

        return FakeResponse(json_data={"id": "JOB123", "state": "UploadComplete"})

    def get(self, url, headers=None, params=None):
        self.get_calls.append((url, headers, params))
        if url.endswith("/jobs/query/JOB123"):
            self.state_calls += 1
            if self.state_calls < 2:
                return FakeResponse(json_data={"state": "UploadComplete"})
            return FakeResponse(json_data={"state": "JobComplete"})
        if url.endswith("/jobs/query/JOB123/results"):
            self.result_calls += 1
            csv_rows = [
                "Id,FirstName,SystemModstamp",
                "1,Ada,2024-01-01T00:00:00.000Z",
                "2,Grace,2024-01-02T00:00:00.000Z",
                "3,Katherine,2024-01-03T00:00:00.000Z",
            ]
            return FakeResponse(
                text="\n".join(csv_rows) + "\n",
                headers={"Sforce-Locator": "null"},
            )
        raise AssertionError(f"Unexpected GET url {url}")


def test_build_contacts_soql_without_watermark():
    # Without watermark but with volunteer filter (default)
    soql = build_contacts_soql()
    assert soql.startswith("SELECT Id, AccountId, FirstName")
    assert "FROM Contact" in soql
    assert "WHERE" in soql  # Volunteer filter is always applied by default
    assert "Contact_Type__c" in soql
    assert soql.endswith("ORDER BY SystemModstamp ASC")

    # Without watermark and without volunteer filter
    soql_no_filter = build_contacts_soql(filter_volunteers=False)
    assert soql_no_filter.startswith("SELECT Id, AccountId, FirstName")
    assert "FROM Contact" in soql_no_filter
    assert "WHERE" not in soql_no_filter
    assert soql_no_filter.endswith("ORDER BY SystemModstamp ASC")


def test_build_contacts_soql_with_watermark_and_limit():
    modstamp = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    soql = build_contacts_soql(last_modstamp=modstamp, limit=500)
    assert "SystemModstamp > 2024-01-01T09:30:00.000Z" in soql
    assert soql.endswith("LIMIT 500")


def test_salesforce_extractor_streams_batches(monkeypatch):
    monkeypatch.setattr(
        extractor,
        "ensure_salesforce_adapter_ready",
        lambda **_: None,
    )
    fake_session = FakeSession()
    fake_client = SimpleNamespace(
        session=fake_session,
        sf_instance="example.my.salesforce.com",
        session_id="abc123",
    )
    extractor_instance = SalesforceExtractor(
        client=fake_client,
        batch_size=2,
        poll_interval=0,
        poll_timeout=10,
        sleep_fn=lambda *_: None,
    )
    batches = list(extractor_instance.extract_batches("SELECT Id FROM Contact"))
    assert len(batches) == 2
    assert isinstance(batches[0], SalesforceBatch)
    assert batches[0].records[0]["FirstName"] == "Ada"
    assert batches[0].locator is None
    assert len(batches[0].records) == 2
    assert len(batches[1].records) == 1


def test_build_contacts_soql_validates_field_list():
    """Test that the SOQL query includes all fields from DEFAULT_CONTACT_FIELDS."""
    from flask_app.importer.adapters.salesforce.extractor import DEFAULT_CONTACT_FIELDS

    soql = build_contacts_soql()

    # Verify all expected fields are in the query
    # This is a basic sanity check - actual field validation happens at Salesforce API level
    for field in DEFAULT_CONTACT_FIELDS:
        # Skip fields that might be in WHERE clause or ORDER BY
        if field in ("SystemModstamp", "LastModifiedDate", "Contact_Type__c"):
            continue
        assert field in soql, f"Field {field} from DEFAULT_CONTACT_FIELDS not found in SOQL query"


def test_salesforce_extractor_validates_invalid_fields(monkeypatch):
    """Test that extractor would fail if SOQL contains invalid fields."""
    from flask_app.importer.adapters.salesforce.extractor import DEFAULT_CONTACT_FIELDS

    # Known invalid NPSP address fields that don't exist in this Salesforce instance
    INVALID_FIELDS = [
        "npe01__Home_Street__c",
        "npe01__Home_City__c",
        "npe01__Work_Street__c",
        "npe01__Other_Street__c",
        "npe01__Primary_Address_Type__c",
    ]

    # Verify invalid fields are NOT in DEFAULT_CONTACT_FIELDS
    for invalid_field in INVALID_FIELDS:
        assert invalid_field not in DEFAULT_CONTACT_FIELDS, (
            f"Invalid field {invalid_field} found in DEFAULT_CONTACT_FIELDS. "
            f"This field doesn't exist in Salesforce and would cause a 400 error."
        )

    # Verify the SOQL query doesn't contain invalid fields
    soql = build_contacts_soql()
    for invalid_field in INVALID_FIELDS:
        assert invalid_field not in soql, (
            f"Invalid field {invalid_field} found in SOQL query. " f"This would cause a 400 error from Salesforce API."
        )


def test_salesforce_extractor_fails_with_invalid_fields(monkeypatch):
    """Test that extractor raises error when SOQL contains invalid fields (simulated)."""
    monkeypatch.setattr(
        extractor,
        "ensure_salesforce_adapter_ready",
        lambda **_: None,
    )

    # Create a session that validates SOQL and rejects invalid fields
    fake_session = FakeSession(validate_soql=True)
    fake_client = SimpleNamespace(
        session=fake_session,
        sf_instance="example.my.salesforce.com",
        session_id="abc123",
    )
    extractor_instance = SalesforceExtractor(
        client=fake_client,
        batch_size=2,
        poll_interval=0,
        poll_timeout=10,
        sleep_fn=lambda *_: None,
    )

    # Test with invalid field - should raise HTTPError when creating job
    invalid_soql = "SELECT Id, npe01__Home_Street__c FROM Contact"
    with pytest.raises(requests.HTTPError, match="400"):
        list(extractor_instance.extract_batches(invalid_soql))

    # Verify the error was caught at job creation (not later)
    assert len(fake_session.post_calls) == 1
    assert fake_session.post_calls[0][1] is not None  # headers were passed


def test_build_sessions_soql_without_watermark():
    """Test that build_sessions_soql generates correct SOQL query."""
    soql = build_sessions_soql()
    assert soql.startswith("SELECT Id, Name, Session_Type__c")
    assert "FROM Session__c" in soql
    assert "WHERE" in soql
    assert "Session_Status__c != 'Draft'" in soql
    assert "Session_Type__c != 'Connector Session'" in soql
    assert soql.endswith("ORDER BY Start_Date_and_Time__c DESC")


def test_build_sessions_soql_with_watermark_and_limit():
    """Test that build_sessions_soql includes watermark and limit."""
    modstamp = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    soql = build_sessions_soql(last_modstamp=modstamp, limit=500)
    assert "SystemModstamp > 2024-01-01T09:30:00.000Z" in soql
    assert soql.endswith("LIMIT 500")


def test_build_sessions_soql_validates_field_list():
    """Test that the SOQL query includes all fields from DEFAULT_SESSION_FIELDS."""
    from flask_app.importer.adapters.salesforce.extractor import DEFAULT_SESSION_FIELDS

    soql = build_sessions_soql()

    # Verify all expected fields are in the query
    for field in DEFAULT_SESSION_FIELDS:
        # Skip fields that might be in WHERE clause or ORDER BY
        if field in (
            "SystemModstamp",
            "LastModifiedDate",
            "Session_Status__c",
            "Session_Type__c",
            "Start_Date_and_Time__c",
        ):
            continue
        assert field in soql, f"Field {field} from DEFAULT_SESSION_FIELDS not found in SOQL query"
