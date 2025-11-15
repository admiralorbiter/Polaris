"""
Salesforce Bulk API extractor for importer staging.

Implements incremental Contact exports using Bulk API 2.0 with configurable
batch sizing and watermark support.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator, List, Mapping, Sequence

import requests

from flask_app.importer.adapters.salesforce import ensure_salesforce_adapter_ready

DEFAULT_CONTACT_FIELDS: Sequence[str] = (
    "Id",
    "AccountId",
    "FirstName",
    "LastName",
    "MiddleName",
    "Email",
    "npe01__AlternateEmail__c",
    "npe01__HomeEmail__c",
    "npe01__WorkEmail__c",
    "npe01__Preferred_Email__c",
    "HomePhone",
    "MobilePhone",
    "npe01__WorkPhone__c",
    "Phone",
    "npe01__PreferredPhone__c",
    "npsp__Primary_Affiliation__c",
    "Title",
    "Department",
    "Gender__c",
    "Birthdate",
    "Racial_Ethnic_Background__c",
    "Age_Group__c",
    "Highest_Level_of_Educational__c",
    "Contact_Type__c",
    "DoNotCall",
    "npsp__Do_Not_Contact__c",
    "HasOptedOutOfEmail",
    "EmailBouncedDate",
    "Last_Mailchimp_Email_Date__c",
    "Last_Volunteer_Date__c",
    "Last_Email_Message__c",
    "Last_Non_Internal_Email_Activity__c",
    "Last_Activity_Date__c",
    "Volunteer_Skills__c",
    "Volunteer_Skills_Text__c",
    "Volunteer_Interests__c",
    "Number_of_Attended_Volunteer_Sessions__c",
    "First_Volunteer_Date__c",
    "Volunteer_Recruitment_Notes__c",
    "Description",
    "MailingStreet",
    "MailingCity",
    "MailingState",
    "MailingPostalCode",
    "MailingCountry",
    # Note: NPSP address component fields (npe01__Home_Street__c, etc.) don't exist in this Salesforce instance
    # Only standard MailingAddress components are available
    "SystemModstamp",
    "LastModifiedDate",
)

DEFAULT_ACCOUNT_FIELDS: Sequence[str] = (
    "Id",
    "Name",
    "Type",
    "Description",
    "LastActivityDate",
    "SystemModstamp",
    "LastModifiedDate",
)

DEFAULT_AFFILIATION_FIELDS: Sequence[str] = (
    "Id",
    "Name",
    "npe5__Organization__c",
    "npe5__Contact__c",
    "npe5__Role__c",
    "npe5__Primary__c",
    "npe5__Status__c",
    "npe5__StartDate__c",
    "npe5__EndDate__c",
    "SystemModstamp",
    "LastModifiedDate",
    "IsDeleted",
)

DEFAULT_SESSION_FIELDS: Sequence[str] = (
    "Id",
    "Name",
    "Session_Type__c",
    "Format__c",
    "Start_Date_and_Time__c",
    "End_Date_and_Time__c",
    "Session_Status__c",
    "Location_Information__c",
    "Description__c",
    "Cancellation_Reason__c",
    "Non_Scheduled_Students_Count__c",
    "District__c",
    "School__c",
    "Legacy_Skill_Covered_for_the_Session__c",
    "Legacy_Skills_Needed__c",
    "Requested_Skills__c",
    "Additional_Information__c",
    "Total_Requested_Volunteer_Jobs__c",
    "Available_Slots__c",
    "Parent_Account__c",
    "Session_Host__c",
    "SystemModstamp",
    "LastModifiedDate",
)

SALESFORCE_API_VERSION = os.environ.get("SALESFORCE_API_VERSION", "v57.0")


def _format_modstamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_contacts_soql(
    *,
    fields: Sequence[str] | None = None,
    last_modstamp: datetime | None = None,
    limit: int | None = None,
    filter_volunteers: bool | None = None,
) -> str:
    """Construct the SOQL used for incremental Contact exports."""

    field_list = tuple(dict.fromkeys(fields or DEFAULT_CONTACT_FIELDS))
    select_clause = ", ".join(field_list)
    where_clauses: List[str] = []

    # Filter for volunteers only if enabled (default: True)
    # Can be disabled via IMPORTER_SALESFORCE_FILTER_VOLUNTEERS=false if field doesn't exist
    if filter_volunteers is None:
        try:
            from flask import current_app

            filter_volunteers = current_app.config.get("IMPORTER_SALESFORCE_FILTER_VOLUNTEERS", True)
        except RuntimeError:
            # No Flask app context - default to True
            filter_volunteers = True

    if filter_volunteers:
        # Filter: Contact_Type__c = 'Volunteer' OR Contact_Type__c = '' OR Contact_Type__c = null
        # Include null values to match all records where Contact_Type__c is Volunteer, empty string, or null
        where_clauses.append("(Contact_Type__c = 'Volunteer' OR Contact_Type__c = '' OR Contact_Type__c = null)")

    if last_modstamp is not None:
        where_clauses.append(f"SystemModstamp > {_format_modstamp(last_modstamp)}")

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    limit_sql = f" LIMIT {int(limit)}" if limit is not None else ""
    order_sql = " ORDER BY SystemModstamp ASC"
    return f"SELECT {select_clause} FROM Contact{where_sql}{order_sql}{limit_sql}"


def build_accounts_soql(
    *,
    fields: Sequence[str] | None = None,
    last_modstamp: datetime | None = None,
    limit: int | None = None,
) -> str:
    """Construct the SOQL used for incremental Account exports."""

    field_list = tuple(dict.fromkeys(fields or DEFAULT_ACCOUNT_FIELDS))
    select_clause = ", ".join(field_list)
    where_clauses: List[str] = []

    # Filter out Household, School District, and School types as specified
    where_clauses.append("Type NOT IN ('Household', 'School District', 'School')")

    if last_modstamp is not None:
        where_clauses.append(f"SystemModstamp > {_format_modstamp(last_modstamp)}")

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    limit_sql = f" LIMIT {int(limit)}" if limit is not None else ""
    order_sql = " ORDER BY Name ASC"
    return f"SELECT {select_clause} FROM Account{where_sql}{order_sql}{limit_sql}"


def build_affiliations_soql(
    *,
    fields: Sequence[str] | None = None,
    last_modstamp: datetime | None = None,
    limit: int | None = None,
    filter_volunteers: bool | None = None,
) -> str:
    """Construct the SOQL used for incremental Affiliation (npe5__Affiliation__c) exports.

    Args:
        fields: Optional list of fields to select. Defaults to DEFAULT_AFFILIATION_FIELDS.
        last_modstamp: Optional datetime for incremental exports (filters by SystemModstamp > value).
        limit: Optional limit on number of records to return.
        filter_volunteers: If True, only return affiliations for contacts with Contact_Type__c = 'Volunteer'.
                          Defaults to True if not specified (can be disabled via config).
    """

    field_list = tuple(dict.fromkeys(fields or DEFAULT_AFFILIATION_FIELDS))
    select_clause = ", ".join(field_list)
    where_clauses: List[str] = []

    # Filter for volunteer contacts only if enabled (default: True)
    # Can be disabled via IMPORTER_SALESFORCE_FILTER_VOLUNTEERS=false if needed
    if filter_volunteers is None:
        try:
            from flask import current_app

            filter_volunteers = current_app.config.get("IMPORTER_SALESFORCE_FILTER_VOLUNTEERS", True)
        except RuntimeError:
            # No Flask app context - default to True
            filter_volunteers = True

    if filter_volunteers:
        # Filter: Only affiliations where the related contact has Contact_Type__c = 'Volunteer'
        # Using relationship syntax: npe5__Contact__r.Contact_Type__c
        # Also include null/empty to match volunteer contact filter behavior
        where_clauses.append(
            "(npe5__Contact__r.Contact_Type__c = 'Volunteer' "
            "OR npe5__Contact__r.Contact_Type__c = '' "
            "OR npe5__Contact__r.Contact_Type__c = null)"
        )

    if last_modstamp is not None:
        where_clauses.append(f"SystemModstamp > {_format_modstamp(last_modstamp)}")

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    limit_sql = f" LIMIT {int(limit)}" if limit is not None else ""
    order_sql = " ORDER BY SystemModstamp ASC"
    return f"SELECT {select_clause} FROM npe5__Affiliation__c{where_sql}{order_sql}{limit_sql}"


def build_sessions_soql(
    *,
    fields: Sequence[str] | None = None,
    last_modstamp: datetime | None = None,
    limit: int | None = None,
) -> str:
    """Construct the SOQL used for incremental Session__c exports."""

    field_list = tuple(dict.fromkeys(fields or DEFAULT_SESSION_FIELDS))
    select_clause = ", ".join(field_list)
    where_clauses: List[str] = []

    # Filter out Draft status and Connector Session type as specified
    where_clauses.append("Session_Status__c != 'Draft'")
    where_clauses.append("Session_Type__c != 'Connector Session'")

    if last_modstamp is not None:
        where_clauses.append(f"SystemModstamp > {_format_modstamp(last_modstamp)}")

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    limit_sql = f" LIMIT {int(limit)}" if limit is not None else ""
    order_sql = " ORDER BY Start_Date_and_Time__c DESC"
    return f"SELECT {select_clause} FROM Session__c{where_sql}{order_sql}{limit_sql}"


@dataclass(frozen=True)
class SalesforceBatch:
    """Represents a batch of rows returned by the extractor."""

    job_id: str
    sequence: int
    records: List[Mapping[str, str]]
    locator: str | None


class SalesforceExtractorError(RuntimeError):
    """Base error for extractor failures."""


class SalesforceJobFailed(SalesforceExtractorError):
    """Raised when Salesforce reports the job failed or was aborted."""


class SalesforceJobTimeout(SalesforceExtractorError):
    """Raised when waiting for the job exceeds the configured timeout."""


class SalesforceExtractor:
    """Execute Bulk API 2.0 queries and stream results in batches."""

    def __init__(
        self,
        *,
        client,
        batch_size: int = 5000,
        api_version: str = SALESFORCE_API_VERSION,
        poll_interval: float = 5.0,
        poll_timeout: float = 600.0,
        sleep_fn=time.sleep,
        logger: logging.Logger | None = None,
    ) -> None:
        ensure_salesforce_adapter_ready()
        self.client = client
        self.session: requests.Session = getattr(client, "session")
        self.batch_size = max(1, int(batch_size))
        self.api_version = api_version
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.sleep = sleep_fn
        self.logger = logger or logging.getLogger(__name__)
        self.instance_url = f"https://{client.sf_instance}"
        self._auth_headers = {
            "Authorization": f"Bearer {client.session_id}",
            "Sforce-Call-Options": "client=polaris-importer",
        }

    # Public API -----------------------------------------------------------------

    def extract_batches(self, soql: str) -> Iterator[SalesforceBatch]:
        """Execute the SOQL query and yield batches of records."""

        job = self._create_job(soql)
        job_id = job["id"]
        final_state = self._wait_for_completion(job_id)
        if final_state not in {"JobComplete"}:
            raise SalesforceJobFailed(f"Salesforce job {job_id} ended in state {final_state}")
        yield from self._stream_job_results(job_id)

    # Internal helpers -----------------------------------------------------------

    @property
    def _bulk_base_url(self) -> str:
        return f"{self.instance_url}/services/data/{self.api_version}/jobs/query"

    def _create_job(self, soql: str) -> Mapping[str, object]:
        payload = {
            "operation": "query",
            "query": soql,
            "contentType": "CSV",
            "columnDelimiter": "COMMA",
            "lineEnding": "LF",
        }
        response = self.session.post(
            self._bulk_base_url,
            headers={**self._auth_headers, "Content-Type": "application/json"},
            json=payload,
        )
        if not response.ok:
            # Log the actual error response from Salesforce for debugging
            try:
                error_data = response.json()
                error_msg = error_data.get("message") or error_data.get("error") or str(error_data)
                # Log full error details
                self.logger.error(
                    f"Salesforce job creation failed: {error_msg}",
                    extra={
                        "status_code": response.status_code,
                        "error": error_msg,
                        "error_data": error_data,
                        "soql_query": soql,
                    },
                )
                # Also print to console for immediate visibility
                print("\n=== SALESFORCE ERROR ===")
                print(f"Status: {response.status_code}")
                print(f"Error: {error_msg}")
                print(f"Full response: {error_data}")
                print(f"SOQL Query: {soql}")
                print("======================\n")
            except Exception as e:
                error_msg = response.text
                self.logger.error(
                    f"Salesforce job creation failed: {error_msg}",
                    extra={
                        "status_code": response.status_code,
                        "error": error_msg,
                        "soql_query": soql,
                        "parse_error": str(e),
                    },
                )
                print("\n=== SALESFORCE ERROR (could not parse JSON) ===")
                print(f"Status: {response.status_code}")
                print(f"Response text: {error_msg}")
                print(f"SOQL Query: {soql}")
                print("======================\n")
        response.raise_for_status()
        data = response.json()
        self.logger.debug("Salesforce job created", extra={"job_id": data.get("id")})
        return data

    def _wait_for_completion(self, job_id: str) -> str:
        url = f"{self._bulk_base_url}/{job_id}"
        deadline = time.time() + self.poll_timeout
        while True:
            response = self.session.get(url, headers=self._auth_headers)
            response.raise_for_status()
            payload = response.json()
            state = payload.get("state")
            if state in {"JobComplete", "Failed", "Aborted"}:
                return state or "Unknown"
            if time.time() >= deadline:
                raise SalesforceJobTimeout(f"Timed out waiting for job {job_id} to complete.")
            self.sleep(self.poll_interval)

    def _stream_job_results(self, job_id: str) -> Iterator[SalesforceBatch]:
        sequence = 0
        locator: str | None = None
        while True:
            params = {}
            if locator:
                params["locator"] = locator
            response = self.session.get(
                f"{self._bulk_base_url}/{job_id}/results",
                headers={**self._auth_headers, "Accept": "text/csv"},
                params=params,
            )
            response.raise_for_status()
            locator = response.headers.get("Sforce-Locator")
            if locator and locator.lower() in {"null", "none"}:
                locator = None
            csv_buffer = io.StringIO(response.text)
            reader = csv.DictReader(csv_buffer)
            batch_records: List[Mapping[str, str]] = []
            for row in reader:
                batch_records.append(row)
                if len(batch_records) == self.batch_size:
                    sequence += 1
                    yield SalesforceBatch(
                        job_id=job_id, sequence=sequence, records=list(batch_records), locator=locator
                    )
                    batch_records.clear()
            if batch_records:
                sequence += 1
                yield SalesforceBatch(job_id=job_id, sequence=sequence, records=list(batch_records), locator=locator)
            if not locator:
                break


def create_salesforce_client() -> object:
    """Instantiate a Simple Salesforce client using environment credentials."""

    ensure_salesforce_adapter_ready()
    from simple_salesforce import Salesforce

    username = os.environ["SF_USERNAME"]
    password = os.environ["SF_PASSWORD"]
    security_token = os.environ["SF_SECURITY_TOKEN"]

    kwargs: dict[str, object] = {}
    domain = os.environ.get("SF_DOMAIN")
    if domain:
        kwargs["domain"] = domain
    client_id = os.environ.get("SF_CLIENT_ID")
    client_secret = os.environ.get("SF_CLIENT_SECRET")
    if client_id and client_secret:
        kwargs["client_id"] = client_id
        kwargs["client_secret"] = client_secret

    return Salesforce(
        username=username,
        password=password,
        security_token=security_token,
        **kwargs,
    )


def chunk_records(records: Iterable[Mapping[str, str]], chunk_size: int) -> Iterator[List[Mapping[str, str]]]:
    """Utility to group iterable of records into lists of `chunk_size`."""

    chunk: List[Mapping[str, str]] = []
    for record in records:
        chunk.append(record)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
