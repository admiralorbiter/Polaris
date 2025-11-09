"""Helpers for staging volunteer rows into the importer schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import IO

from flask_app.importer.adapters import VolunteerCSVAdapter
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, StagingVolunteer

BATCH_SIZE = 500


@dataclass
class StagingSummary:
    """Outcome statistics for a staging operation."""

    rows_processed: int
    rows_staged: int
    rows_skipped_blank: int
    header: tuple[str, ...]
    dry_run: bool = False


def stage_volunteers_from_csv(
    import_run: ImportRun,
    file_obj: IO[str],
    *,
    source_system: str = "csv",
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE,
) -> StagingSummary:
    """Stage volunteer rows from a CSV into ``staging_volunteers``."""

    adapter = VolunteerCSVAdapter(file_obj, source_system=source_system)
    rows_to_flush: list[StagingVolunteer] = []
    rows_staged = 0

    for row in adapter.iter_rows():
        if dry_run:
            continue

        payload_json = dict(row.raw)
        normalized_json = dict(row.normalized)
        external_system = _resolve_external_system(normalized_json.get("external_system"), source_system)
        external_id = normalized_json.get("external_id")
        checksum = _compute_checksum(normalized_json)

        staging_row = StagingVolunteer(
            run_id=import_run.id,
            sequence_number=row.sequence_number,
            source_record_id=_resolve_source_record_id(external_id, row.sequence_number),
            external_system=external_system,
            external_id=str(external_id) if external_id not in (None, "") else None,
            payload_json=payload_json,
            normalized_json=normalized_json,
            checksum=checksum,
        )
        rows_to_flush.append(staging_row)
        rows_staged += 1

        if len(rows_to_flush) >= batch_size:
            db.session.add_all(rows_to_flush)
            db.session.flush()
            rows_to_flush.clear()

    if not dry_run and rows_to_flush:
        db.session.add_all(rows_to_flush)
        db.session.flush()

    summary = StagingSummary(
        rows_processed=adapter.statistics.rows_processed,
        rows_staged=rows_staged if not dry_run else 0,
        rows_skipped_blank=adapter.statistics.rows_skipped_blank,
        header=adapter.header.canonical_headers if adapter.header else (),
        dry_run=dry_run,
    )
    _update_counts(import_run, summary)
    return summary


def _resolve_external_system(candidate: object | None, fallback: str) -> str:
    if isinstance(candidate, str):
        candidate_clean = candidate.strip()
        if candidate_clean:
            return candidate_clean
    elif candidate is not None:
        return str(candidate)
    return fallback or "csv"


def _compute_checksum(payload: dict[str, object | None]) -> str:
    """Return a stable checksum for a payload to support idempotency."""

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _resolve_source_record_id(external_id: object | None, sequence_number: int) -> str:
    if external_id in (None, ""):
        return f"seq-{sequence_number}"
    return str(external_id)


def _update_counts(import_run: ImportRun, summary: StagingSummary) -> None:
    counts = dict(import_run.counts_json or {})
    staging_counts = counts.setdefault("staging", {}).setdefault("volunteers", {})
    staging_counts.update(
        {
            "rows_processed": summary.rows_processed,
            "rows_staged": summary.rows_staged,
            "rows_skipped_blank": summary.rows_skipped_blank,
            "headers": list(summary.header),
            "dry_run": summary.dry_run,
        }
    )
    import_run.counts_json = counts

    metrics = dict(import_run.metrics_json or {})
    staging_metrics = metrics.setdefault("staging", {}).setdefault("volunteers", {})
    staging_metrics.update(
        {
            "rows_processed": summary.rows_processed,
            "rows_staged": summary.rows_staged,
            "rows_skipped_blank": summary.rows_skipped_blank,
            "dry_run": summary.dry_run,
        }
    )
    import_run.metrics_json = metrics
