"""
Service layer for querying and managing import skip records.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import NoResultFound

from flask_app.models import db
from flask_app.models.importer.schema import ImportRun, ImportSkip, ImportSkipType


@dataclass
class SkipSummary:
    """Aggregated skip statistics for a run."""

    total_skips: int
    by_type: Mapping[str, int]
    by_reason: Mapping[str, int]


class ImportSkipService:
    """Facade for searching and querying import skip records."""

    def __init__(self, session: Session | None = None):
        self.session: Session = session or db.session

    def get_skips_for_run(
        self,
        run_id: int,
        *,
        skip_type: ImportSkipType | None = None,
        entity_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[ImportSkip]:
        """
        Get skip records for a specific import run.

        Args:
            run_id: Import run ID
            skip_type: Optional filter by skip type
            entity_type: Optional filter by entity type
            limit: Optional limit on number of results
            offset: Offset for pagination

        Returns:
            List of ImportSkip records
        """
        query = self.session.query(ImportSkip).filter(ImportSkip.run_id == run_id)

        if skip_type:
            query = query.filter(ImportSkip.skip_type == skip_type)

        if entity_type:
            query = query.filter(ImportSkip.entity_type == entity_type)

        query = query.order_by(ImportSkip.created_at.desc())

        if limit:
            query = query.limit(limit)

        if offset:
            query = query.offset(offset)

        return list(query.all())

    def get_skip(self, skip_id: int) -> ImportSkip | None:
        """
        Get a single skip record by ID.

        Args:
            skip_id: Skip record ID

        Returns:
            ImportSkip record or None if not found
        """
        return (
            self.session.query(ImportSkip)
            .filter(ImportSkip.id == skip_id)
            .one_or_none()
        )

    def get_skip_summary(self, run_id: int) -> SkipSummary:
        """
        Get aggregated skip statistics for a run.

        Args:
            run_id: Import run ID

        Returns:
            SkipSummary with counts by type and reason
        """
        skips = self.get_skips_for_run(run_id)

        by_type: Counter[str] = Counter()
        by_reason: Counter[str] = Counter()

        for skip in skips:
            by_type[skip.skip_type.value] += 1
            if skip.skip_reason:
                # Extract first part of reason (before colon or first 50 chars)
                reason_key = skip.skip_reason.split(":")[0].strip() if ":" in skip.skip_reason else skip.skip_reason[:50]
                by_reason[reason_key] += 1

        return SkipSummary(
            total_skips=len(skips),
            by_type=dict(by_type),
            by_reason=dict(by_reason),
        )

    def search_skips(
        self,
        *,
        run_id: int | None = None,
        skip_type: ImportSkipType | None = None,
        entity_type: str | None = None,
        record_key: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[ImportSkip], int]:
        """
        Search skip records with filtering and pagination.

        Args:
            run_id: Optional filter by run ID
            skip_type: Optional filter by skip type
            entity_type: Optional filter by entity type
            record_key: Optional filter by record key (partial match)
            created_from: Optional filter by creation date (from)
            created_to: Optional filter by creation date (to)
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            Tuple of (list of ImportSkip records, total count)
        """
        query = self.session.query(ImportSkip)

        if run_id:
            query = query.filter(ImportSkip.run_id == run_id)

        if skip_type:
            query = query.filter(ImportSkip.skip_type == skip_type)

        if entity_type:
            query = query.filter(ImportSkip.entity_type == entity_type)

        if record_key:
            query = query.filter(ImportSkip.record_key.contains(record_key))

        if created_from:
            query = query.filter(ImportSkip.created_at >= created_from)

        if created_to:
            query = query.filter(ImportSkip.created_at <= created_to)

        # Get total count before pagination
        total_count = query.count()

        # Apply ordering and pagination
        query = query.order_by(ImportSkip.created_at.desc())
        query = query.limit(limit).offset(offset)

        return list(query.all()), total_count

