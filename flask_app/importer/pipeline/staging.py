"""Helpers for staging volunteer rows into the importer schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import IO

from flask import current_app, has_app_context

from flask_app.importer.adapters import VolunteerCSVAdapter, VolunteerCSVRow
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, StagingVolunteer

BATCH_SIZE = 500

BATCH_SIZE = 500


def _commit_staging_batch() -> None:
    if has_app_context() and current_app.config.get("TESTING"):
        db.session.flush()
    else:
        db.session.commit()


@dataclass
class StagingSummary:
    """Outcome statistics for a staging operation."""

    rows_processed: int
    rows_staged: int
    rows_skipped_blank: int
    header: tuple[str, ...]
    dry_run: bool = False
    dry_run_rows: tuple[VolunteerCSVRow, ...] = ()


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
    dry_run_rows: list[VolunteerCSVRow] = []
    rows_staged = 0
    
    # Track field-level statistics for CSV
    csv_field_stats: dict[str, dict[str, int]] = {}
    total_rows_processed = 0

    for row in adapter.iter_rows():
        total_rows_processed += 1
        payload_json = dict(row.raw)
        normalized_json = dict(row.normalized)
        
        # Track CSV column population
        for column_name, value in payload_json.items():
            if column_name not in csv_field_stats:
                csv_field_stats[column_name] = {
                    "records_with_value": 0,
                    "total_records_processed": 0,
                }
            csv_field_stats[column_name]["total_records_processed"] += 1
            if value is not None and value != "":
                csv_field_stats[column_name]["records_with_value"] += 1
        
        external_system = resolve_external_system(normalized_json.get("external_system"), source_system)
        external_id = normalized_json.get("external_id")
        checksum = compute_checksum(normalized_json)

        if dry_run:
            dry_run_rows.append(row)
            continue

        staging_row = StagingVolunteer(
            run_id=import_run.id,
            sequence_number=row.sequence_number,
            source_record_id=resolve_source_record_id(external_id, row.sequence_number),
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
            _commit_staging_batch()
            rows_to_flush.clear()

    if not dry_run and rows_to_flush:
        db.session.add_all(rows_to_flush)
        _commit_staging_batch()

    summary = StagingSummary(
        rows_processed=adapter.statistics.rows_processed,
        rows_staged=rows_staged if not dry_run else 0,
        rows_skipped_blank=adapter.statistics.rows_skipped_blank,
        header=adapter.header.canonical_headers if adapter.header else (),
        dry_run=dry_run,
        dry_run_rows=tuple(dry_run_rows),
    )
    update_staging_counts(import_run, summary, csv_field_stats=csv_field_stats if csv_field_stats else None)
    _commit_staging_batch()
    return summary


def resolve_external_system(candidate: object | None, fallback: str) -> str:
    if isinstance(candidate, str):
        candidate_clean = candidate.strip()
        if candidate_clean:
            return candidate_clean
    elif candidate is not None:
        return str(candidate)
    return fallback or "csv"


def compute_checksum(payload: dict[str, object | None]) -> str:
    """Return a stable checksum for a payload to support idempotency."""

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def resolve_source_record_id(external_id: object | None, sequence_number: int) -> str:
    if external_id in (None, ""):
        return f"seq-{sequence_number}"
    return str(external_id)


def update_staging_counts(import_run: ImportRun, summary: StagingSummary, *, csv_field_stats: dict[str, dict[str, int]] | None = None) -> None:
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
    
    # Store CSV field-level statistics
    if csv_field_stats:
        field_stats_data = metrics.setdefault("field_stats", {}).setdefault("volunteers", {})
        source_fields_data = field_stats_data.setdefault("source_fields", {})
        
        for column_name, stats in csv_field_stats.items():
            total_processed = stats.get("total_records_processed", 0)
            with_value = stats.get("records_with_value", 0)
            population_rate = with_value / total_processed if total_processed > 0 else 0.0
            
            source_fields_data[column_name] = {
                "target": None,  # CSV columns don't have explicit target mapping
                "records_with_value": with_value,
                "records_mapped": with_value,  # For CSV, mapped = with value
                "records_transformed": 0,
                "records_failed_transform": 0,
                "records_used_default": 0,
                "total_records_processed": total_processed,
                "population_rate": population_rate,
            }
    
    import_run.metrics_json = metrics
