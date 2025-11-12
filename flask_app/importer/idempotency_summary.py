from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from flask import current_app, has_app_context

from flask_app.importer.utils import ensure_json_serializable, resolve_artifact_directory
from flask_app.models import db
from flask_app.models.importer.schema import ExternalIdMap, ImportRun

_IDENTIFIER_SAMPLE_LIMIT = 25


@dataclass(frozen=True)
class IdempotencySummary:
    payload: dict[str, Any]
    path: Path


def _sample_identifiers(identifiers: Iterable[str]) -> dict[str, Any]:
    identifiers = list(identifiers)
    return {
        "items": identifiers[:_IDENTIFIER_SAMPLE_LIMIT],
        "total": len(identifiers),
    }


def _collect_mapping_stats(run: ImportRun) -> dict[str, Any]:
    base_query = db.session.query(ExternalIdMap).filter(ExternalIdMap.entity_type == "volunteer")
    mapping_index: dict[tuple[str | None, str | None], ExternalIdMap] = {}

    if run.id is not None:
        for mapping in base_query.filter(ExternalIdMap.run_id == run.id):
            mapping_index[(mapping.external_system, mapping.external_id)] = mapping

    if run.started_at is not None:
        recent_query = base_query.filter(ExternalIdMap.last_seen_at >= run.started_at)
        for mapping in recent_query:
            mapping_index.setdefault((mapping.external_system, mapping.external_id), mapping)

    mappings = sorted(
        mapping_index.values(),
        key=lambda item: (item.external_system or "", item.external_id or ""),
    )
    touched_identifiers = [
        f"{mapping.external_system}:{mapping.external_id}" for mapping in mappings if mapping.external_id is not None
    ]
    new_identifiers = [
        f"{mapping.external_system}:{mapping.external_id}"
        for mapping in mappings
        if mapping.external_id is not None and mapping.first_seen_at == mapping.last_seen_at
    ]
    total_active = (
        db.session.query(ExternalIdMap)
        .filter(ExternalIdMap.entity_type == "volunteer", ExternalIdMap.is_active.is_(True))
        .count()
    )
    return {
        "touched": _sample_identifiers(touched_identifiers),
        "new": _sample_identifiers(new_identifiers),
        "total_active": total_active,
    }


def _determine_diff(core_summary, mapping_stats: dict[str, Any]) -> str:
    # Prioritize core_summary over mapping_stats - mapping entries are metadata, not data changes
    if core_summary.rows_created:
        return "created"
    if core_summary.rows_updated:
        return "updated"
    if core_summary.rows_skipped_no_change:
        return "none"
    # If no core changes but new mappings exist, still consider it "created" for tracking
    if mapping_stats["new"]["total"]:
        return "created"
    return "none"


def persist_idempotency_summary(
    run: ImportRun,
    *,
    staging_summary,
    dq_summary,
    clean_summary,
    core_summary,
    fuzzy_summary=None,
) -> IdempotencySummary | None:
    """
    Persist an ``idempotency_summary.json`` artifact capturing core replay metrics.

    Returns:
        IdempotencySummary with payload metadata and target path, or ``None`` if no
        app context is available.
    """

    if not has_app_context():
        return None

    environment = current_app.config.get("IMPORTER_METRICS_ENV", "sandbox")
    generated_at = datetime.now(timezone.utc).isoformat()
    mapping_stats = _collect_mapping_stats(run)
    summary = {
        "generated_at": generated_at,
        "environment": environment,
        "run": {
            "id": run.id,
            "source": getattr(run, "source", None),
            "dry_run": bool(getattr(run, "dry_run", False)),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        },
        "staging": {
            "rows_processed": staging_summary.rows_processed,
            "rows_staged": staging_summary.rows_staged,
            "rows_skipped_blank": staging_summary.rows_skipped_blank,
            "dry_run": staging_summary.dry_run,
        },
        "dq": {
            "rows_evaluated": dq_summary.rows_evaluated,
            "rows_validated": dq_summary.rows_validated,
            "rows_quarantined": dq_summary.rows_quarantined,
            "rule_counts": dict(dq_summary.rule_counts),
            "dry_run": dq_summary.dry_run,
        },
        "clean": {
            "rows_considered": clean_summary.rows_considered,
            "rows_promoted": clean_summary.rows_promoted,
            "rows_skipped": clean_summary.rows_skipped,
            "dry_run": clean_summary.dry_run,
        },
        "core": {
            "rows_processed": core_summary.rows_processed,
            "rows_created": core_summary.rows_created,
            "rows_updated": core_summary.rows_updated,
            "rows_reactivated": core_summary.rows_reactivated,
            "rows_deduped_auto": core_summary.rows_deduped_auto,
            "rows_skipped_duplicates": core_summary.rows_skipped_duplicates,
            "rows_skipped_no_change": core_summary.rows_skipped_no_change,
            "rows_missing_external_id": core_summary.rows_missing_external_id,
            "rows_soft_deleted": core_summary.rows_soft_deleted,
            "dry_run": core_summary.dry_run,
        },
        "idempotency": {
            "external_id_map": mapping_stats,
            "diff": _determine_diff(core_summary, mapping_stats),
        },
    }

    if fuzzy_summary is not None:
        summary["fuzzy"] = {
            "rows_considered": fuzzy_summary.rows_considered,
            "suggestions_created": fuzzy_summary.suggestions_created,
            "high_confidence": fuzzy_summary.high_confidence,
            "review_band": fuzzy_summary.review_band,
            "low_score": fuzzy_summary.low_score,
            "skipped_no_signals": fuzzy_summary.skipped_no_signals,
            "skipped_no_candidates": fuzzy_summary.skipped_no_candidates,
            "skipped_deterministic": fuzzy_summary.skipped_deterministic,
            "dry_run": fuzzy_summary.dry_run,
        }

    artifact_root = resolve_artifact_directory(current_app)
    run_dir = artifact_root / f"run_{run.id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "idempotency_summary.json"
    summary_path.write_text(
        json.dumps(ensure_json_serializable(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    metrics = dict(run.metrics_json or {})
    artifacts = metrics.setdefault("artifacts", {})
    artifacts["idempotency_summary_path"] = str(summary_path)
    artifacts["idempotency_environment"] = environment
    run.metrics_json = metrics

    return IdempotencySummary(payload=summary, path=summary_path)
