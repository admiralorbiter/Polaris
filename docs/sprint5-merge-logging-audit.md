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

| Need | Option A (Recommended) | Option B | Notes |
|------|------------------------|----------|-------|
| Persist fuzzy match metadata | Add `decision_metadata JSONB` column to `merge_log` storing `score`, `threshold`, `match_type`, `top_features`, `auto_merge` flag. | Reuse `snapshot_after` to embed dedupe metadata inline. | Dedicated column keeps snapshot clean and enables SQL queries/analytics. |
| Track source suggestion | Add nullable `dedupe_suggestion_id` FK to `merge_log`. | Derive from audit logs at runtime. | Link makes it trivial to trace decisions back to suggestions for analytics/undo workflows. |
| Differentiate decision types | Enumerate `decision_type` (`manual`, `deterministic_auto`, `fuzzy_auto`). | Keep free-form string. | Enum improves consistency, complements metrics labels. |

## 3. Testing Checklist

1. Add unit tests ensuring `decision_metadata` persists and round-trips (including undo).
2. Expand integration tests to create fuzzy auto-merge events, verifying metadata stored and accessible via API.
3. Ensure undo operations rehydrate metadata and restore original suggestions.
4. Update analytics queries/dashboards to consume new fields (auto-merge counts by match_type, average score, undo rate).

## 4. Next Actions

| Item | Owner | Due |
|------|-------|-----|
| Approve schema changes (`decision_metadata`, `dedupe_suggestion_id`, enum update). | Engineering + Data | ☐ |
| File migration (Alembic) adding new columns with backfill defaults. | Engineering | ☐ |
| Update ORM models and serialization layers to expose metadata via API. | Engineering | ☐ |
| Document change in importer tech doc + Merge UI specs. | Docs/UX | ☐ |

Once these items are complete, Sprint 5 stories can rely on the enriched logging without additional rework.
