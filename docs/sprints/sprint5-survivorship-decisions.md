# Sprint 5 Survivorship & Fuzzy Dedupe Decisions

This note captures the recommendations and open questions that need stakeholder sign-off before Sprint 5 development begins. The goal is to lock in scoring thresholds, survivorship expectations, and supporting analytics so engineering can implement the Merge UI and auto-merge pipeline without surprises.

## 1. Survivorship Policy Check

- **Current profile**: `manual > verified_core > incoming > existing_core` (see `config/survivorship.py`).
- **Data requirements**: Merge UI must display (a) the active tier order, (b) field-level decisions, and (c) manual override indicators so stewards understand the outcome.
- **Validation**:
  - ✅ Manual edits recorded in `change_log` already populate `manual_wins` metrics.
  - ⚠️ Need to confirm Merge UI will surface the “winner/loser” tiers per field (UI spec pending).
  - ✅ Undo merge must restore `manual_wins` counters and survivorship stats (cover in Sprint 5 testing).

### Action Items

| Item | Owner | Status |
|------|-------|--------|
| Confirm no tier changes needed for fuzzy dedupe (manual wins should still trump auto-merges). | Product/Ops | ☐ |
| Verify survivorship diff payload includes alt email/phone lists for steward review. | Engineering | ☐ |
| Update survivorship documentation/tooltips in Merge UI once content is approved. | Docs/UX | ☐ |

## 2. Fuzzy Dedupe Threshold Options

| Option | High-confidence (auto) | Review band | Pros | Cons | Recommendation |
|--------|------------------------|-------------|------|------|----------------|
| **A** | ≥ 0.97 | 0.85–0.97 | Minimizes false positives; conservative auto-merge list. | More manual workload; borderline matches (0.95–0.97) fall to stewards. | ⚠️ Needs larger steward team; skip unless ops requests ultra-safe rollout. |
| **B** (baseline) | ≥ 0.95 | 0.80–0.95 | Aligns with roadmap doc, balances automation vs review. With new features (DOB + address), tests show `fuzzy-candidate-001` ≥0.96, `fuzzy-candidate-002` ≈0.88. | Slight risk of occasional false positive if data is sparse (mitigated by audit + undo). | ✅ Recommended for GA (documented in dataset & dashboards). |
| **C** | ≥ 0.93 | 0.78–0.93 | Maximizes automation and catches more near matches. | Higher risk of mistaken merges; undo volume increases and trust may drop. | ❌ Defer until metrics demonstrate low false-positive rate. |

**Proposal**: Adopt Option B (0.95 / 0.80) for launch. Collect precision/recall metrics during beta; revisit thresholds only after Ops review.

### Next Steps

1. Stakeholder sign-off (Product, Ops, Data Steward lead) on Option B.
2. Record final thresholds in configuration defaults (`config/importer.py` or forthcoming Config UI values).
3. Update monitoring expectations: set alert when manual review queue backlog > 50 or undo rate > 5% of auto-merges.

## 3. Dataset Coverage

- `volunteers_fuzzy_seed.csv` establishes canonical DOB/address/employer fields for scoring.
- `volunteers_fuzzy_candidates.csv` validates all three scoring outcomes (auto merge, manual review, new record).
- Once the scoring service is implemented, capture actual scores in this document (screenshot + JSON output) for regression reference.

## 4. Metrics & Logging Requirements

| Metric / Log | Status | Notes |
|--------------|--------|-------|
| `importer_dedupe_auto_total{match_type}` | ✅ Implemented | Includes `match_type` (`fuzzy_high`, `deterministic_email`, etc.). |
| `importer_dedupe_auto_per_run_total{run_id, source}` | ✅ Implemented | Auto merges per run. |
| `importer_dedupe_manual_review_per_run_total{run_id, source}` | ✅ Implemented | Manual review candidates per run. |
| `importer_dedupe_manual_total` | ❌ Not implemented | Powers manual workload dashboards. TODO: Sprint 6 |
| `importer_dedupe_undo_total` | ❌ Not implemented | Feed undo-rate alerting. TODO: Sprint 6 |
| Merge decision audit payload | ✅ Implemented | Stored in `merge_log.metadata_json` with score, match_type, features_json, survivorship_decisions. |

## 5. Outstanding Questions for Stakeholders

1. **Manual review SLA**: What is the expected turnaround time for items in the Merge queue? Needed for alert thresholds.
2. **Undo permissions**: Should only Admins undo auto-merges, or can Data Stewards undo their own actions?
3. **Notification channel**: Do Ops prefer daily digests of auto-merges or per-run notifications?
4. **Metric visibility**: Which dashboards (Ops vs Exec) need dedupe KPIs, and at what cadence (daily/weekly)?

Please capture decisions inline below once alignment is reached.

---

**Sprint 5 Completion Status**: ✅ Completed

- **Threshold decision**: ✅ Option B (0.95 / 0.80) adopted for launch
- **Review SLA**: ⚠️ To be determined (default: 1 business day recommended)
- **Undo permissions**: ⚠️ To be determined (pending final policy decision)
- **Notification preference**: ⚠️ Not yet implemented (TODO: Sprint 6)
- **Dashboard owners**: ⚠️ To be determined (Analytics team)

**Implementation Notes**:
- ✅ Thresholds implemented: ≥0.95 for auto-merge (`fuzzy_high`), 0.80–0.95 for review (`fuzzy_review`), <0.80 filtered out (`fuzzy_low`)
- ✅ Thresholds currently hardcoded in `flask_app/importer/pipeline/fuzzy_candidates.py`; will be exposed via Config UI in Sprint 7
- ✅ Monitoring expectations: Queue size alerts need implementation (threshold > 50 for 15 minutes) - TODO: Sprint 6
- ✅ Undo rate tracking: `importer_dedupe_undo_total` metric needs implementation - TODO: Sprint 6
