"""
Service helpers for querying and serializing data quality violations.

The DQ inbox relies on these helpers to provide filtered listings, detailed
payload views, CSV export, and aggregate statistics without coupling view
logic to SQLAlchemy internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from io import StringIO
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import csv
import json

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, joinedload

from flask_app.models import db
from flask_app.models.importer import (
    DataQualitySeverity,
    DataQualityStatus,
    DataQualityViolation,
    ImportRun,
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


