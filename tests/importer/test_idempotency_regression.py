from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from flask_app.importer.idempotency_summary import persist_idempotency_summary
from flask_app.importer.pipeline import (
    load_core_volunteers,
    promote_clean_volunteers,
    run_minimal_dq,
    stage_volunteers_from_csv,
)
from flask_app.models import ContactEmail, ContactPhone, Volunteer, db
from flask_app.models.importer.schema import DedupeDecision, DedupeSuggestion, ExternalIdMap, ImportRun, ImportRunStatus

DATASET_ROOT = Path("ops/testdata/importer_golden_dataset_v0")


def _create_import_run(*, dry_run: bool) -> ImportRun:
    run = ImportRun(
        source="csv",
        adapter="csv",
        status=ImportRunStatus.PENDING,
        dry_run=dry_run,
    )
    db.session.add(run)
    db.session.commit()
    return db.session.get(ImportRun, run.id)


def _execute_ingest_handle(
    handle,
    *,
    dry_run: bool,
    source_system: str = "legacy_csv",
) -> dict[str, object]:
    run = _create_import_run(dry_run=dry_run)
    run.status = ImportRunStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    db.session.commit()
    handle.seek(0)
    staging_summary = stage_volunteers_from_csv(
        run,
        handle,
        source_system=source_system,
        dry_run=dry_run,
    )
    dq_summary = run_minimal_dq(
        run,
        dry_run=dry_run,
        csv_rows=staging_summary.dry_run_rows,
    )
    clean_summary = promote_clean_volunteers(run, dry_run=dry_run)
    core_summary = load_core_volunteers(
        run,
        dry_run=dry_run,
        clean_candidates=clean_summary.candidates,
    )
    run.status = ImportRunStatus.SUCCEEDED
    run.finished_at = datetime.now(timezone.utc)
    summary = persist_idempotency_summary(
        run,
        staging_summary=staging_summary,
        dq_summary=dq_summary,
        clean_summary=clean_summary,
        core_summary=core_summary,
    )
    db.session.commit()
    db.session.refresh(run)
    return {
        "run": run,
        "staging": staging_summary,
        "dq": dq_summary,
        "clean": clean_summary,
        "core": core_summary,
        "summary": summary,
    }


def _execute_ingest(csv_filename: str, *, dry_run: bool = False) -> dict[str, object]:
    csv_path = DATASET_ROOT / csv_filename
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return _execute_ingest_handle(handle, dry_run=dry_run)


def _load_summary_payload(result: dict[str, object]) -> tuple[Path, dict[str, object]]:
    summary = result.get("summary")
    if summary is not None and summary.path:
        summary_path = summary.path
    else:
        summary_path = Path(result["run"].metrics_json["artifacts"]["idempotency_summary_path"])
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    return summary_path, payload


@pytest.fixture()
def seeded_importer(app):
    result = _execute_ingest("volunteers_valid.csv", dry_run=False)
    db.session.expunge_all()
    return result


def test_idempotent_replay_preserves_external_map_and_counts(seeded_importer):
    baseline_snapshot: dict[str, dict[str, object]] = {}
    for id_map in ExternalIdMap.query.order_by(ExternalIdMap.external_id):
        baseline_snapshot[id_map.external_id] = {
            "entity_id": id_map.entity_id,
            "first_seen_at": id_map.first_seen_at,
            "last_seen_at": id_map.last_seen_at,
        }

    baseline_volunteer_count = Volunteer.query.count()

    dry_run_result = _execute_ingest("volunteers_idempotent_replay.csv", dry_run=True)
    dry_core = dry_run_result["core"]
    assert dry_core.dry_run is True
    assert dry_core.rows_created == 0
    assert dry_core.rows_updated == 0
    assert Volunteer.query.count() == baseline_volunteer_count
    dry_summary_path, dry_summary_payload = _load_summary_payload(dry_run_result)
    assert dry_summary_path.exists()
    assert dry_summary_payload["core"]["dry_run"] is True
    assert dry_summary_payload["idempotency"]["diff"] == "none"

    live_result = _execute_ingest("volunteers_idempotent_replay.csv", dry_run=False)
    core_summary = live_result["core"]
    assert core_summary.rows_created == 0
    assert core_summary.rows_updated == 0
    assert core_summary.rows_skipped_no_change == baseline_volunteer_count
    assert core_summary.rows_deduped_auto == 0
    assert ExternalIdMap.query.count() == len(baseline_snapshot)
    summary_path, summary_payload = _load_summary_payload(live_result)
    assert summary_path.exists()
    assert summary_payload["environment"] == "sandbox"
    assert summary_payload["idempotency"]["diff"] == "none"
    assert summary_payload["core"]["rows_skipped_no_change"] == baseline_volunteer_count
    assert summary_payload["idempotency"]["external_id_map"]["new"]["total"] == 0

    for external_id, snapshot in baseline_snapshot.items():
        refreshed = ExternalIdMap.query.filter_by(external_id=external_id).one()
        assert refreshed.entity_id == snapshot["entity_id"]
        assert refreshed.first_seen_at == snapshot["first_seen_at"]
        assert refreshed.last_seen_at >= snapshot["last_seen_at"]
        assert refreshed.run_id == live_result["run"].id

    core_counts = live_result["run"].counts_json["core"]["volunteers"]
    assert core_counts["rows_created"] == 0
    assert core_counts["rows_updated"] == 0
    assert core_counts["rows_skipped_no_change"] == baseline_volunteer_count


