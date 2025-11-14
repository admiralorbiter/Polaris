"""
Minimal data quality rule engine for volunteer imports (IMP-11).

This module defines lightweight validators that operate on staged volunteer
payloads prior to further pipeline steps. Rules emit structured outcomes that
callers can persist to `dq_violations` or tally for metrics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, MutableMapping, Sequence

from flask_app.importer.adapters import VolunteerCSVRow
from flask_app.models.base import db
from flask_app.models.importer.schema import (
    DataQualitySeverity,
    DataQualityStatus,
    DataQualityViolation,
    StagingOrganization,
    StagingRecordStatus,
    StagingVolunteer,
)


@dataclass(frozen=True)
class DQResult:
    """
    Outcome from evaluating a single data-quality rule against a payload.

    Attributes:
        rule_code: Stable identifier for the rule (e.g., `VOL_CONTACT_REQUIRED`).
        severity: Error, warning, or info (see `DataQualitySeverity`).
        message: Human-friendly summary explaining the violation.
        details: Optional structured payload with extra context for downstream
            consumers (UI, logging, remediation tools).
    """

    rule_code: str
    severity: DataQualitySeverity
    message: str
    details: Mapping[str, object]


@dataclass(frozen=True)
class DQRule:
    """Declarative rule definition used by the minimal DQ engine."""

    code: str
    description: str
    severity: DataQualitySeverity

    def evaluate(self, payload: Mapping[str, object | None]) -> Iterable[DQResult]:
        """Return violations for the provided payload."""
        raise NotImplementedError


_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_E164_REGEX = re.compile(r"^\+[1-9]\d{7,14}$")


def _coerce_str(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


class EmailOrPhoneRule(DQRule):
    """Ensure at least one of email or phone is present."""

    def __init__(self, severity: DataQualitySeverity = DataQualitySeverity.ERROR) -> None:
        super().__init__(
            code="VOL_CONTACT_REQUIRED",
            description="Volunteer should include at least one contact method (email or phone).",
            severity=severity,
        )

    def evaluate(self, payload: Mapping[str, object | None]) -> Iterable[DQResult]:
        email = _coerce_str(payload.get("email") or payload.get("email_normalized"))
        phone = _coerce_str(payload.get("phone") or payload.get("phone_e164"))
        if email or phone:
            return []
        return [
            DQResult(
                rule_code=self.code,
                severity=self.severity,
                message="Row missing both email and phone; at least one contact method is required.",
                details={"fields": ["email", "phone"]},
            )
        ]


class EmailFormatRule(DQRule):
    """Validate email adheres to a basic RFC-like format."""

    def __init__(self) -> None:
        super().__init__(
            code="VOL_EMAIL_FORMAT",
            description="Email must be well-formed (basic RFC compliance).",
            severity=DataQualitySeverity.ERROR,
        )

    def evaluate(self, payload: Mapping[str, object | None]) -> Iterable[DQResult]:
        email = _coerce_str(payload.get("email") or payload.get("email_normalized"))
        if not email:
            return []
        if _EMAIL_REGEX.match(email):
            return []
        return [
            DQResult(
                rule_code=self.code,
                severity=self.severity,
                message="Email is not in a valid format.",
                details={"fields": ["email"], "value": email},
            )
        ]


class PhoneFormatRule(DQRule):
    """Validate phone numbers conform to E.164."""

    def __init__(self) -> None:
        super().__init__(
            code="VOL_PHONE_E164",
            description="Phone numbers must be normalized to E.164.",
            severity=DataQualitySeverity.ERROR,
        )

    def evaluate(self, payload: Mapping[str, object | None]) -> Iterable[DQResult]:
        phone = _coerce_str(payload.get("phone") or payload.get("phone_e164"))
        if not phone:
            return []
        if _E164_REGEX.match(phone):
            return []
        return [
            DQResult(
                rule_code=self.code,
                severity=self.severity,
                message="Phone is not E.164 formatted (+<country><number>).",
                details={"fields": ["phone"], "value": phone},
            )
        ]


def get_minimal_volunteer_rules() -> Sequence[DQRule]:
    """
    Get minimal volunteer DQ rules.
    
    EmailOrPhoneRule is excluded by default (uses metadata flags instead).
    Can be enabled via IMPORTER_WARN_ON_MISSING_CONTACT config.
    """
    from flask import current_app
    
    rules: list[DQRule] = [
        EmailFormatRule(),
        PhoneFormatRule(),
    ]
    
    # Optionally add contact requirement as warning if config enabled
    warn_on_missing_contact = current_app.config.get("IMPORTER_WARN_ON_MISSING_CONTACT", False)
    if warn_on_missing_contact:
        # Create rule with WARNING severity instead of ERROR
        contact_rule = EmailOrPhoneRule(severity=DataQualitySeverity.WARNING)
        rules.append(contact_rule)
    
    return tuple(rules)


MINIMAL_VOLUNTEER_RULES: Sequence[DQRule] = (
    EmailFormatRule(),
    PhoneFormatRule(),
)


def evaluate_rules(
    payload: Mapping[str, object | None], rules: Sequence[DQRule] | None = None
) -> list[DQResult]:
    """
    Evaluate the provided payload against the configured rules.

    Args:
        payload: Canonical volunteer payload (normalized keys expected).
        rules: Optional override list of rules; defaults to minimal IMP-11 rules.

    Returns:
        List of violations (empty when the payload satisfies all rules).
    """

    if rules is None:
        # Use configurable rules function instead of static tuple
        try:
            applicable_rules = get_minimal_volunteer_rules()
        except Exception:
            # Fallback to static rules if config access fails
            applicable_rules = MINIMAL_VOLUNTEER_RULES
    else:
        applicable_rules = rules
    violations: list[DQResult] = []
    for rule in applicable_rules:
        violations.extend(rule.evaluate(payload))
    return violations


def summarize_violations(results: Iterable[DQResult]) -> MutableMapping[str, int]:
    """
    Aggregate violation counts keyed by rule code.

    Helpful for metrics and reporting surfaces. Only counts occurrences; severity
    weighting remains up to the caller.
    """

    summary: MutableMapping[str, int] = {}
    for result in results:
        summary[result.rule_code] = summary.get(result.rule_code, 0) + 1
    return summary


@dataclass
class DQProcessingSummary:
    """Aggregate results from running DQ across staged volunteers."""

    rows_evaluated: int
    rows_validated: int
    rows_quarantined: int
    violations: list[DQResult]
    dry_run: bool

    @property
    def rule_counts(self) -> MutableMapping[str, int]:
        return summarize_violations(self.violations)


def run_minimal_dq(
    import_run,
    *,
    dry_run: bool = False,
    csv_rows: Sequence[VolunteerCSVRow] | None = None,
) -> DQProcessingSummary:
    """
    Evaluate staged volunteer/organization rows for a given import run and persist violations.

    Args:
        import_run: `ImportRun` instance whose staged rows should be evaluated.
        dry_run: If true, no database state is mutated; a summary is still
            returned for diagnostics.
    """
    if dry_run:
        if csv_rows:
            return _run_minimal_dq_dry_run(import_run, csv_rows)
        return _run_minimal_dq_from_staging(import_run)

    session = db.session
    now = datetime.now(timezone.utc)
    rows_evaluated = 0
    rows_validated = 0
    rows_quarantined = 0
    all_violations: list[DQResult] = []

    # Process volunteers
    volunteer_rows = (
        session.query(StagingVolunteer)
        .filter(
            StagingVolunteer.run_id == import_run.id,
            StagingVolunteer.status == StagingRecordStatus.LANDED,
        )
        .order_by(StagingVolunteer.sequence_number)
    )

    for row in volunteer_rows:
        rows_evaluated += 1
        payload = _compose_payload(row)
        violations = list(evaluate_rules(payload))
        # Separate errors (blocking) from warnings (non-blocking)
        error_violations = [v for v in violations if v.severity == DataQualitySeverity.ERROR]
        warning_violations = [v for v in violations if v.severity != DataQualitySeverity.ERROR]
        
        # Only quarantine on ERROR severity violations
        if not error_violations:
            rows_validated += 1
            row.status = StagingRecordStatus.VALIDATED
            row.processed_at = now
            row.last_error = None
        else:
            rows_quarantined += 1
            all_violations.extend(error_violations)
            row.status = StagingRecordStatus.QUARANTINED
            row.last_error = error_violations[0].message
            row.processed_at = now
        
        # Log all violations (both errors and warnings) for tracking
        for violation in violations:
            session.add(
                DataQualityViolation(
                    run_id=import_run.id,
                    staging_volunteer_id=row.id,
                    entity_type="volunteer",
                    record_key=_compose_record_key(row),
                    rule_code=violation.rule_code,
                    severity=violation.severity,
                    status=DataQualityStatus.OPEN,
                    message=violation.message,
                    details_json=dict(violation.details),
                )
            )

    # Process organizations
    org_rows = (
        session.query(StagingOrganization)
        .filter(
            StagingOrganization.run_id == import_run.id,
            StagingOrganization.status == StagingRecordStatus.LANDED,
        )
        .order_by(StagingOrganization.sequence_number)
    )

    for row in org_rows:
        rows_evaluated += 1
        payload = _compose_organization_payload(row)
        violations = list(evaluate_organization_rules(payload))
        # Separate errors (blocking) from warnings (non-blocking)
        error_violations = [v for v in violations if v.severity == DataQualitySeverity.ERROR]
        warning_violations = [v for v in violations if v.severity != DataQualitySeverity.ERROR]
        
        # Only quarantine on ERROR severity violations
        if not error_violations:
            rows_validated += 1
            row.status = StagingRecordStatus.VALIDATED
            row.processed_at = now
            row.last_error = None
        else:
            rows_quarantined += 1
            all_violations.extend(error_violations)
            row.status = StagingRecordStatus.QUARANTINED
            row.last_error = error_violations[0].message
            row.processed_at = now
        
        # Log all violations (both errors and warnings) for tracking
        for violation in violations:
            session.add(
                DataQualityViolation(
                    run_id=import_run.id,
                    staging_organization_id=row.id,
                    entity_type="organization",
                    record_key=_compose_organization_record_key(row),
                    rule_code=violation.rule_code,
                    severity=violation.severity,
                    status=DataQualityStatus.OPEN,
                    message=violation.message,
                    details_json=dict(violation.details),
                )
            )

    summary = DQProcessingSummary(
        rows_evaluated=rows_evaluated,
        rows_validated=rows_validated,
        rows_quarantined=rows_quarantined,
        violations=all_violations,
        dry_run=dry_run,
    )
    _update_dq_counts(import_run, summary)
    return summary


def _compose_payload(row: StagingVolunteer) -> MutableMapping[str, object | None]:
    payload: MutableMapping[str, object | None] = {}
    normalized = row.normalized_json or {}
    raw = row.payload_json or {}

    # Start with raw payload
    payload.update(raw)

    # Email extraction - check raw FIRST before updating normalized
    email_value = None
    if raw.get("Email"):
        email_value = str(raw["Email"]).strip()
        if email_value:  # Only set if non-empty after stripping
            payload["email"] = email_value
            payload["email_normalized"] = email_value
    
    # Phone extraction - check raw FIRST before updating normalized  
    phone_value = None
    if raw.get("Phone"):
        phone_value = str(raw["Phone"]).strip()
        if phone_value:
            payload["phone"] = phone_value
    elif raw.get("MobilePhone"):
        phone_value = str(raw["MobilePhone"]).strip()
        if phone_value:
            payload["phone"] = phone_value
    elif raw.get("HomePhone"):
        phone_value = str(raw["HomePhone"]).strip()
        if phone_value:
            payload["phone"] = phone_value
    
    # NOW update with normalized (this may add nested structures that could overwrite our values)
    payload.update(normalized)
    
    # Preserve nested email/phone structures from normalized data
    # If normalized has a dict structure, keep it (don't flatten to string)
    # The loader will process all email/phone types from the dict
    if isinstance(payload.get("email"), dict):
        # Keep the nested dict structure - don't flatten it
        # The loader will process all email types from the dict
        pass  # Keep the dict as-is
    elif email_value and not payload.get("email"):
        # Only set string email if we don't have a dict and don't have an email yet
        payload["email"] = email_value
        payload["email_normalized"] = email_value
    elif not email_value and "email_normalized" in normalized:
        email_value = str(normalized["email_normalized"]).strip()
        if email_value:
            payload["email"] = email_value
            payload["email_normalized"] = email_value
    elif not email_value and "VOL_EMAIL" in normalized:
        email_value = str(normalized["VOL_EMAIL"]).strip()
        if email_value:
            payload["email"] = email_value
    
    # Preserve nested phone structures from normalized data
    if isinstance(payload.get("phone"), dict):
        # Keep the nested dict structure - don't flatten it
        # The loader will process all phone types from the dict
        pass  # Keep the dict as-is
    elif phone_value and not payload.get("phone"):
        # Only set string phone if we don't have a dict and don't have a phone yet
        payload["phone"] = phone_value
        payload["phone_e164"] = phone_value
    elif not phone_value and "phone_e164" in normalized:
        phone_value = str(normalized["phone_e164"]).strip()
        if phone_value:
            payload["phone"] = phone_value
            payload["phone_e164"] = phone_value
    elif not phone_value and "VOL_PHONE_E164" in normalized:
        phone_value = str(normalized["VOL_PHONE_E164"]).strip()
        if phone_value:
            payload["phone"] = phone_value
            payload["phone_e164"] = phone_value
    elif not phone_value and "VOL_PHONE" in normalized:
        phone_value = str(normalized["VOL_PHONE"]).strip()
        if phone_value:
            payload["phone"] = phone_value

    return payload


def _compose_record_key(row: StagingVolunteer) -> str:
    if row.external_id:
        return str(row.external_id)
    if row.source_record_id:
        return str(row.source_record_id)
    if row.sequence_number is not None:
        return f"seq-{row.sequence_number}"
    return f"row-{row.id}"


def _compose_organization_payload(row: StagingOrganization) -> MutableMapping[str, object | None]:
    payload: MutableMapping[str, object | None] = {}
    normalized = row.normalized_json or {}
    raw = row.payload_json or {}

    # Start with raw payload
    payload.update(raw)
    
    # Name extraction
    name_value = None
    if raw.get("Name"):
        name_value = str(raw["Name"]).strip()
        if name_value:
            payload["name"] = name_value
    
    # Update with normalized
    payload.update(normalized)
    
    # Ensure name is available
    if not payload.get("name") and name_value:
        payload["name"] = name_value
    
    return payload


def _compose_organization_record_key(row: StagingOrganization) -> str:
    if row.external_id:
        return str(row.external_id)
    if row.source_record_id:
        return str(row.source_record_id)
    if row.sequence_number is not None:
        return f"seq-{row.sequence_number}"
    return f"row-{row.id}"


class OrganizationNameRequiredRule(DQRule):
    """Ensure organization name is present."""

    def __init__(self, severity: DataQualitySeverity = DataQualitySeverity.ERROR) -> None:
        super().__init__(
            code="ORG_NAME_REQUIRED",
            description="Organization must include a name.",
            severity=severity,
        )

    def evaluate(self, payload: Mapping[str, object | None]) -> Iterable[DQResult]:
        name = _coerce_str(payload.get("name") or payload.get("Name"))
        if name:
            return []
        return [
            DQResult(
                rule_code=self.code,
                severity=self.severity,
                message="Organization missing required name field.",
                details={"fields": ["name"]},
            )
        ]


def evaluate_organization_rules(payload: Mapping[str, object | None]) -> Iterable[DQResult]:
    """
    Evaluate all applicable organization DQ rules against a payload.

    Returns violations found (empty if payload passes all rules).
    """
    applicable_rules: list[DQRule] = [
        OrganizationNameRequiredRule(),
    ]
    violations: list[DQResult] = []
    for rule in applicable_rules:
        violations.extend(rule.evaluate(payload))
    return violations

def _run_minimal_dq_dry_run(
    import_run,
    csv_rows: Sequence[VolunteerCSVRow],
) -> DQProcessingSummary:
    rows_evaluated = 0
    rows_validated = 0
    rows_quarantined = 0
    all_violations: list[DQResult] = []

    for row in csv_rows:
        rows_evaluated += 1
        payload = _compose_payload_from_csv_row(row)
        violations = list(evaluate_rules(payload))
        if violations:
            rows_quarantined += 1
            all_violations.extend(violations)
        else:
            rows_validated += 1

    summary = DQProcessingSummary(
        rows_evaluated=rows_evaluated,
        rows_validated=rows_validated,
        rows_quarantined=rows_quarantined,
        violations=all_violations,
        dry_run=True,
    )
    _update_dq_counts(import_run, summary)
    return summary


def _run_minimal_dq_from_staging(import_run) -> DQProcessingSummary:
    session = db.session
    rows_evaluated = 0
    rows_validated = 0
    rows_quarantined = 0
    all_violations: list[DQResult] = []

    # Process volunteers
    volunteer_rows = (
        session.query(StagingVolunteer)
        .filter(
            StagingVolunteer.run_id == import_run.id,
            StagingVolunteer.status == StagingRecordStatus.LANDED,
        )
        .order_by(StagingVolunteer.sequence_number)
    )

    for row in volunteer_rows:
        rows_evaluated += 1
        payload = _compose_payload(row)
        violations = list(evaluate_rules(payload))
        if violations:
            rows_quarantined += 1
            all_violations.extend(violations)
        else:
            rows_validated += 1

    # Process organizations
    org_rows = (
        session.query(StagingOrganization)
        .filter(
            StagingOrganization.run_id == import_run.id,
            StagingOrganization.status == StagingRecordStatus.LANDED,
        )
        .order_by(StagingOrganization.sequence_number)
    )

    for row in org_rows:
        rows_evaluated += 1
        payload = _compose_organization_payload(row)
        violations = list(evaluate_organization_rules(payload))
        if violations:
            rows_quarantined += 1
            all_violations.extend(violations)
        else:
            rows_validated += 1

    summary = DQProcessingSummary(
        rows_evaluated=rows_evaluated,
        rows_validated=rows_validated,
        rows_quarantined=rows_quarantined,
        violations=all_violations,
        dry_run=True,
    )
    _update_dq_counts(import_run, summary)
    return summary


def _compose_payload_from_csv_row(row: VolunteerCSVRow) -> MutableMapping[str, object | None]:
    payload: MutableMapping[str, object | None] = {}
    payload.update(row.raw)
    payload.update(row.normalized)

    if "email" not in payload and "email" in row.raw:
        payload["email"] = row.raw.get("email")
    if "email" not in payload and "email_normalized" in row.normalized:
        payload["email"] = row.normalized.get("email_normalized")
    if "phone" not in payload and "phone" in row.raw:
        payload["phone"] = row.raw.get("phone")
    if "phone" not in payload and "phone_e164" in row.normalized:
        payload["phone"] = row.normalized.get("phone_e164")

    return payload


def _update_dq_counts(import_run, summary: DQProcessingSummary) -> None:
    counts = dict(import_run.counts_json or {})
    dq_counts = counts.setdefault("dq", {}).setdefault("volunteers", {})
    dq_counts.update(
        {
            "rows_evaluated": summary.rows_evaluated,
            "rows_validated": summary.rows_validated if not summary.dry_run else 0,
            "rows_quarantined": summary.rows_quarantined if not summary.dry_run else 0,
            "rule_counts": dict(summary.rule_counts),
            "dry_run": summary.dry_run,
        }
    )
    import_run.counts_json = counts

    metrics = dict(import_run.metrics_json or {})
    dq_metrics = metrics.setdefault("dq", {}).setdefault("volunteers", {})
    dq_metrics.update(
        {
            "rows_evaluated": summary.rows_evaluated,
            "rows_validated": summary.rows_validated,
            "rows_quarantined": summary.rows_quarantined,
            "rule_counts": dict(summary.rule_counts),
            "dry_run": summary.dry_run,
        }
    )
    import_run.metrics_json = metrics


