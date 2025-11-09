"""
Service helpers for querying and serializing data quality violations.

The DQ inbox relies on these helpers to provide filtered listings, detailed
payload views, CSV export, and aggregate statistics without coupling view
logic to SQLAlchemy internals.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from io import StringIO
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import csv
import json
import hashlib

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, joinedload

from flask_app.importer.pipeline.clean import promote_clean_volunteers
from flask_app.importer.pipeline.dq import DQResult, evaluate_rules, run_minimal_dq
from flask_app.importer.pipeline.load_core import load_core_volunteers
from flask_app.importer.utils import diff_payload, normalize_payload
from flask_app.models import AdminLog, db
from flask_app.models.importer import (
    DataQualitySeverity,
    DataQualityStatus,
    DataQualityViolation,
    ImportRunStatus,
    ImportRun,
    StagingRecordStatus,
    StagingVolunteer,
)

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200
DEFAULT_SORT = "-created_at"

SORT_FIELDS = {
    "created_at": DataQualityViolation.created_at,
    "severity": DataQualityViolation.severity,
    "rule_code": DataQualityViolation.rule_code,
    "status": DataQualityViolation.status,
    "run_id": DataQualityViolation.run_id,
    "violation_id": DataQualityViolation.id,
}

LEADING_FORMULA_CHARACTERS = ("=", "+", "-", "@")


@dataclass(frozen=True)
class ViolationFilters:
    page: int = DEFAULT_PAGE
    page_size: int = DEFAULT_PAGE_SIZE
    sort: str = DEFAULT_SORT
    rule_codes: tuple[str, ...] = ()
    severities: tuple[DataQualitySeverity, ...] = ()
    statuses: tuple[DataQualityStatus, ...] = ()
    run_ids: tuple[int, ...] = ()
    created_from: datetime | None = None
    created_to: datetime | None = None

    @classmethod
    def coerce(
        cls,
        *,
        page: int | str | None = None,
        page_size: int | str | None = None,
        sort: str | None = None,
        rule_codes: Iterable[str] | None = None,
        severities: Iterable[str] | None = None,
        statuses: Iterable[str] | None = None,
        run_ids: Iterable[str] | None = None,
        created_from: str | datetime | None = None,
        created_to: str | datetime | None = None,
    ) -> "ViolationFilters":
        resolved_page = _coerce_positive_int(page, fallback=DEFAULT_PAGE)
        resolved_page_size = min(_coerce_positive_int(page_size, fallback=DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE)

        sort_value = sort or DEFAULT_SORT
        sort_key = sort_value.lstrip("-")
        if sort_key not in SORT_FIELDS:
            raise ValueError(f"Unsupported sort field '{sort_key}'.")

        resolved_rule_codes = tuple(_normalize_string(code) for code in (rule_codes or ()) if _normalize_string(code))
        resolved_severities = tuple(_coerce_enum(DataQualitySeverity, value) for value in (severities or ()))
        resolved_statuses = tuple(_coerce_enum(DataQualityStatus, value) for value in (statuses or ()))
        resolved_run_ids = tuple(_coerce_run_id(value) for value in (run_ids or ()) if _coerce_run_id(value) is not None)

        resolved_created_from = _coerce_datetime(created_from, end_of_day=False)
        resolved_created_to = _coerce_datetime(created_to, end_of_day=True)
        if resolved_created_from and resolved_created_to and resolved_created_from > resolved_created_to:
            raise ValueError("created_from must be before created_to.")

        return cls(
            page=resolved_page,
            page_size=resolved_page_size,
            sort=sort_value,
            rule_codes=resolved_rule_codes,
            severities=resolved_severities,
            statuses=resolved_statuses,
            run_ids=resolved_run_ids,
            created_from=resolved_created_from,
            created_to=resolved_created_to,
        )


@dataclass(slots=True)
class ViolationSummary:
    id: int
    run_id: int
    staging_volunteer_id: int | None
    rule_code: str
    severity: str
    status: str
    created_at: datetime
    preview: str
    source: str | None


@dataclass(slots=True)
class ViolationListResult:
    items: list[ViolationSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass(slots=True)
class ViolationStats:
    total: int
    by_rule_code: Mapping[str, int]
    by_severity: Mapping[str, int]
    by_status: Mapping[str, int]


class RemediationError(Exception):
    """Base exception for remediation failures."""


class RemediationNotFound(RemediationError):
    """Raised when the target violation cannot be located."""


class RemediationConflict(RemediationError):
    """Raised when the violation state prevents remediation."""


class RemediationValidationError(RemediationError):
    """Raised when remediation input fails validation or DQ rules."""

    def __init__(self, errors: Sequence[Mapping[str, Any]]):
        super().__init__("Remediation failed validation.")
        self.errors: list[Mapping[str, Any]] = list(errors)


@dataclass(slots=True)
class RemediationResult:
    violation_id: int
    status: DataQualityStatus
    remediation_run_id: int | None
    dq_errors: list[Mapping[str, Any]]
    edited_payload: Mapping[str, Any]
    diff: Mapping[str, Mapping[str, Any]]
    clean_contact_id: int | None
    clean_volunteer_id: int | None


@dataclass(slots=True)
class RemediationStats:
    since: datetime
    attempts: int
    successes: int
    failures: int
    field_counts: Mapping[str, int]
    rule_counts: Mapping[str, int]


class DataQualityViolationService:
    """Facade for searching and exporting data quality violations."""

    def __init__(self, session: Session | None = None) -> None:
        self.session: Session = session or db.session

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------
    def list_violations(self, filters: ViolationFilters) -> ViolationListResult:
        query = self._base_query()
        query = self._apply_filters(query, filters)

        total = query.count()
        if total == 0:
            return ViolationListResult(items=[], total=0, page=filters.page, page_size=filters.page_size, total_pages=0)

        sort_expression = _resolve_sort_expression(filters.sort)
        rows: Sequence[DataQualityViolation] = (
            query.options(
                joinedload(DataQualityViolation.staging_row),
                joinedload(DataQualityViolation.import_run),
            )
            .order_by(sort_expression)
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
            .all()
        )

        items = [self._summarize(row) for row in rows]
        total_pages = (total + filters.page_size - 1) // filters.page_size
        return ViolationListResult(
            items=items,
            total=total,
            page=filters.page,
            page_size=filters.page_size,
            total_pages=total_pages,
        )

    def get_violation(self, violation_id: int) -> DataQualityViolation | None:
        return (
            self._base_query()
            .options(
                joinedload(DataQualityViolation.staging_row),
                joinedload(DataQualityViolation.import_run),
            )
            .filter(DataQualityViolation.id == violation_id)
            .one_or_none()
        )

    def remediate_violation(
        self,
        violation_id: int,
        *,
        edited_payload: Mapping[str, Any],
        notes: str | None,
        user_id: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RemediationResult:
        """
        Apply steward-provided edits to a quarantined row and re-run the importer pipeline.
        """

        violation = self.get_violation(violation_id)
        if violation is None:
            raise RemediationNotFound(f"Violation {violation_id} not found.")
        if violation.status != DataQualityStatus.OPEN:
            raise RemediationConflict("Violation is not open for remediation.")
        staging_row = violation.staging_row
        if staging_row is None:
            raise RemediationConflict("Violation is detached from its staging row and cannot be remediated.")
        if not isinstance(edited_payload, Mapping):
            raise RemediationValidationError(
                [{"rule_code": "PAYLOAD_FORMAT", "message": "Edited payload must be an object.", "details": {}}]
            )

        now = datetime.now(timezone.utc)
        original_payload = _compose_payload_from_staging(staging_row)
        original_normalized = normalize_payload(original_payload)
        sanitized_updates = normalize_payload(edited_payload)
        updated_payload = dict(original_normalized)
        updated_payload.update(sanitized_updates)
        diff = diff_payload(original_normalized, updated_payload)

        dq_results = list(evaluate_rules(updated_payload))
        if dq_results:
            serialized_errors = [
                {
                    "rule_code": result.rule_code,
                    "severity": result.severity.value if isinstance(result.severity, DataQualitySeverity) else str(result.severity),
                    "message": result.message,
                    "details": dict(result.details),
                }
                for result in dq_results
            ]
            _record_remediation_audit(
                violation,
                user_id=user_id,
                timestamp=now,
                outcome="validation_failed",
                diff=diff,
                edited_payload=updated_payload,
                notes=notes,
                dq_errors=serialized_errors,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.session.commit()
            raise RemediationValidationError(serialized_errors)

        remediation_run = _create_remediation_run(self.session, violation, user_id=user_id, timestamp=now)
        remediation_row = _create_remediation_staging_row(
            self.session,
            remediation_run,
            staging_row,
            updated_payload,
        )

        try:
            dq_summary = run_minimal_dq(remediation_run, dry_run=False)
            if dq_summary.rows_quarantined:
                serialized_errors = [
                    {
                        "rule_code": result.rule_code,
                        "severity": result.severity.value if isinstance(result.severity, DataQualitySeverity) else str(result.severity),
                        "message": result.message,
                        "details": dict(result.details),
                    }
                    for result in dq_summary.violations
                ]
                failure_time = datetime.now(timezone.utc)
                remediation_run.status = ImportRunStatus.FAILED
                remediation_run.finished_at = failure_time
                _update_remediation_run_metrics(
                    remediation_run,
                    outcome="failed",
                    timestamp=failure_time,
                    dq_summary=dq_summary,
                    clean_summary=None,
                    core_summary=None,
                    errors=serialized_errors,
                )
                _record_remediation_audit(
                    violation,
                    user_id=user_id,
                    timestamp=failure_time,
                    outcome="dq_failed",
                    diff=diff,
                    edited_payload=updated_payload,
                    notes=notes,
                    dq_errors=serialized_errors,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    remediation_run_id=remediation_run.id,
                )
                self.session.commit()
                raise RemediationValidationError(serialized_errors)

            clean_summary = promote_clean_volunteers(remediation_run, dry_run=False)
            core_summary = load_core_volunteers(remediation_run, dry_run=False)
        except Exception:
            self.session.rollback()
            raise

        completed_at = datetime.now(timezone.utc)
        remediation_run.status = ImportRunStatus.SUCCEEDED
        remediation_run.finished_at = completed_at
        _update_remediation_run_metrics(
            remediation_run,
            outcome="succeeded",
            timestamp=completed_at,
            dq_summary=dq_summary,
            clean_summary=clean_summary,
            core_summary=core_summary,
            errors=None,
        )

        self.session.flush()
        self.session.refresh(remediation_row)
        clean_record = remediation_row.clean_record
        if clean_record is not None:
            self.session.refresh(clean_record)

        violation.status = DataQualityStatus.FIXED
        violation.remediated_at = completed_at
        violation.remediated_by_user_id = user_id
        _record_remediation_audit(
            violation,
            user_id=user_id,
            timestamp=completed_at,
            outcome="succeeded",
            diff=diff,
            edited_payload=updated_payload,
            notes=notes,
            dq_errors=[],
            ip_address=ip_address,
            user_agent=user_agent,
            remediation_run_id=remediation_run.id,
            clean_summary={
                "rows_promoted": clean_summary.rows_promoted,
                "rows_skipped": clean_summary.rows_skipped,
            },
            core_summary={
                "rows_inserted": core_summary.rows_inserted,
                "rows_skipped_duplicates": core_summary.rows_skipped_duplicates,
            },
        )

        log_details = {
            "violation_id": violation.id,
            "remediation_run_id": remediation_run.id,
            "diff": {key: dict(value) for key, value in diff.items()},
            "notes": notes,
        }
        admin_log = AdminLog(
            admin_user_id=user_id,
            action="IMPORT_VIOLATION_REMEDIATED",
            details=json.dumps(log_details),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(admin_log)

        self.session.commit()

        clean_contact_id = clean_record.core_contact_id if clean_record is not None else None
        clean_volunteer_id = clean_record.core_volunteer_id if clean_record is not None else None
        return RemediationResult(
            violation_id=violation.id,
            status=violation.status,
            remediation_run_id=remediation_run.id,
            dq_errors=[],
            edited_payload=updated_payload,
            diff=diff,
            clean_contact_id=clean_contact_id,
            clean_volunteer_id=clean_volunteer_id,
        )

    def get_remediation_stats(self, *, days: int = 30) -> RemediationStats:
        """
        Aggregate remediation outcomes over the requested trailing window.
        """

        window_days = max(1, int(days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        query = (
            self._base_query()
            .options()
            .filter(DataQualityViolation.remediation_audit_json.isnot(None))
        )

        attempts = 0
        successes = 0
        failures = 0
        field_counter: Counter = Counter()
        rule_counter: Counter = Counter()

        for violation in query:
            for event in _iter_remediation_events(violation):
                event_timestamp = _parse_event_timestamp(event.get("timestamp"))
                if event_timestamp is None or event_timestamp < cutoff:
                    continue

                outcome = str(event.get("outcome") or "").lower()
                if not outcome:
                    continue

                attempts += 1
                if outcome == "succeeded":
                    successes += 1
                    diff_payload = event.get("diff") or {}
                    for field in diff_payload:
                        field_counter[field] += 1
                    if violation.rule_code:
                        rule_counter[violation.rule_code] += 1
                elif outcome in {"validation_failed", "dq_failed"}:
                    failures += 1
                    dq_errors = event.get("dq_errors") or ()
                    for error in dq_errors:
                        rule_code = (error or {}).get("rule_code") or violation.rule_code
                        if rule_code:
                            rule_counter[rule_code] += 1

        return RemediationStats(
            since=cutoff,
            attempts=attempts,
            successes=successes,
            failures=failures,
            field_counts=dict(field_counter),
            rule_counts=dict(rule_counter),
        )
    def summarize(self, violation: DataQualityViolation) -> ViolationSummary:
        return self._summarize(violation)

    def get_stats(self, filters: ViolationFilters) -> ViolationStats:
        query = self._apply_filters(self._base_query(), filters, include_sort=False)

        by_rule_code = {rule_code: count for rule_code, count in query.with_entities(DataQualityViolation.rule_code, func.count()).group_by(DataQualityViolation.rule_code).all()}
        by_severity = {
            severity.value if isinstance(severity, DataQualitySeverity) else str(severity): count
            for severity, count in query.with_entities(DataQualityViolation.severity, func.count()).group_by(DataQualityViolation.severity).all()
        }
        by_status = {
            status.value if isinstance(status, DataQualityStatus) else str(status): count
            for status, count in query.with_entities(DataQualityViolation.status, func.count()).group_by(DataQualityViolation.status).all()
        }

        total = sum(by_rule_code.values())
        return ViolationStats(total=total, by_rule_code=by_rule_code, by_severity=by_severity, by_status=by_status)

    def export_csv(self, filters: ViolationFilters, *, limit: int = 5000) -> tuple[str, str]:
        query = (
            self._apply_filters(self._base_query(), filters)
            .options(
                joinedload(DataQualityViolation.staging_row),
            )
            .order_by(_resolve_sort_expression(filters.sort))
            .limit(limit)
        )
        rows = query.all()
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "violation_id",
                "run_id",
                "staging_volunteer_id",
                "rule_code",
                "severity",
                "status",
                "created_at",
                "staging_row_data",
                "violation_details",
            ]
        )
        for row in rows:
            staging_json = row.staging_row.payload_json if row.staging_row and row.staging_row.payload_json else {}
            flattened_payload = _flatten_mapping(staging_json)
            details_json = _flatten_mapping(row.details_json or {})
            writer.writerow(
                [
                    row.id,
                    row.run_id,
                    row.staging_volunteer_id,
                    row.rule_code,
                    row.severity.value if isinstance(row.severity, DataQualitySeverity) else str(row.severity),
                    row.status.value if isinstance(row.status, DataQualityStatus) else str(row.status),
                    row.created_at.isoformat() if row.created_at else "",
                    _sanitize_csv(flattened_payload),
                    _sanitize_csv(details_json),
                ]
            )
        filename = f"dq_violations_export_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
        return filename, buffer.getvalue()

    def list_rule_codes(self) -> list[str]:
        rows = self.session.query(DataQualityViolation.rule_code).distinct().order_by(DataQualityViolation.rule_code.asc()).all()
        return [row[0] for row in rows if row and row[0]]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _base_query(self):
        return self.session.query(DataQualityViolation)

    def _apply_filters(self, query, filters: ViolationFilters, *, include_sort: bool = True):
        predicates = []
        if filters.rule_codes:
            predicates.append(DataQualityViolation.rule_code.in_(filters.rule_codes))
        if filters.severities:
            predicates.append(DataQualityViolation.severity.in_(filters.severities))
        if filters.statuses:
            predicates.append(DataQualityViolation.status.in_(filters.statuses))
        if filters.run_ids:
            predicates.append(DataQualityViolation.run_id.in_(filters.run_ids))
        if filters.created_from:
            predicates.append(DataQualityViolation.created_at >= filters.created_from)
        if filters.created_to:
            predicates.append(DataQualityViolation.created_at <= filters.created_to)
        if predicates:
            query = query.filter(and_(*predicates))
        if include_sort:
            query = query.order_by(_resolve_sort_expression(filters.sort))
        return query

    def _summarize(self, violation: DataQualityViolation) -> ViolationSummary:
        staging = violation.staging_row
        import_run = violation.import_run
        preview = _build_preview(staging)
        source = import_run.source if import_run else None
        severity = violation.severity.value if isinstance(violation.severity, DataQualitySeverity) else str(violation.severity)
        status = violation.status.value if isinstance(violation.status, DataQualityStatus) else str(violation.status)
        return ViolationSummary(
            id=violation.id,
            run_id=violation.run_id,
            staging_volunteer_id=violation.staging_volunteer_id,
            rule_code=violation.rule_code,
            severity=severity,
            status=status,
            created_at=violation.created_at or datetime.now(timezone.utc),
            preview=preview,
            source=source,
        )


# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------


def _coerce_positive_int(candidate: int | str | None, *, fallback: int) -> int:
    if candidate in (None, ""):
        return fallback
    if isinstance(candidate, int):
        return max(1, candidate)
    if isinstance(candidate, str) and candidate.isdigit():
        return max(1, int(candidate))
    raise ValueError(f"Expected positive integer, received '{candidate}'.")


def _normalize_string(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    return candidate or None


def _coerce_enum(enum_cls, value: str | Any):
    if isinstance(value, enum_cls):
        return value
    normalized = _normalize_string(str(value))
    if not normalized:
        raise ValueError(f"Empty value is not valid for {enum_cls.__name__}.")
    try:
        return enum_cls(normalized.lower())
    except ValueError as exc:
        raise ValueError(f"Unsupported value '{value}' for {enum_cls.__name__}.") from exc


def _coerce_run_id(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"Expected integer run_id, received '{value}'.")


def _coerce_datetime(candidate: str | datetime | None, *, end_of_day: bool) -> datetime | None:
    if candidate in (None, ""):
        return None
    if isinstance(candidate, datetime):
        return candidate if candidate.tzinfo else candidate.replace(tzinfo=timezone.utc)
    text = candidate.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d":
                parsed = datetime.combine(parsed.date(), time.max if end_of_day else time.min)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unable to parse datetime '{candidate}'.")


def _resolve_sort_expression(sort: str):
    descending = sort.startswith("-")
    sort_key = sort.lstrip("-")
    column = SORT_FIELDS.get(sort_key)
    if column is None:
        raise ValueError(f"Unsupported sort field '{sort}'.")
    return column.desc() if descending else column.asc()


def _build_preview(staging: StagingVolunteer | None) -> str:
    if staging is None:
        return ""
    preview_parts = []
    payload = staging.payload_json or {}
    normalized = staging.normalized_json or {}

    first_name = normalized.get("first_name") or payload.get("first_name")
    last_name = normalized.get("last_name") or payload.get("last_name")
    email = normalized.get("email") or normalized.get("email_normalized") or payload.get("email")
    phone = normalized.get("phone_e164") or payload.get("phone")

    if first_name or last_name:
        preview_parts.append(" ".join(filter(None, (str(first_name or "").strip(), str(last_name or "").strip()))).strip())
    if email:
        preview_parts.append(str(email).strip())
    if phone:
        preview_parts.append(str(phone).strip())
    if not preview_parts:
        preview_parts.append(f"Row #{staging.id}")
    return " · ".join(part for part in preview_parts if part)


def _sanitize_csv(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in LEADING_FORMULA_CHARACTERS:
        return f"'{text}"
    return text


def _record_remediation_audit(
    violation: DataQualityViolation,
    *,
    user_id: int,
    timestamp: datetime,
    outcome: str,
    diff: Mapping[str, Mapping[str, Any]],
    edited_payload: Mapping[str, Any],
    notes: str | None,
    dq_errors: Sequence[Mapping[str, Any]],
    ip_address: str | None,
    user_agent: str | None,
    remediation_run_id: int | None = None,
    **extra: Any,
) -> None:
    events = []
    existing = violation.remediation_audit_json or {}
    if isinstance(existing, Mapping):
        prior = existing.get("events")
        if isinstance(prior, Sequence):
            events.extend(event for event in prior if isinstance(event, Mapping))
    serialized_diff = {key: dict(value) for key, value in diff.items()}
    event = {
        "timestamp": timestamp.isoformat(),
        "user_id": user_id,
        "outcome": outcome,
        "diff": serialized_diff,
        "edited_payload": dict(edited_payload),
        "notes": notes,
        "dq_errors": list(dq_errors),
        "ip_address": ip_address,
        "user_agent": user_agent,
        "remediation_run_id": remediation_run_id,
    }
    if extra:
        event.update(extra)
    events.append(event)
    violation.remediation_audit_json = {"events": events}
    violation.edited_payload_json = dict(edited_payload)
    violation.edited_fields_json = serialized_diff
    violation.remediation_notes = notes


def _create_remediation_run(
    session: Session,
    violation: DataQualityViolation,
    *,
    user_id: int,
    timestamp: datetime,
) -> ImportRun:
    parent_run = violation.import_run
    source = parent_run.source if parent_run else violation.entity_type
    adapter = parent_run.adapter if parent_run else None
    run = ImportRun(
        source=source,
        adapter=adapter,
        status=ImportRunStatus.RUNNING,
        dry_run=False,
        started_at=timestamp,
        finished_at=None,
        triggered_by_user_id=user_id,
        counts_json={},
        metrics_json={},
        anomaly_flags={},
        error_summary=None,
        notes=f"Remediation of violation {violation.id} (parent run {violation.run_id})",
        ingest_params_json={
            "remediation": {
                "violation_id": violation.id,
                "parent_run_id": violation.run_id,
                "staging_volunteer_id": violation.staging_volunteer_id,
            }
        },
    )
    session.add(run)
    session.flush()
    return run


def _create_remediation_staging_row(
    session: Session,
    remediation_run: ImportRun,
    original_row: StagingVolunteer,
    updated_payload: Mapping[str, Any],
) -> StagingVolunteer:
    payload_copy = dict(updated_payload)
    staging_row = StagingVolunteer(
        run_id=remediation_run.id,
        sequence_number=original_row.sequence_number,
        source_record_id=original_row.source_record_id,
        external_system=original_row.external_system,
        external_id=original_row.external_id,
        payload_json=payload_copy,
        normalized_json=payload_copy,
        checksum=_compute_checksum(payload_copy),
        status=StagingRecordStatus.LANDED,
    )
    session.add(staging_row)
    session.flush()
    return staging_row


def _compose_payload_from_staging(staging_row: StagingVolunteer) -> dict[str, Any]:
    payload = dict(staging_row.payload_json or {})
    normalized = staging_row.normalized_json or {}
    for key, value in normalized.items():
        payload.setdefault(key, value)
    payload.setdefault("external_system", staging_row.external_system)
    if staging_row.external_id and not payload.get("external_id"):
        payload["external_id"] = staging_row.external_id
    return payload


def _compute_checksum(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _update_remediation_run_metrics(
    run: ImportRun,
    *,
    outcome: str,
    timestamp: datetime,
    dq_summary=None,
    clean_summary=None,
    core_summary=None,
    errors: Sequence[Mapping[str, Any]] | None,
) -> None:
    counts = dict(run.counts_json or {})
    remediation_counts = counts.setdefault("remediation", {})
    remediation_counts["attempts"] = remediation_counts.get("attempts", 0) + 1
    if outcome == "succeeded":
        remediation_counts["succeeded"] = remediation_counts.get("succeeded", 0) + 1
    else:
        remediation_counts["failed"] = remediation_counts.get("failed", 0) + 1
    remediation_counts["last_attempt_at"] = timestamp.isoformat()
    run.counts_json = counts

    metrics = dict(run.metrics_json or {})
    remediation_metrics = metrics.setdefault("remediation", {})
    remediation_metrics.update(
        {
            "outcome": outcome,
            "timestamp": timestamp.isoformat(),
        }
    )
    if dq_summary is not None:
        remediation_metrics["dq"] = {
            "rows_evaluated": getattr(dq_summary, "rows_evaluated", 0),
            "rows_validated": getattr(dq_summary, "rows_validated", 0),
            "rows_quarantined": getattr(dq_summary, "rows_quarantined", 0),
        }
    if clean_summary is not None:
        remediation_metrics["clean"] = {
            "rows_promoted": getattr(clean_summary, "rows_promoted", 0),
            "rows_skipped": getattr(clean_summary, "rows_skipped", 0),
        }
    if core_summary is not None:
        remediation_metrics["core"] = {
            "rows_inserted": getattr(core_summary, "rows_inserted", 0),
            "rows_skipped_duplicates": getattr(core_summary, "rows_skipped_duplicates", 0),
        }
    if errors:
        remediation_metrics["errors"] = list(errors)
    run.metrics_json = metrics


def _iter_remediation_events(violation: DataQualityViolation) -> Iterable[Mapping[str, Any]]:
    payload = violation.remediation_audit_json or {}
    events = payload.get("events") if isinstance(payload, Mapping) else None
    if not isinstance(events, Sequence):
        return []
    return (event for event in events if isinstance(event, Mapping))


def _parse_event_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value)
    try:
        normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _flatten_mapping(candidate: object) -> str:
    if not isinstance(candidate, Mapping):
        return json.dumps(candidate, ensure_ascii=False, sort_keys=True)

    parts: list[str] = []
    for key in sorted(candidate.keys()):
        value = candidate[key]
        if isinstance(value, Mapping):
            value_str = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            value_str = "" if value is None else str(value)
        if value_str and value_str[0] in LEADING_FORMULA_CHARACTERS:
            value_str = f"'{value_str}"
        parts.append(f"{key}={value_str}")
    return "; ".join(parts)