def test_changed_payload_updates_existing_contacts(seeded_importer):
    update_result = _execute_ingest("volunteers_changed_payload.csv", dry_run=False)
    core_summary = update_result["core"]
    assert core_summary.rows_created == 0
    assert core_summary.rows_updated == 3
    assert core_summary.rows_skipped_no_change == 0
    summary_path, summary_payload = _load_summary_payload(update_result)
    assert summary_payload["idempotency"]["diff"] == "updated"
    assert summary_payload["core"]["rows_updated"] == 3

    id_map_vol_1 = ExternalIdMap.query.filter_by(external_id="vol-001").one()
    volunteer_1 = db.session.get(Volunteer, id_map_vol_1.entity_id)
    primary_email = ContactEmail.query.filter_by(contact_id=volunteer_1.id, is_primary=True).one()
    assert primary_email.email == "eleanor.rigby+update@example.org"
    primary_phone = ContactPhone.query.filter_by(contact_id=volunteer_1.id, is_primary=True).one()
    assert primary_phone.phone_number == "+14155550999"

    id_map_vol_3 = ExternalIdMap.query.filter_by(external_id="vol-003").one()
    volunteer_3 = db.session.get(Volunteer, id_map_vol_3.entity_id)
    assert any(email.email == "prudence.jones@example.org" for email in volunteer_3.emails)


def test_signal_specific_dedupe_auto_merges(seeded_importer):
    result = _execute_ingest("volunteers_email_vs_phone.csv", dry_run=False)
    core_summary = result["core"]
    assert core_summary.rows_created == 0
    assert core_summary.rows_deduped_auto == 2
    assert Volunteer.query.count() == 3
    summary_path, summary_payload = _load_summary_payload(result)
    assert summary_payload["idempotency"]["diff"] in {"updated", "created"}

    suggestions = DedupeSuggestion.query.filter_by(run_id=result["run"].id).all()
    assert len(suggestions) == 2
    decisions = {suggestion.decision for suggestion in suggestions}
    assert decisions == {DedupeDecision.AUTO_MERGED}
    match_types = {suggestion.match_type for suggestion in suggestions}
    assert match_types == {"email", "phone"}


def test_partial_replay_subset_is_idempotent(seeded_importer):
    csv_buffer = io.StringIO(
        "external_system,external_id,first_name,last_name,email,phone,source_updated_at\n"
        "legacy_csv,vol-001,Eleanor,Rigby,eleanor.rigby@example.org,+14155550101,2025-10-01T12:00:00Z\n"
    )
    result = _execute_ingest_handle(csv_buffer, dry_run=False)
    core_summary = result["core"]
    assert core_summary.rows_created == 0
    assert core_summary.rows_updated == 0
    assert core_summary.rows_skipped_no_change == 1
    summary_path, summary_payload = _load_summary_payload(result)
    assert summary_payload["idempotency"]["diff"] == "none"
    assert summary_payload["core"]["rows_skipped_no_change"] == 1

    id_map = ExternalIdMap.query.filter_by(external_id="vol-001").one()
    assert id_map.run_id == result["run"].id
