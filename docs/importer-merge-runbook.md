# Importer Merge Workflow Runbook (Sprint 5)

Audience: Data Stewards and Admins who will review fuzzy dedupe candidates and manage merge decisions.

## 1. Access & Permissions

- **Roles**
  - **Admin**: Full access (review, merge, undo, adjust thresholds).
  - **Data Steward**: Review queue access, can merge/reject/defer; may undo merges they performed (pending final policy decision).
  - **Viewer**: Read-only access to review queue, cannot take action.
- Verify your role under `Admin ▸ Users ▸ Roles` before Sprint 5 launches.

## 2. Understanding Duplicate Detection

**Important**: The system has two types of duplicate detection:

1. **Import-time dedupe** (automatic):
   - Runs automatically on every import
   - Checks **new records** from the import against **existing volunteers** in the database
   - One-way comparison: new → existing
   - Prevents new duplicates from being created
   - Candidates appear in the review queue automatically

2. **Manual scan** (periodic):
   - Must be run manually via the Duplicate Review UI
   - Scans **all existing volunteers** against **each other** to find duplicates
   - Two-way comparison: existing ↔ existing
   - Finds duplicates in historical data (e.g., records imported before duplicate review existed, or created through other means)
   - **When to run**: Periodically (e.g., monthly) or after bulk imports from legacy systems

**Why many duplicates aren't checked on import:**
- Import-time dedupe only checks new records against existing ones
- Duplicates among existing volunteers require a manual scan
- This design is intentional for performance: running a full scan on every import would be too slow

## 3. Daily Checklist

1. Open `Admin ▸ Importer ▸ Duplicate Review`.
2. Filter by `Status = Needs Review` (queue badges show total + aging).
3. Work items from oldest to newest, focusing on SLA agreed with Ops (default: 1 business day).
4. Monitor "Auto merges today" and "Undo rate" cards for anomalies.
5. **Periodic task**: Run manual scan for existing volunteers (monthly or after bulk imports).

## 4. Reviewing a Candidate

Each candidate panel shows:

- **Score & band**: numeric score (0–1). Badge indicates `Auto`, `Review`, or `New`. Scores ≥0.95 auto-merged; 0.80–0.95 require review.
- **Top signals**: key features contributing to the score (name similarity, DOB match, address distance, alternate email/phone matches).
- **Source payloads**:
  - Candidate (staged record) with normalized fields.
  - Primary contact (core record) with last updated timestamp and manual edits flagged.
- **Survivorship preview**: field-level changes that would occur if merged (values, tiers, manual override indicator).

### Decision Steps

1. **Confirm identity**
   - Compare name variations (nickname vs legal name).
   - Check DOB, address, employer/school, alternate emails/phones.
   - Review audit trail for manual edits (ensures we do not undo steward overrides unintentionally).
2. **Choose an action**
   - **Merge**: Confident it is the same person. Optionally adjust winners per field if manual data should stay.
   - **Not a duplicate**: Confident they are different people (provide reason for audit log).
   - **Defer**: Unsure; leave comment with open question. Candidate remains in queue and surfaces in backlog reporting.

## 5. Merge Execution

1. Click **Review** on a candidate.
2. Inspect “Survivorship outcome” table; edit field winners if necessary.
3. Provide optional steward note (recommended for tricky cases).
4. Click **Merge**.
5. Verify success toast and that the candidate disappears from the queue.

### Post-merge expectations

- `MergeLog` entry created with snapshots + dedupe metadata.
- `ChangeLogEntry` entries emitted for each field change (visible under volunteer detail ▸ Audit).
- `importer_dedupe_manual_total{match_type}` counter increments.
- Manual merge appears in run dashboard with steward attribution.

## 6. Undoing a Merge

Use undo when a merge was incorrect or premature.

1. Navigate to `Admin ▸ Importer ▸ Merge History` (or volunteer detail ▸ Merge history).
2. Locate the merge entry (filter by steward, date, or score).
3. Click **Undo merge**.
4. Review the undo payload summary (contacts, field changes, ID map entries) and confirm.
5. Verify the queue shows separate volunteers again; `MergeLog.undo_payload` records the reversal.

**Important**: Undo availability may be limited to Admins (confirm final policy). Always document the reason in the prompted text box for compliance.

## 7. Handling Auto-merges

- Auto-merges (deterministic + fuzzy high confidence) appear in Merge History with `decision_type = deterministic_auto` or `fuzzy_auto`.
- They do **not** require steward action but should be spot-checked daily:
  - Review the Auto merges table for outliers (unexpected names, addresses).
  - Undo any incorrect auto-merge and flag the record to Ops for threshold review.
- Monitor **Undo rate**; escalate to Engineering if >5% within 7-day window.

## 8. Escalation & Exceptions

| Scenario | Action |
|----------|--------|
| Household/shared contact info | Defer and tag Ops lead; consider creating household link instead of merging. |
| Conflicting compliance fields (e.g., consent) | Defer and escalate to Compliance contact. |
| System outages preventing Merge UI access | Notify Engineering; record duplicates manually and resume once service restored. |

## 9. Metrics to Watch

- `Auto merges today` – should trend upward as fuzzy dedupe matures.
- `Manual review queue` – keep backlog < 50 items; alert triggers above this threshold.
- `Undo rate` – maintain <5% of auto merges.
- `Average resolution time` – target < 24 hours for manual reviews.

## 10. Reference Materials

- [Sprint 5 Survivorship & Threshold Decisions](./sprint5-survivorship-decisions.md)
- [Golden Dataset Fuzzy Scenarios](../ops/testdata/importer_golden_dataset_v0/README.md)
- Importer Tech Doc — Sprint 5 section for implementation roadmap.

## 11. Open Questions

Record the final policy decisions here once approved:

- **Manual review SLA**: ⚠️ **To be determined** (default: 1 business day recommended)
- **Undo permissions (roles)**: ⚠️ **To be determined** (pending final policy decision; currently Admins can undo)
- **Notification cadence**: ⚠️ **Not yet implemented** (TODO: Sprint 6 - auto-merge notifications)
- **Escalation contacts**: ⚠️ **To be determined** (pending escalation policy)

**Sprint 5 Completion Status**: ✅ Merge workflow implemented and documented; policy decisions pending.

**Implementation Notes**:
- ✅ Merge UI available at `Admin ▸ Importer ▸ Duplicate Review`
- ✅ Undo functionality available via `importer_dedupe_undo_merge` endpoint
- ✅ Queue statistics available via `importer_dedupe_stats` endpoint
- ⚠️ Auto-merge notifications not yet implemented (TODO: Sprint 6)
- ⚠️ Export functionality not yet implemented (TODO: Sprint 6)
