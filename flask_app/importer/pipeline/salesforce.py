"""
Salesforce ingestion helpers for staging contacts.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from flask_app.importer.adapters.salesforce.extractor import SalesforceBatch, SalesforceExtractor, build_accounts_soql, build_contacts_soql
from flask_app.importer.mapping import FieldImportStats, SalesforceMappingTransformer, get_active_salesforce_account_mapping, get_active_salesforce_mapping
from flask_app.importer.metrics import record_salesforce_batch, record_salesforce_unmapped
from flask_app.importer.pipeline.staging import (
    StagingSummary,
    compute_checksum,
    resolve_source_record_id,
    _commit_staging_batch,
    update_staging_counts,
)
from flask_app.models.base import db
from flask_app.models.importer.schema import ImportRun, ImporterWatermark, StagingOrganization, StagingVolunteer


@dataclass
class SalesforceIngestSummary:
    """Operational summary for a Salesforce ingest run."""

    job_id: str
    batches_processed: int
    records_received: int
    records_staged: int
    dry_run: bool
    header: tuple[str, ...]
    max_modstamp: datetime | None
    unmapped_counts: Mapping[str, int]
    errors: list[str]


def ingest_salesforce_contacts(
    *,
    import_run: ImportRun,
    extractor: SalesforceExtractor,
    watermark: ImporterWatermark,
    staging_batch_size: int,
    dry_run: bool,
    logger: logging.Logger,
    record_limit: int | None = None,
) -> SalesforceIngestSummary:
    """
    Stream Salesforce Contacts into staging and update watermark metadata.
    """

    last_modstamp = watermark.last_successful_modstamp
    # Ensure last_modstamp is timezone-aware for comparison
    if last_modstamp is not None and last_modstamp.tzinfo is None:
        last_modstamp = last_modstamp.replace(tzinfo=timezone.utc)
    soql = build_contacts_soql(last_modstamp=last_modstamp, limit=record_limit)
    batches_processed = 0
    records_received = 0
    records_staged = 0
    header: tuple[str, ...] = ()
    max_modstamp: datetime | None = last_modstamp
    sequence_number = 0
    staging_buffer: list[StagingVolunteer] = []
    unmapped_counter: Counter[str] = Counter()
    transform_errors: list[str] = []

    mapping_spec = get_active_salesforce_mapping()
    transformer = SalesforceMappingTransformer(mapping_spec)
    
    # Aggregate field statistics across all records
    aggregated_field_stats: dict[str, FieldImportStats] = {}
    target_field_contributors: dict[str, set[str]] = defaultdict(set)

    def flush_buffer():
        nonlocal records_staged
        if dry_run or not staging_buffer:
            staging_buffer.clear()
            return
        db.session.add_all(staging_buffer)
        _commit_staging_batch()
        records_staged += len(staging_buffer)
        staging_buffer.clear()

    for batch in extractor.extract_batches(soql):
        batches_processed += 1
        if not header and batch.records:
            header = tuple(batch.records[0].keys())
        batch_start = time.perf_counter()
        for record in batch.records:
            records_received += 1
            modstamp = _parse_salesforce_datetime(record.get("SystemModstamp"))
            if modstamp:
                # Ensure both datetimes are timezone-aware before comparison
                if max_modstamp is not None and max_modstamp.tzinfo is None:
                    max_modstamp = max_modstamp.replace(tzinfo=timezone.utc)
                if modstamp.tzinfo is None:
                    modstamp = modstamp.replace(tzinfo=timezone.utc)
                if max_modstamp is None or modstamp > max_modstamp:
                    max_modstamp = modstamp
            transform_result = transformer.transform(record)
            
            # Aggregate field statistics
            for source_field, stats in transform_result.field_stats.items():
                if source_field not in aggregated_field_stats:
                    aggregated_field_stats[source_field] = FieldImportStats(
                        source_field=stats.source_field,
                        target_field=stats.target_field,
                    )
                agg_stats = aggregated_field_stats[source_field]
                agg_stats.records_with_value += stats.records_with_value
                agg_stats.records_mapped += stats.records_mapped
                agg_stats.records_transformed += stats.records_transformed
                agg_stats.records_failed_transform += stats.records_failed_transform
                agg_stats.records_used_default += stats.records_used_default
                agg_stats.total_records_processed += stats.total_records_processed
                
                # Track target field contributors
                if stats.target_field:
                    target_field_contributors[stats.target_field].add(source_field)
            
            for field_name in transform_result.unmapped_fields:
                unmapped_counter[field_name] += 1
            if transform_result.errors:
                transform_errors.extend(transform_result.errors)
            if dry_run:
                continue
            sequence_number += 1
            normalized = transform_result.canonical or {}
            # Check for missing contact info and add metadata flag
            email_dict = normalized.get("email", {})
            phone_dict = normalized.get("phone", {})
            email_value = None
            phone_value = None
            if isinstance(email_dict, dict):
                email_value = email_dict.get("primary") or email_dict.get("home") or email_dict.get("work") or email_dict.get("alternate")
            elif email_dict:
                email_value = email_dict
            if isinstance(phone_dict, dict):
                phone_value = phone_dict.get("primary") or phone_dict.get("mobile") or phone_dict.get("home") or phone_dict.get("work")
            elif phone_dict:
                phone_value = phone_dict
            if not email_value and not phone_value:
                # Set metadata flag for missing contact info
                metadata = normalized.setdefault("metadata", {})
                metadata["missing_contact_info"] = True
            staging_buffer.append(
                StagingVolunteer(
                    run_id=import_run.id,
                    sequence_number=sequence_number,
                    source_record_id=resolve_source_record_id(record.get("Id"), sequence_number),
                    external_system="salesforce",
                    external_id=record.get("Id") or None,
                    payload_json=dict(record),
                    normalized_json=normalized,
                    checksum=compute_checksum(normalized),
                )
            )
            if len(staging_buffer) >= staging_batch_size:
                flush_buffer()
        flush_buffer()
        duration = time.perf_counter() - batch_start
        record_salesforce_batch(status="success", duration_seconds=duration, record_count=len(batch.records))
        logger.info(
            "Salesforce batch ingested",
            extra={
                "importer_run_id": import_run.id,
                "salesforce_job_id": batch.job_id,
                "salesforce_batch_sequence": batch.sequence,
                "salesforce_batch_records": len(batch.records),
                "salesforce_batch_locator": batch.locator,
                "salesforce_batch_duration_seconds": round(duration, 3),
            },
        )

    summary = SalesforceIngestSummary(
        job_id=batch.job_id if batches_processed else "n/a",
        batches_processed=batches_processed,
        records_received=records_received,
        records_staged=records_staged if not dry_run else 0,
        dry_run=dry_run,
        header=header,
        max_modstamp=max_modstamp,
        unmapped_counts=dict(unmapped_counter),
        errors=transform_errors,
    )
    if unmapped_counter:
        for field_name, count in unmapped_counter.items():
            record_salesforce_unmapped(field_name, count)
    _update_import_run(import_run, summary, field_stats=aggregated_field_stats, target_contributors=target_field_contributors)
    if not dry_run and max_modstamp:
        watermark.last_successful_modstamp = max_modstamp.astimezone(timezone.utc)
        watermark.last_run_id = import_run.id
        watermark.metadata_json = {
            "job_id": summary.job_id,
            "batches_processed": summary.batches_processed,
            "records_received": summary.records_received,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return summary


def _update_import_run(import_run: ImportRun, summary: SalesforceIngestSummary, *, field_stats: dict[str, FieldImportStats] | None = None, target_contributors: dict[str, set[str]] | None = None) -> None:
    staging_summary = StagingSummary(
        rows_processed=summary.records_received,
        rows_staged=summary.records_staged,
        rows_skipped_blank=0,
        header=summary.header,
        dry_run=summary.dry_run,
        dry_run_rows=(),
    )
    update_staging_counts(import_run, staging_summary)
    metrics = dict(import_run.metrics_json or {})
    salesforce_metrics = metrics.setdefault("salesforce", {})
    salesforce_metrics.update(
        {
            "job_id": summary.job_id,
            "batches_processed": summary.batches_processed,
            "records_received": summary.records_received,
            "records_staged": summary.records_staged,
            "dry_run": summary.dry_run,
            "max_system_modstamp": summary.max_modstamp.isoformat() if summary.max_modstamp else None,
            "unmapped_fields": dict(summary.unmapped_counts),
            "transform_errors": list(summary.errors),
        }
    )
    
    # Store field-level statistics
    if field_stats:
        field_stats_data = metrics.setdefault("field_stats", {}).setdefault("volunteers", {})
        source_fields_data = field_stats_data.setdefault("source_fields", {})
        target_fields_data = field_stats_data.setdefault("target_fields", {})
        unmapped_fields_data = field_stats_data.setdefault("unmapped_source_fields", {})
        
        # Store source field statistics
        for source_field, stats in field_stats.items():
            source_fields_data[source_field] = {
                "target": stats.target_field,
                "records_with_value": stats.records_with_value,
                "records_mapped": stats.records_mapped,
                "records_transformed": stats.records_transformed,
                "records_failed_transform": stats.records_failed_transform,
                "records_used_default": stats.records_used_default,
                "total_records_processed": stats.total_records_processed,
                "population_rate": stats.population_rate,
            }
        
        # Store target field statistics
        if target_contributors:
            total_records = summary.records_received
            for target_field, source_fields in target_contributors.items():
                # Calculate completeness for target field
                total_populated = 0
                for source_field in source_fields:
                    if source_field in field_stats:
                        total_populated += field_stats[source_field].records_mapped
                
                target_fields_data[target_field] = {
                    "source_fields": sorted(list(source_fields)),
                    "total_records_populated": total_populated,
                    "total_records_processed": total_records,
                    "completeness_rate": total_populated / total_records if total_records > 0 else 0.0,
                }
        
        # Store unmapped fields
        for unmapped_field, count in summary.unmapped_counts.items():
            unmapped_fields_data[unmapped_field] = {
                "records_with_value": count,
                "total_records_processed": summary.records_received,
            }
    
    import_run.metrics_json = metrics


def ingest_salesforce_accounts(
    *,
    import_run: ImportRun,
    extractor: SalesforceExtractor,
    watermark: ImporterWatermark,
    staging_batch_size: int,
    dry_run: bool,
    logger: logging.Logger,
    record_limit: int | None = None,
) -> SalesforceIngestSummary:
    """
    Stream Salesforce Accounts into staging and update watermark metadata.
    """

    last_modstamp = watermark.last_successful_modstamp
    # Ensure last_modstamp is timezone-aware for comparison
    if last_modstamp is not None and last_modstamp.tzinfo is None:
        last_modstamp = last_modstamp.replace(tzinfo=timezone.utc)
    soql = build_accounts_soql(last_modstamp=last_modstamp, limit=record_limit)
    batches_processed = 0
    records_received = 0
    records_staged = 0
    header: tuple[str, ...] = ()
    max_modstamp: datetime | None = last_modstamp
    sequence_number = 0
    staging_buffer: list[StagingOrganization] = []
    unmapped_counter: Counter[str] = Counter()
    transform_errors: list[str] = []

    mapping_spec = get_active_salesforce_account_mapping()
    transformer = SalesforceMappingTransformer(mapping_spec)
    
    # Aggregate field statistics across all records
    aggregated_field_stats: dict[str, FieldImportStats] = {}
    target_field_contributors: dict[str, set[str]] = defaultdict(set)

    def flush_buffer():
        nonlocal records_staged
        if dry_run or not staging_buffer:
            staging_buffer.clear()
            return
        db.session.add_all(staging_buffer)
        _commit_staging_batch()
        records_staged += len(staging_buffer)
        staging_buffer.clear()

    for batch in extractor.extract_batches(soql):
        batches_processed += 1
        if not header and batch.records:
            header = tuple(batch.records[0].keys())
        batch_start = time.perf_counter()
        for record in batch.records:
            records_received += 1
            modstamp = _parse_salesforce_datetime(record.get("SystemModstamp"))
            if modstamp:
                # Ensure both datetimes are timezone-aware before comparison
                if max_modstamp is not None and max_modstamp.tzinfo is None:
                    max_modstamp = max_modstamp.replace(tzinfo=timezone.utc)
                if modstamp.tzinfo is None:
                    modstamp = modstamp.replace(tzinfo=timezone.utc)
                if max_modstamp is None or modstamp > max_modstamp:
                    max_modstamp = modstamp
            transform_result = transformer.transform(record)
            
            # Aggregate field statistics
            for source_field, stats in transform_result.field_stats.items():
                if source_field not in aggregated_field_stats:
                    aggregated_field_stats[source_field] = FieldImportStats(
                        source_field=stats.source_field,
                        target_field=stats.target_field,
                    )
                agg_stats = aggregated_field_stats[source_field]
                agg_stats.records_with_value += stats.records_with_value
                agg_stats.records_mapped += stats.records_mapped
                agg_stats.records_transformed += stats.records_transformed
                agg_stats.records_failed_transform += stats.records_failed_transform
                agg_stats.records_used_default += stats.records_used_default
                agg_stats.total_records_processed += stats.total_records_processed
                
                # Track target field contributors
                if stats.target_field:
                    target_field_contributors[stats.target_field].add(source_field)
            
            for field_name in transform_result.unmapped_fields:
                unmapped_counter[field_name] += 1
            if transform_result.errors:
                transform_errors.extend(transform_result.errors)
            if dry_run:
                continue
            sequence_number += 1
            normalized = transform_result.canonical or {}
            staging_buffer.append(
                StagingOrganization(
                    run_id=import_run.id,
                    sequence_number=sequence_number,
                    source_record_id=resolve_source_record_id(record.get("Id"), sequence_number),
                    external_system="salesforce",
                    external_id=record.get("Id") or None,
                    payload_json=dict(record),
                    normalized_json=normalized,
                    checksum=compute_checksum(normalized),
                )
            )
            if len(staging_buffer) >= staging_batch_size:
                flush_buffer()
        flush_buffer()
        duration = time.perf_counter() - batch_start
        record_salesforce_batch(status="success", duration_seconds=duration, record_count=len(batch.records))
        logger.info(
            "Salesforce batch ingested",
            extra={
                "importer_run_id": import_run.id,
                "salesforce_job_id": batch.job_id,
                "salesforce_batch_sequence": batch.sequence,
                "salesforce_batch_records": len(batch.records),
                "salesforce_batch_locator": batch.locator,
                "salesforce_batch_duration_seconds": round(duration, 3),
            },
        )

    summary = SalesforceIngestSummary(
        job_id=batch.job_id if batches_processed else "n/a",
        batches_processed=batches_processed,
        records_received=records_received,
        records_staged=records_staged if not dry_run else 0,
        dry_run=dry_run,
        header=header,
        max_modstamp=max_modstamp,
        unmapped_counts=dict(unmapped_counter),
        errors=transform_errors,
    )
    if unmapped_counter:
        for field_name, count in unmapped_counter.items():
            record_salesforce_unmapped(field_name, count)
    _update_import_run_accounts(import_run, summary, field_stats=aggregated_field_stats, target_contributors=target_field_contributors)
    if not dry_run and max_modstamp:
        watermark.last_successful_modstamp = max_modstamp.astimezone(timezone.utc)
        watermark.last_run_id = import_run.id
        watermark.metadata_json = {
            "job_id": summary.job_id,
            "batches_processed": summary.batches_processed,
            "records_received": summary.records_received,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return summary


def _update_import_run_accounts(import_run: ImportRun, summary: SalesforceIngestSummary, *, field_stats: dict[str, FieldImportStats] | None = None, target_contributors: dict[str, set[str]] | None = None) -> None:
    staging_summary = StagingSummary(
        rows_processed=summary.records_received,
        rows_staged=summary.records_staged,
        rows_skipped_blank=0,
        header=summary.header,
        dry_run=summary.dry_run,
        dry_run_rows=(),
    )
    update_staging_counts(import_run, staging_summary)
    metrics = dict(import_run.metrics_json or {})
    salesforce_metrics = metrics.setdefault("salesforce", {})
    salesforce_metrics.update(
        {
            "job_id": summary.job_id,
            "batches_processed": summary.batches_processed,
            "records_received": summary.records_received,
            "records_staged": summary.records_staged,
            "dry_run": summary.dry_run,
            "max_system_modstamp": summary.max_modstamp.isoformat() if summary.max_modstamp else None,
            "unmapped_fields": dict(summary.unmapped_counts),
            "transform_errors": list(summary.errors),
        }
    )
    
    # Store field-level statistics
    if field_stats:
        field_stats_data = metrics.setdefault("field_stats", {}).setdefault("organizations", {})
        source_fields_data = field_stats_data.setdefault("source_fields", {})
        target_fields_data = field_stats_data.setdefault("target_fields", {})
        unmapped_fields_data = field_stats_data.setdefault("unmapped_source_fields", {})
        
        # Store source field statistics
        for source_field, stats in field_stats.items():
            source_fields_data[source_field] = {
                "target": stats.target_field,
                "records_with_value": stats.records_with_value,
                "records_mapped": stats.records_mapped,
                "records_transformed": stats.records_transformed,
                "records_failed_transform": stats.records_failed_transform,
                "records_used_default": stats.records_used_default,
                "total_records_processed": stats.total_records_processed,
                "population_rate": stats.population_rate,
            }
        
        # Store target field statistics
        if target_contributors:
            total_records = summary.records_received
            for target_field, source_fields in target_contributors.items():
                # Calculate completeness for target field
                total_populated = 0
                for source_field in source_fields:
                    if source_field in field_stats:
                        total_populated += field_stats[source_field].records_mapped
                
                target_fields_data[target_field] = {
                    "source_fields": sorted(list(source_fields)),
                    "total_records_populated": total_populated,
                    "total_records_processed": total_records,
                    "completeness_rate": total_populated / total_records if total_records > 0 else 0.0,
                }
        
        # Store unmapped fields
        for unmapped_field, count in summary.unmapped_counts.items():
            unmapped_fields_data[unmapped_field] = {
                "records_with_value": count,
                "total_records_processed": summary.records_received,
            }
    
    import_run.metrics_json = metrics


def _parse_salesforce_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

