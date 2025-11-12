"""
Merge service for handling manual dedupe candidate reviews and merges.

This service provides the backend logic for the Merge UI, handling merge operations,
candidate rejection/deferral, and queue management.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from config.survivorship import load_profile
from flask_app.importer.pipeline.clean import CleanVolunteerPayload
from flask_app.importer.pipeline.load_core import (
    _apply_email_change,
    _apply_phone_change,
    _build_core_snapshot,
    _build_incoming_payload,
    _build_incoming_provenance,
    _build_verified_snapshot,
    _profile_field_names,
    _resolve_manual_overrides,
    _serialize_change_value,
)
from flask_app.importer.pipeline.survivorship import apply_survivorship, summarize_decisions
from flask_app.models import ChangeLogEntry, ExternalIdMap, MergeLog, Volunteer, db
from flask_app.models.importer.schema import CleanVolunteer, DedupeDecision, DedupeSuggestion, ImportRun


@dataclass
class CandidateDetails:
    """Detailed information about a dedupe candidate for UI display."""

    suggestion_id: int
    score: float | None
    match_type: str | None
    features_json: dict | None
    primary_contact: dict[str, Any]
    candidate_contact: dict[str, Any] | None
    staging_data: dict[str, Any] | None
    survivorship_preview: dict[str, Any]
    run_id: int
    created_at: datetime


@dataclass
class QueueStats:
    """Statistics about the review queue."""

    total_pending: int
    total_review_band: int
    total_high_confidence: int
    aging_buckets: dict[str, int]


class MergeService:
    """Service for handling merge operations and candidate management."""

    def __init__(self, session: Session | None = None):
        self.session = session or db.session

    def get_review_queue(
        self,
        *,
        status: str | None = None,
        match_type: str | None = None,
        run_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[DedupeSuggestion], int]:
        """
        Get list of dedupe candidates for review.

        Args:
            status: Filter by decision status ('pending', 'deferred', etc.)
            match_type: Filter by match type ('fuzzy_high', 'fuzzy_review', etc.)
            run_id: Filter by import run ID
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            Tuple of (candidates list, total count)
        """
        query = self.session.query(DedupeSuggestion).options(
            joinedload(DedupeSuggestion.primary_contact),
            joinedload(DedupeSuggestion.candidate_contact),
            joinedload(DedupeSuggestion.staging_row),
            joinedload(DedupeSuggestion.import_run),
        )

        if status:
            if status == "pending":
                query = query.filter(DedupeSuggestion.decision == DedupeDecision.PENDING)
            elif status == "deferred":
                query = query.filter(DedupeSuggestion.decision == DedupeDecision.DEFERRED)
            elif status == "review":
                query = query.filter(
                    DedupeSuggestion.decision == DedupeDecision.PENDING,
                    DedupeSuggestion.match_type.in_(["fuzzy_review", "fuzzy_high"]),
                )

        if match_type:
            query = query.filter(DedupeSuggestion.match_type == match_type)

        if run_id:
            query = query.filter(DedupeSuggestion.run_id == run_id)

        # Only return suggestions with valid primary contact
        query = query.filter(DedupeSuggestion.primary_contact_id.isnot(None))

        total = query.count()

        # Order by score descending, then by created_at (oldest first for pending)
        query = query.order_by(
            DedupeSuggestion.score.desc().nulls_last(),
            DedupeSuggestion.id.asc(),
        )

        candidates = query.offset(offset).limit(limit).all()

        return candidates, total

    def get_candidate_details(self, suggestion_id: int) -> CandidateDetails:
        """
        Get detailed information about a dedupe candidate.

        Args:
            suggestion_id: ID of the DedupeSuggestion

        Returns:
            CandidateDetails with full candidate information

        Raises:
            ValueError: If suggestion not found or invalid
        """
        suggestion = (
            self.session.query(DedupeSuggestion)
            .options(
                joinedload(DedupeSuggestion.primary_contact),
                joinedload(DedupeSuggestion.candidate_contact),
                joinedload(DedupeSuggestion.staging_row),
                joinedload(DedupeSuggestion.import_run),
            )
            .filter_by(id=suggestion_id)
            .first()
        )

        if not suggestion:
            raise ValueError(f"Dedupe suggestion {suggestion_id} not found")

        if not suggestion.primary_contact_id:
            raise ValueError(f"Dedupe suggestion {suggestion_id} has no primary contact")

        primary_volunteer = self.session.get(Volunteer, suggestion.primary_contact_id)
        if not primary_volunteer:
            raise ValueError(f"Primary contact {suggestion.primary_contact_id} not found")

        # Build primary contact snapshot
        profile = load_profile()
        field_names = _profile_field_names(profile)
        primary_snapshot = _build_core_snapshot(primary_volunteer, field_names)
        primary_data = {
            "id": primary_volunteer.id,
            "first_name": primary_volunteer.first_name,
            "last_name": primary_volunteer.last_name,
            "snapshot": primary_snapshot,
            "updated_at": primary_volunteer.updated_at.isoformat() if primary_volunteer.updated_at else None,
        }

        # Build candidate data
        candidate_data: dict[str, Any] | None = None
        staging_data: dict[str, Any] | None = None
        clean_volunteer: CleanVolunteer | None = None

        if suggestion.candidate_contact_id:
            # Candidate is already a core volunteer
            candidate_volunteer = self.session.get(Volunteer, suggestion.candidate_contact_id)
            if candidate_volunteer:
                candidate_snapshot = _build_core_snapshot(candidate_volunteer, field_names)
                candidate_data = {
                    "id": candidate_volunteer.id,
                    "first_name": candidate_volunteer.first_name,
                    "last_name": candidate_volunteer.last_name,
                    "snapshot": candidate_snapshot,
                    "updated_at": candidate_volunteer.updated_at.isoformat()
                    if candidate_volunteer.updated_at
                    else None,
                }
        elif suggestion.staging_row:
            # Candidate is in staging
            staging_row = suggestion.staging_row
            payload = staging_row.normalized_json or {}
            staging_data = {
                "id": staging_row.id,
                "payload": payload,
                "sequence_number": staging_row.sequence_number,
            }
            # Build incoming payload from staging
            clean_volunteer = self.session.query(CleanVolunteer).filter_by(staging_volunteer_id=staging_row.id).first()
            if clean_volunteer:
                candidate_payload = CleanVolunteerPayload(
                    staging_volunteer_id=staging_row.id,
                    first_name=clean_volunteer.first_name or "",
                    last_name=clean_volunteer.last_name or "",
                    email=clean_volunteer.email,
                    phone_e164=clean_volunteer.phone_e164,
                    external_system=clean_volunteer.external_system or "csv",
                    external_id=clean_volunteer.external_id,
                    checksum=clean_volunteer.checksum,
                    normalized_payload=payload,
                )
                incoming_payload = _build_incoming_payload(candidate_payload, field_names)
                candidate_data = {
                    "id": None,
                    "first_name": clean_volunteer.first_name,
                    "last_name": clean_volunteer.last_name,
                    "snapshot": incoming_payload,
                    "updated_at": None,
                }

        # Build survivorship preview
        if candidate_data:
            incoming_payload = candidate_data["snapshot"]
            manual_overrides = _resolve_manual_overrides(
                suggestion.import_run,
                suggestion.staging_row,
                field_names,
            )
            verified_snapshot = _build_verified_snapshot(primary_volunteer, field_names)

            # Build incoming provenance - handle case where we don't have a candidate payload
            if clean_volunteer and suggestion.staging_row:
                payload_obj = CleanVolunteerPayload(
                    staging_volunteer_id=suggestion.staging_row.id,
                    first_name=clean_volunteer.first_name or "",
                    last_name=clean_volunteer.last_name or "",
                    email=clean_volunteer.email,
                    phone_e164=clean_volunteer.phone_e164,
                    external_system=clean_volunteer.external_system or "csv",
                    external_id=clean_volunteer.external_id,
                    checksum=clean_volunteer.checksum,
                    normalized_payload=clean_volunteer.payload_json or {},
                )
                incoming_provenance = _build_incoming_provenance(
                    suggestion.import_run,
                    payload_obj,
                    suggestion.staging_row,
                )
            else:
                # Fallback when we don't have staging data
                incoming_provenance = {
                    "source_run_id": suggestion.run_id,
                }

            survivorship_result = apply_survivorship(
                profile=profile,
                incoming_payload=incoming_payload,
                core_snapshot=primary_snapshot,
                manual_overrides=manual_overrides,
                verified_snapshot=verified_snapshot,
                incoming_provenance=incoming_provenance,
            )

            survivorship_preview = {
                "resolved_values": survivorship_result.resolved_values,
                "decisions": [
                    {
                        "field_name": decision.field_name,
                        "group_name": decision.group_name,
                        "winner": {
                            "tier": decision.winner.tier,
                            "value": decision.winner.value,
                        },
                        "changed": decision.changed,
                        "manual_override": decision.manual_override,
                        "reason": decision.reason,
                    }
                    for decision in survivorship_result.decisions
                ],
                "stats": survivorship_result.stats,
            }
        else:
            survivorship_preview = {}

        return CandidateDetails(
            suggestion_id=suggestion.id,
            score=float(suggestion.score) if suggestion.score else None,
            match_type=suggestion.match_type,
            features_json=suggestion.features_json or {},
            primary_contact=primary_data,
            candidate_contact=candidate_data,
            staging_data=staging_data,
            survivorship_preview=survivorship_preview,
            run_id=suggestion.run_id,
            created_at=suggestion.import_run.created_at if suggestion.import_run else datetime.now(timezone.utc),
        )

    def execute_merge(
        self,
        suggestion_id: int,
        *,
        user_id: int,
        field_overrides: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> MergeLog:
        """
        Execute a merge operation for a dedupe candidate.

        Args:
            suggestion_id: ID of the DedupeSuggestion
            user_id: ID of the user performing the merge
            field_overrides: Optional dict of field_name -> value to override survivorship
            notes: Optional notes about the merge

        Returns:
            Created MergeLog entry

        Raises:
            ValueError: If suggestion not found or invalid
            RuntimeError: If merge fails
        """
        suggestion = (
            self.session.query(DedupeSuggestion)
            .options(
                joinedload(DedupeSuggestion.primary_contact),
                joinedload(DedupeSuggestion.candidate_contact),
                joinedload(DedupeSuggestion.staging_row),
                joinedload(DedupeSuggestion.import_run),
            )
            .filter_by(id=suggestion_id)
            .first()
        )

        if not suggestion:
            raise ValueError(f"Dedupe suggestion {suggestion_id} not found")

        if suggestion.decision != DedupeDecision.PENDING:
            raise ValueError(f"Cannot merge suggestion {suggestion_id} with decision {suggestion.decision}")

        if not suggestion.primary_contact_id:
            raise ValueError(f"Dedupe suggestion {suggestion_id} has no primary contact")

        primary_volunteer = self.session.get(Volunteer, suggestion.primary_contact_id)
        if not primary_volunteer:
            raise ValueError(f"Primary contact {suggestion.primary_contact_id} not found")

        # Determine candidate volunteer
        candidate_volunteer: Volunteer | None = None
        clean_volunteer: CleanVolunteer | None = None

        if suggestion.candidate_contact_id:
            candidate_volunteer = self.session.get(Volunteer, suggestion.candidate_contact_id)
        elif suggestion.staging_row:
            # Need to create volunteer from staging or find existing
            clean_volunteer = (
                self.session.query(CleanVolunteer).filter_by(staging_volunteer_id=suggestion.staging_row.id).first()
            )
            if clean_volunteer and clean_volunteer.core_volunteer_id:
                candidate_volunteer = self.session.get(Volunteer, clean_volunteer.core_volunteer_id)

        # If no candidate volunteer exists, we're merging staging into primary
        # This is the common case for fuzzy dedupe

        # Build snapshots before merge
        profile = load_profile()
        field_names = _profile_field_names(profile)
        snapshot_before = {
            "primary": _build_core_snapshot(primary_volunteer, field_names),
        }

        # Build incoming payload
        if candidate_volunteer:
            incoming_payload = _build_core_snapshot(candidate_volunteer, field_names)
            snapshot_before["candidate"] = incoming_payload
        elif suggestion.staging_row and clean_volunteer:
            payload_obj = CleanVolunteerPayload(
                staging_volunteer_id=suggestion.staging_row.id,
                first_name=clean_volunteer.first_name or "",
                last_name=clean_volunteer.last_name or "",
                email=clean_volunteer.email,
                phone_e164=clean_volunteer.phone_e164,
                external_system=clean_volunteer.external_system or "csv",
                external_id=clean_volunteer.external_id,
                checksum=clean_volunteer.checksum,
                normalized_payload=clean_volunteer.payload_json or {},
            )
            incoming_payload = _build_incoming_payload(payload_obj, field_names)
            snapshot_before["staging"] = incoming_payload
        else:
            incoming_payload = {}

        # Apply field overrides if provided
        manual_overrides: dict[str, dict[str, Any]] = {}
        if field_overrides:
            for field_name, value in field_overrides.items():
                manual_overrides[field_name] = {
                    "value": value,
                    "source": "manual_override",
                    "user_id": user_id,
                }

        # Apply survivorship
        core_snapshot = _build_core_snapshot(primary_volunteer, field_names)
        existing_overrides = _resolve_manual_overrides(
            suggestion.import_run,
            suggestion.staging_row,
            field_names,
        )
        manual_overrides.update(existing_overrides)
        verified_snapshot = _build_verified_snapshot(primary_volunteer, field_names)

        # Build incoming provenance - handle case where we don't have a candidate payload
        if clean_volunteer and suggestion.staging_row:
            # Build a payload object for provenance
            payload_obj = CleanVolunteerPayload(
                staging_volunteer_id=suggestion.staging_row.id,
                first_name=clean_volunteer.first_name or "",
                last_name=clean_volunteer.last_name or "",
                email=clean_volunteer.email,
                phone_e164=clean_volunteer.phone_e164,
                external_system=clean_volunteer.external_system or "csv",
                external_id=clean_volunteer.external_id,
                checksum=clean_volunteer.checksum,
                normalized_payload=clean_volunteer.payload_json or {},
            )
            incoming_provenance = _build_incoming_provenance(
                suggestion.import_run,
                payload_obj,
                suggestion.staging_row,
            )
        else:
            # Fallback when we don't have staging data
            incoming_provenance = {
                "source_run_id": suggestion.run_id,
            }

        survivorship_result = apply_survivorship(
            profile=profile,
            incoming_payload=incoming_payload,
            core_snapshot=core_snapshot,
            manual_overrides=manual_overrides if manual_overrides else None,
            verified_snapshot=verified_snapshot,
            incoming_provenance=incoming_provenance,
        )

        # Apply changes to primary volunteer
        changes: dict[str, tuple[Any, Any]] = {}
        for field_name, final_value in survivorship_result.resolved_values.items():
            if field_name == "email":
                before, after, changed = _apply_email_change(primary_volunteer, final_value)
                if changed:
                    changes[field_name] = (before, after)
            elif field_name == "phone_e164":
                before, after, changed = _apply_phone_change(primary_volunteer, final_value)
                if changed:
                    changes[field_name] = (before, after)
            elif hasattr(primary_volunteer, field_name):
                before = getattr(primary_volunteer, field_name)
                if before != final_value:
                    setattr(primary_volunteer, field_name, final_value)
                    changes[field_name] = (before, final_value)

        # Update external_id_map entries for merged contact
        merged_contact_id = suggestion.candidate_contact_id or (candidate_volunteer.id if candidate_volunteer else None)
        if merged_contact_id:
            # Find all external_id_map entries pointing to merged contact
            merged_maps = (
                self.session.query(ExternalIdMap)
                .filter_by(entity_type="volunteer", entity_id=merged_contact_id, is_active=True)
                .all()
            )
            for map_entry in merged_maps:
                # Check if primary already has this external_id
                existing = (
                    self.session.query(ExternalIdMap)
                    .filter_by(
                        entity_type="volunteer",
                        external_system=map_entry.external_system,
                        external_id=map_entry.external_id,
                        entity_id=primary_volunteer.id,
                    )
                    .first()
                )
                if existing:
                    # Deactivate the duplicate
                    map_entry.soft_delete(reason="merged_into_contact")
                else:
                    # Update to point to primary
                    map_entry.entity_id = primary_volunteer.id
                    map_entry.mark_seen()

        # Also handle staging external_id if present
        if suggestion.staging_row and clean_volunteer and clean_volunteer.external_id:
            staging_map = (
                self.session.query(ExternalIdMap)
                .filter_by(
                    entity_type="volunteer",
                    external_system=clean_volunteer.external_system or "csv",
                    external_id=clean_volunteer.external_id,
                )
                .first()
            )
            if staging_map and staging_map.entity_id != primary_volunteer.id:
                if staging_map.entity_id == (candidate_volunteer.id if candidate_volunteer else None):
                    # Update to point to primary
                    staging_map.entity_id = primary_volunteer.id
                    staging_map.mark_seen()
                else:
                    # Check if primary already has this external_id
                    existing = (
                        self.session.query(ExternalIdMap)
                        .filter_by(
                            entity_type="volunteer",
                            external_system=staging_map.external_system,
                            external_id=staging_map.external_id,
                            entity_id=primary_volunteer.id,
                        )
                        .first()
                    )
                    if existing:
                        staging_map.soft_delete(reason="merged_into_contact")
                    else:
                        staging_map.entity_id = primary_volunteer.id
                        staging_map.mark_seen()

        # Build snapshot after merge
        snapshot_after = {
            "primary": _build_core_snapshot(primary_volunteer, field_names),
        }

        # Create merge log entry
        merge_log = MergeLog(
            run_id=suggestion.run_id,
            primary_contact_id=primary_volunteer.id,
            merged_contact_id=merged_contact_id or primary_volunteer.id,  # Use primary if no candidate
            performed_by_user_id=user_id,
            decision_type="manual",
            reason=notes,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            undo_payload={
                "suggestion_id": suggestion_id,
                "merged_contact_id": merged_contact_id,
                "changes": {
                    k: {"before": _serialize_change_value(v[0]), "after": _serialize_change_value(v[1])}
                    for k, v in changes.items()
                },
            },
        )
        merge_log.metadata_json = {
            "score": float(suggestion.score) if suggestion.score else None,
            "match_type": suggestion.match_type,
            "features_json": suggestion.features_json,
            "survivorship_decisions": summarize_decisions(survivorship_result.decisions),
            "field_overrides": field_overrides,
        }
        self.session.add(merge_log)

        # Create change log entries
        for field_name, (before, after) in changes.items():
            decision = next((d for d in survivorship_result.decisions if d.field_name == field_name), None)
            metadata = {
                "merge_log_id": merge_log.id,
                "suggestion_id": suggestion_id,
                "change_source": "manual_merge",
            }
            if decision:
                metadata["survivorship"] = {
                    "winner": {
                        "tier": decision.winner.tier,
                        "value": _serialize_change_value(decision.winner.value),
                    },
                    "manual_override": decision.manual_override,
                    "reason": decision.reason,
                }

            change_entry = ChangeLogEntry(
                run_id=suggestion.run_id,
                entity_type="volunteer",
                entity_id=primary_volunteer.id,
                field_name=field_name,
                old_value=_serialize_change_value(before),
                new_value=_serialize_change_value(after),
                change_source="manual_merge",
                changed_by_user_id=user_id,
                metadata_json=metadata,
            )
            self.session.add(change_entry)

        # Update suggestion decision
        suggestion.decision = DedupeDecision.ACCEPTED
        suggestion.decided_at = datetime.now(timezone.utc)
        suggestion.decided_by_user_id = user_id
        suggestion.decision_notes = notes

        # If candidate volunteer exists, we might want to soft-delete it
        # For now, we'll leave it but mark it as merged in external_id_map

        # Record metrics (TODO: add manual dedupe metric to ImporterMonitoring)
        # ImporterMonitoring.record_dedupe_manual(match_type=suggestion.match_type or "unknown")

        self.session.flush()

        return merge_log

    def reject_candidate(
        self,
        suggestion_id: int,
        *,
        user_id: int,
        notes: str | None = None,
    ) -> DedupeSuggestion:
        """
        Mark a candidate as rejected (not a duplicate).

        Args:
            suggestion_id: ID of the DedupeSuggestion
            user_id: ID of the user rejecting
            notes: Optional reason for rejection

        Returns:
            Updated DedupeSuggestion

        Raises:
            ValueError: If suggestion not found
        """
        suggestion = self.session.get(DedupeSuggestion, suggestion_id)
        if not suggestion:
            raise ValueError(f"Dedupe suggestion {suggestion_id} not found")

        if suggestion.decision not in (DedupeDecision.PENDING, DedupeDecision.DEFERRED):
            raise ValueError(f"Cannot reject suggestion {suggestion_id} with decision {suggestion.decision}")

        suggestion.decision = DedupeDecision.REJECTED
        suggestion.decided_at = datetime.now(timezone.utc)
        suggestion.decided_by_user_id = user_id
        suggestion.decision_notes = notes

        self.session.flush()

        return suggestion

    def defer_candidate(
        self,
        suggestion_id: int,
        *,
        user_id: int,
        notes: str | None = None,
    ) -> DedupeSuggestion:
        """
        Defer a candidate decision for later review.

        Args:
            suggestion_id: ID of the DedupeSuggestion
            user_id: ID of the user deferring
            notes: Optional reason for deferral

        Returns:
            Updated DedupeSuggestion

        Raises:
            ValueError: If suggestion not found
        """
        suggestion = self.session.get(DedupeSuggestion, suggestion_id)
        if not suggestion:
            raise ValueError(f"Dedupe suggestion {suggestion_id} not found")

        if suggestion.decision != DedupeDecision.PENDING:
            raise ValueError(f"Cannot defer suggestion {suggestion_id} with decision {suggestion.decision}")

        suggestion.decision = DedupeDecision.DEFERRED
        suggestion.decided_at = datetime.now(timezone.utc)
        suggestion.decided_by_user_id = user_id
        suggestion.decision_notes = notes

        self.session.flush()

        return suggestion

    def get_queue_stats(self) -> QueueStats:
        """
        Get statistics about the review queue.

        Returns:
            QueueStats with counts and aging information
        """
        now = datetime.now(timezone.utc)

        # Total pending
        total_pending = (
            self.session.query(func.count(DedupeSuggestion.id))
            .filter(DedupeSuggestion.decision == DedupeDecision.PENDING)
            .filter(DedupeSuggestion.primary_contact_id.isnot(None))
            .scalar()
            or 0
        )

        # Review band (0.80-0.95)
        total_review_band = (
            self.session.query(func.count(DedupeSuggestion.id))
            .filter(
                DedupeSuggestion.decision == DedupeDecision.PENDING,
                DedupeSuggestion.match_type == "fuzzy_review",
                DedupeSuggestion.primary_contact_id.isnot(None),
            )
            .scalar()
            or 0
        )

        # High confidence (≥0.95)
        total_high_confidence = (
            self.session.query(func.count(DedupeSuggestion.id))
            .filter(
                DedupeSuggestion.decision == DedupeDecision.PENDING,
                DedupeSuggestion.match_type == "fuzzy_high",
                DedupeSuggestion.primary_contact_id.isnot(None),
            )
            .scalar()
            or 0
        )

        # Aging buckets (based on import run created_at)
        # Use timedelta for database-agnostic date arithmetic
        day_ago = now - timedelta(days=1)
        two_days_ago = now - timedelta(days=2)

        aging_24h = (
            self.session.query(func.count(DedupeSuggestion.id))
            .join(ImportRun)
            .filter(
                DedupeSuggestion.decision == DedupeDecision.PENDING,
                DedupeSuggestion.primary_contact_id.isnot(None),
                ImportRun.created_at >= day_ago,
            )
            .scalar()
            or 0
        )

        aging_48h = (
            self.session.query(func.count(DedupeSuggestion.id))
            .join(ImportRun)
            .filter(
                DedupeSuggestion.decision == DedupeDecision.PENDING,
                DedupeSuggestion.primary_contact_id.isnot(None),
                ImportRun.created_at < day_ago,
                ImportRun.created_at >= two_days_ago,
            )
            .scalar()
            or 0
        )

        aging_older = (
            self.session.query(func.count(DedupeSuggestion.id))
            .join(ImportRun)
            .filter(
                DedupeSuggestion.decision == DedupeDecision.PENDING,
                DedupeSuggestion.primary_contact_id.isnot(None),
                ImportRun.created_at < two_days_ago,
            )
            .scalar()
            or 0
        )

        return QueueStats(
            total_pending=total_pending,
            total_review_band=total_review_band,
            total_high_confidence=total_high_confidence,
            aging_buckets={
                "<24h": aging_24h,
                "24-48h": aging_48h,
                ">48h": aging_older,
            },
        )


__all__ = ["MergeService", "CandidateDetails", "QueueStats"]
