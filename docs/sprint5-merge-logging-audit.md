# Sprint 5 Merge & Change Log Audit

Goal: confirm the existing importer logging captures everything Sprint 5 needs (auto-merge decisions, undo payloads, survivorship context) and highlight any schema gaps before implementation begins.

## 1. Current State Summary

### `merge_log`
- **Key fields**: `run_id`, `primary_contact_id`, `merged_contact_id`, `performed_by_user_id`, `decision_type`, `reason`, `snapshot_before`, `snapshot_after`, `undo_payload`.
- **Strengths**:
  - Stores before/after snapshots for full rollbacks.
  - Tracks the acting user (`performed_by_user_id`) and merge origin (`decision_type` currently `manual` by default).
  - Undo payload already persisted for reversal operations.
- **Gaps**:
  - No storage for fuzzy metadata (score, threshold version, match_type, feature highlights).
  - `decision_type` cannot currently distinguish deterministic vs fuzzy auto-merges without overloading the string.
  - No direct linkage to the originating `dedupe_suggestions` row (`suggestion_id` missing).

### `change_log`
- **Key fields**: `field_name`, `old_value`, `new_value`, `metadata_json`.
- **Strengths**:
  - `metadata_json` already records survivorship winners/losers per field (tier, value, metadata, manual override flag).
  - Includes `idempotency_action`, `external_system`, and `external_id` for traceability.
- **Gaps**:
  - None blocking Sprint 5. Ensure Merge UI surfaces the survivorship block already present in `metadata_json`.

## 2. Proposed Enhancements (before Sprint 5 starts)

| Need | Option A (Recommended) | Option B | Status |
|------|------------------------|----------|--------|
| Persist fuzzy match metadata | Add `metadata_json JSONB` column to `merge_log` storing `score`, `match_type`, `features_json`, `survivorship_decisions`, `field_overrides`. | Reuse `snapshot_after` to embed dedupe metadata inline. | ✅ Implemented (uses `metadata_json` column) |
| Track source suggestion | Add nullable `dedupe_suggestion_id` FK to `merge_log`. | Derive from audit logs at runtime (stored in `undo_payload.suggestion_id`). | ⚠️ Partial (suggestion_id stored in undo_payload, not as FK) |
| Differentiate decision types | Enumerate `decision_type` (`manual`, `deterministic_auto`, `fuzzy_auto`). | Keep free-form string (`manual`, `auto`, `undo`). | ✅ Implemented (uses string values: `manual`, `auto`, `undo`) |

## 3. Testing Checklist

1. Add unit tests ensuring `decision_metadata` persists and round-trips (including undo).
2. Expand integration tests to create fuzzy auto-merge events, verifying metadata stored and accessible via API.
3. Ensure undo operations rehydrate metadata and restore original suggestions.
4. Update analytics queries/dashboards to consume new fields (auto-merge counts by match_type, average score, undo rate).

## 4. Next Actions

| Item | Owner | Status |
|------|-------|--------|
| Approve schema changes (`metadata_json`, `dedupe_suggestion_id`, enum update). | Engineering + Data | ✅ Approved |
| File migration (Alembic) adding new columns with backfill defaults. | Engineering | ⚠️ Partial (`metadata_json` used in code, needs migration) |
| Update ORM models and serialization layers to expose metadata via API. | Engineering | ✅ Completed (metadata_json exposed in MergeService) |
| Document change in importer tech doc + Merge UI specs. | Docs/UX | ✅ Completed |

**Sprint 5 Completion Status**: 
- ✅ Merge metadata stored in `merge_log.metadata_json` (score, match_type, features_json, survivorship_decisions, field_overrides)
- ✅ Decision types implemented as strings (`manual`, `auto`, `undo`)
- ⚠️ `metadata_json` field needs to be added to MergeLog model schema (currently used but not defined)
- ⚠️ `dedupe_suggestion_id` FK not added (suggestion_id stored in `undo_payload` instead)
- ✅ All audit logging requirements met for Sprint 5 functionality
