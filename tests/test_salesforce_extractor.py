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
    def __init__(self):
        self.post_calls = []
        self.get_calls = []
        self.state_calls = 0
        self.result_calls = 0

    def post(self, url, headers=None, json=None):
        self.post_calls.append((url, headers, json))
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

