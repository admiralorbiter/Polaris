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
| `importer_dedupe_auto_total{match_type}` | Planned | Include `match_type` (`fuzzy_high`, `deterministic_email`, etc.). |
| `importer_dedupe_manual_total` | Planned | Powers manual workload dashboards. |
| `importer_dedupe_undo_total` | Planned | Feed undo-rate alerting. |
| Merge decision audit payload | Needs review | Ensure payload stores score, threshold version, and top features for compliance auditing. |

## 5. Outstanding Questions for Stakeholders

1. **Manual review SLA**: What is the expected turnaround time for items in the Merge queue? Needed for alert thresholds.
2. **Undo permissions**: Should only Admins undo auto-merges, or can Data Stewards undo their own actions?
3. **Notification channel**: Do Ops prefer daily digests of auto-merges or per-run notifications?
4. **Metric visibility**: Which dashboards (Ops vs Exec) need dedupe KPIs, and at what cadence (daily/weekly)?

Please capture decisions inline below once alignment is reached.

---

- **Threshold decision**: __________
- **Review SLA**: __________
- **Undo permissions**: __________
- **Notification preference**: __________
- **Dashboard owners**: __________
