"""
Service helpers for importer run querying, filtering, and serialization.

The runs dashboard consumes these helpers to provide paginated listings,
detail payloads, and aggregate statistics while keeping SQLAlchemy logic
centralized and easily testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from flask_app.models import AdminLog, User, db
from flask_app.models.importer.schema import ImportRun, ImportRunStatus

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
DEFAULT_SORT = "-started_at"

VALID_SORT_FIELDS = {
    "id": ImportRun.id,
    "run_id": ImportRun.id,
    "source": ImportRun.source,
    "status": ImportRun.status,
    "started_at": ImportRun.started_at,
    "finished_at": ImportRun.finished_at,
    "created_at": ImportRun.created_at,
}


@dataclass(frozen=True)
class RunFilters:
    """Canonical set of filter options applied to importer runs queries."""

    page: int = DEFAULT_PAGE
    page_size: int = DEFAULT_PAGE_SIZE
    sort: str = DEFAULT_SORT
    statuses: tuple[ImportRunStatus, ...] = field(default_factory=tuple)
    sources: tuple[str, ...] = field(default_factory=tuple)
    search: str | None = None
    started_from: datetime | None = None
    started_to: datetime | None = None
    include_dry_runs: bool = True

    @classmethod
    def coerce(
        cls,
        *,
        page: int | str | None = None,
        page_size: int | str | None = None,
        sort: str | None = None,
        statuses: Iterable[str] | None = None,
        sources: Iterable[str] | None = None,
        search: str | None = None,
        started_from: str | datetime | None = None,
        started_to: str | datetime | None = None,
        include_dry_runs: str | bool | None = None,
    ) -> "RunFilters":
        """
        Coerce mixed user input into a validated ``RunFilters`` instance.
        """

        resolved_page = _coerce_positive_int(page, fallback=DEFAULT_PAGE)
        resolved_size = min(_coerce_positive_int(page_size, fallback=DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE)

        resolved_sort = sort or DEFAULT_SORT
        sort_key = resolved_sort.lstrip("-")
        if sort_key not in VALID_SORT_FIELDS:
            raise ValueError(f"Unsupported sort field '{sort_key}'.")

        resolved_statuses: list[ImportRunStatus] = []
        if statuses:
            for value in statuses:
                if value is None or value == "":
                    continue
                resolved_statuses.append(_coerce_status(value))

        resolved_sources = tuple(sorted({s.strip().lower() for s in (sources or ()) if s}))

        resolved_search = search.strip() if isinstance(search, str) and search.strip() else None

        resolved_started_from = _coerce_datetime(started_from)
        resolved_started_to = _coerce_datetime(started_to, end_of_day=True)

        if resolved_started_from and resolved_started_to and resolved_started_from > resolved_started_to:
            raise ValueError("started_from must be before started_to.")

        resolved_include_dry_runs = _coerce_bool(include_dry_runs, default=True)

        return cls(
            page=resolved_page,
            page_size=resolved_size,
            sort=resolved_sort,
            statuses=tuple(resolved_statuses),
            sources=resolved_sources,
            search=resolved_search,
            started_from=resolved_started_from,
            started_to=resolved_started_to,
            include_dry_runs=resolved_include_dry_runs,
        )


@dataclass(slots=True)
class RunSummary:
    """Summarized representation of an importer run."""

    id: int
    source: str
    adapter: str | None
    status: str
    dry_run: bool
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    rows_staged: int
    rows_validated: int
    rows_quarantined: int
    rows_created: int
    rows_updated: int
    rows_reactivated: int
    rows_changed: int
    rows_skipped_duplicates: int
    rows_skipped_no_change: int
    rows_deduped_auto: int
    rows_missing_external_id: int
    rows_soft_deleted: int
    triggered_by: Mapping[str, Any] | None
    can_retry: bool
    counts_digest: Mapping[str, Any]


@dataclass(slots=True)
class RunListResult:
    """Paginated result set for importer runs."""

    items: list[RunSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass(slots=True)
class RunStats:
    """Aggregate statistics for importer runs dashboard."""

    total: int
    statuses: Mapping[str, int]
    sources: Mapping[str, int]
    dry_runs: Mapping[str, int]


class ImportRunService:
    """Facade for querying importer runs with consistent filtering semantics."""

    def __init__(self, session: Session | None = None) -> None:
        self.session: Session = session or db.session

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def list_runs(self, filters: RunFilters) -> RunListResult:
        query = self._base_query()
        query = self._apply_filters(query, filters)

        total = query.count()
        if total == 0:
            return RunListResult(items=[], total=0, page=filters.page, page_size=filters.page_size, total_pages=0)

        sort_expression = _resolve_sort_expression(filters.sort)
        paginated = (
            query.options()
            .order_by(sort_expression)
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
            .all()
        )

        summaries = [self._summarize_run(run) for run in paginated]

        total_pages = (total + filters.page_size - 1) // filters.page_size
        return RunListResult(
            items=summaries, total=total, page=filters.page, page_size=filters.page_size, total_pages=total_pages
        )

    def get_run(self, run_id: int) -> ImportRun:
        run = self._base_query().filter(ImportRun.id == run_id).one_or_none()
        if run is None:
            raise NoResultFound(f"Import run {run_id} not found.")
        return run

    def get_run_summary(self, run_id: int) -> RunSummary:
        run = self.get_run(run_id)
        return self._summarize_run(run)

    def summarize(self, run: ImportRun) -> RunSummary:
        return self._summarize_run(run)

    def get_stats(self, filters: RunFilters) -> RunStats:
        query = self._apply_filters(self._base_query(), filters, include_sort=False)

        status_counts = {
            status.value if isinstance(status, ImportRunStatus) else str(status): count
            for status, count in (query.with_entities(ImportRun.status, func.count()).group_by(ImportRun.status).all())
        }
        source_counts = {
            source: count
            for source, count in (query.with_entities(ImportRun.source, func.count()).group_by(ImportRun.source).all())
        }
        dry_run_counts = {"true": 0, "false": 0}
        for dry_run_value, count in (
            query.with_entities(ImportRun.dry_run, func.count()).group_by(ImportRun.dry_run).all()
        ):
            label = "true" if bool(dry_run_value) else "false"
            dry_run_counts[label] = dry_run_counts.get(label, 0) + count
        total = sum(status_counts.values())

        return RunStats(total=total, statuses=status_counts, sources=source_counts, dry_runs=dry_run_counts)

    def list_sources(self) -> list[str]:
        rows = self.session.query(ImportRun.source).distinct().order_by(ImportRun.source.asc()).all()
        return [row[0] for row in rows if row and row[0]]

    @staticmethod
    def record_audit_view(
        user_id: int, run_id: int | None, *, ip_address: str | None = None, user_agent: str | None = None
    ) -> None:
        """Persist an audit trail entry for dashboard interactions."""

        AdminLog.log_action(
            admin_user_id=user_id,
            action="IMPORT_RUN_VIEW" if run_id is None else "IMPORT_RUN_DETAIL_VIEW",
            target_user_id=None,
            details=f'{{"run_id": {run_id if run_id is not None else "null"}}}',
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _base_query(self):
        return self.session.query(ImportRun).options()

    def _apply_filters(self, query, filters: RunFilters, *, include_sort: bool = True):
        predicates = []

        if filters.statuses:
            predicates.append(ImportRun.status.in_(filters.statuses))

        if filters.sources:
            predicates.append(ImportRun.source.in_(filters.sources))

        if not filters.include_dry_runs:
            predicates.append(ImportRun.dry_run.is_(False))

        if filters.started_from:
            predicates.append(ImportRun.started_at >= filters.started_from)

        if filters.started_to:
            predicates.append(ImportRun.started_at <= filters.started_to)

        if filters.search:
            predicates.append(_build_search_predicate(filters.search))

        if predicates:
            query = query.filter(and_(*predicates))

        if include_sort:
            query = query.order_by(_resolve_sort_expression(filters.sort))

        return query

    def _summarize_run(self, run: ImportRun) -> RunSummary:
        counts_json = run.counts_json or {}
        staging_counts = _nested_dict(counts_json, "staging", "volunteers")
        dq_counts = _nested_dict(counts_json, "dq", "volunteers")
        core_counts = _nested_dict(counts_json, "core", "volunteers")

        summary_counts: dict[str, Any] = {
            "staging": staging_counts,
            "dq": dq_counts,
            "core": core_counts,
        }

        duration_seconds: float | None = None
        if run.started_at:
            finished = run.finished_at or datetime.now(timezone.utc)
            duration_seconds = (finished - run.started_at).total_seconds()

        triggered_by_user = None
        if run.triggered_by_user_id:
            user: User | None = self.session.get(User, run.triggered_by_user_id)
            if user:
                triggered_by_user = {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "display_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
                }

        can_retry = _can_retry(run)

        rows_created = int(core_counts.get("rows_created", 0) or 0)
        rows_updated = int(core_counts.get("rows_updated", 0) or 0)
        rows_reactivated = int(core_counts.get("rows_reactivated", 0) or 0)
        rows_changed = int(core_counts.get("rows_changed", rows_updated) or 0)
        rows_deduped_auto = int(core_counts.get("rows_deduped_auto", 0) or 0)
        rows_skipped_duplicates = int(core_counts.get("rows_skipped_duplicates", 0) or 0)
        rows_skipped_no_change = int(core_counts.get("rows_skipped_no_change", 0) or 0)
        rows_missing_external_id = int(core_counts.get("rows_missing_external_id", 0) or 0)
        rows_soft_deleted = int(core_counts.get("rows_soft_deleted", 0) or 0)

        return RunSummary(
            id=run.id,
            source=run.source,
            adapter=run.adapter,
            status=run.status.value if isinstance(run.status, ImportRunStatus) else str(run.status),
            dry_run=run.dry_run,
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_seconds=duration_seconds,
            rows_staged=int(staging_counts.get("rows_staged", 0) or 0),
            rows_validated=int(dq_counts.get("rows_validated", 0) or 0),
            rows_quarantined=int(dq_counts.get("rows_quarantined", 0) or 0),
            rows_created=rows_created,
            rows_updated=rows_updated,
            rows_reactivated=rows_reactivated,
            rows_changed=rows_changed,
            rows_skipped_duplicates=rows_skipped_duplicates,
            rows_skipped_no_change=rows_skipped_no_change,
            rows_deduped_auto=rows_deduped_auto,
            rows_missing_external_id=rows_missing_external_id,
            rows_soft_deleted=rows_soft_deleted,
            triggered_by=triggered_by_user,
            can_retry=can_retry,
            counts_digest=summary_counts,
        )


# -------------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------------


def _coerce_positive_int(candidate: int | str | None, *, fallback: int) -> int:
    if candidate in (None, ""):
        return fallback
    if isinstance(candidate, int):
        return max(1, candidate)
    if isinstance(candidate, str) and candidate.isdigit():
        return max(1, int(candidate))
    raise ValueError(f"Expected positive integer for pagination, received '{candidate}'.")


def _coerce_status(value: str | ImportRunStatus) -> ImportRunStatus:
    if isinstance(value, ImportRunStatus):
        return value
    normalized = str(value).strip().lower()
    try:
        return ImportRunStatus(normalized)
    except ValueError:
        raise ValueError(f"Unsupported status filter '{value}'.") from None


def _coerce_datetime(candidate: str | datetime | None, *, end_of_day: bool = False) -> datetime | None:
    if candidate in (None, ""):
        return None
    if isinstance(candidate, datetime):
        return candidate if candidate.tzinfo else candidate.replace(tzinfo=timezone.utc)
    text = str(candidate).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d" and end_of_day:
                parsed = datetime.combine(parsed.date(), time.max)
            if fmt == "%Y-%m-%d" and not end_of_day:
                parsed = datetime.combine(parsed.date(), time.min)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unable to parse datetime value '{candidate}'. Expected ISO-like formats.")


def _coerce_bool(candidate: str | bool | None, *, default: bool) -> bool:
    if candidate is None:
        return default
    if isinstance(candidate, bool):
        return candidate
    normalized = candidate.strip().lower()
    if normalized in ("1", "true", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "no", "n", "off"):
        return False
    return default


def _nested_dict(data: Mapping[str, Any], *keys: str) -> MutableMapping[str, Any]:
    cursor: Mapping[str, Any] | MutableMapping[str, Any] = data
    for key in keys:
        next_value = cursor.get(key, {})
        if not isinstance(next_value, Mapping):
            return {}
        cursor = next_value
    return dict(cursor)


def _resolve_sort_expression(sort: str):
    descending = sort.startswith("-")
    sort_key = sort.lstrip("-")
    expression = VALID_SORT_FIELDS.get(sort_key)
    if expression is None:
        raise ValueError(f"Unsupported sort field '{sort}'.")
    return expression.desc() if descending else expression.asc()


def _build_search_predicate(term: str):
    """Search by run_id exact match, adapter/source partial matches."""
    like_pattern = f"%{term.lower()}%"
    numeric_term = None
    if term.isdigit():
        numeric_term = int(term)

    predicates = [
        func.lower(ImportRun.source).like(like_pattern),
        func.lower(ImportRun.adapter).like(like_pattern),
    ]
    if numeric_term is not None:
        predicates.append(ImportRun.id == numeric_term)
    return or_(*predicates)


def _can_retry(run: ImportRun) -> bool:
    if not run.ingest_params_json:
        return False
    params = run.ingest_params_json
    file_path = params.get("file_path")
    keep_file = params.get("keep_file", False)
    if not keep_file or not file_path:
        return False
    try:
        return Path(file_path).exists()
    except (TypeError, ValueError):
        return False
