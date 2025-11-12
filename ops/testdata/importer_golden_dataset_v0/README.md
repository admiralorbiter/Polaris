# Importer Golden Dataset v0

This directory contains sample inputs and expected outcomes for the volunteer importer. Start here when validating new importer work or debugging regressions.

## Files

- `volunteers_valid.csv` — happy-path records that should stage and load successfully.
- `volunteers_invalid.csv` — rows that trigger current validation rules (required contact info, format checks).
- `volunteers_duplicates.csv` — rows representing deterministic duplicate scenarios (same email/phone).
- `volunteers_duplicate_skip.csv` — demonstrates deterministic auto-dedupe resolving an existing volunteer via email.
- `volunteers_survivorship_seed.csv` — baseline records to seed core data before exercising survivorship precedence.
- `volunteers_survivorship_updates.csv` — follow-up records with conflicting values to demonstrate incoming overrides vs. manual wins.
- `volunteers_idempotent_replay.csv` — exact replay of the happy-path dataset to validate idempotent dry-run/live workflows.
- `volunteers_changed_payload.csv` — same `external_id`s as the happy-path dataset with updated contact info to assert update-vs-insert handling.
- `volunteers_email_vs_phone.csv` — conflicting records that collide on email-only and phone-only signals to exercise deterministic dedupe heuristics.
- `volunteers_fuzzy_seed.csv` — seeds high-fidelity volunteer profiles (DOB, address, employer) used as the baseline for fuzzy dedupe scenarios in Sprint 5.
- `volunteers_fuzzy_candidates.csv` — near-duplicate volunteers intentionally crafted to land in different fuzzy dedupe score bands (auto-merge, manual review, new record).

Each CSV includes a header row. Use these files with `flask importer run --source csv --file <path>` (or future automation) to exercise the pipeline.

## Expected Outcomes

| File                    | Records | Expected result                                                                 |
|------------------------|---------|----------------------------------------------------------------------------------|
| `volunteers_valid.csv`   | 3       | All rows land in `staging_volunteers`, pass validation, and appear in counts.    |
| `volunteers_invalid.csv` | 3       | Rows land but are quarantined with rule codes (`VOL_CONTACT_REQUIRED`, `VOL_EMAIL_FORMAT`, `VOL_PHONE_E164`). |
| `volunteers_duplicates.csv` | 2   | First row inserts; second deterministically merges into the same volunteer (`core.rows_deduped_auto=1`, dashboard auto-resolved card increments). |
| `volunteers_duplicate_skip.csv` | 2 | First row inserts into core; second auto-resolves against the existing record (`core.rows_deduped_auto=1`, `dedupe_suggestions.decision=AUTO_MERGED`, dashboard card + row badge reflect the merge). |
| `volunteers_survivorship_seed.csv` | 2 | Seeds two volunteers with steward-verified context. Run once to establish the baseline core state. |
| `volunteers_survivorship_updates.csv` | 2 | Re-run **after** the seed file. Expect `core.volunteers.survivorship.stats.incoming_overrides ≥ 1` (Jordan’s fresh CRM update wins). If you manually edit Taylor’s record between runs (set a custom note or phone via DQ remediation), the second row will demonstrate a manual win (`manual_wins ≥ 1`) and the run detail modal will highlight the survivorship breakdown. |
| `volunteers_idempotent_replay.csv` | 3 | Run immediately after `volunteers_valid.csv`; expect zero new `core.rows_created`, identical `rows_updated`, and matching `external_id_map` entries aside from run timestamps. |
| `volunteers_changed_payload.csv` | 3 | Run after `volunteers_valid.csv`; expect `core.rows_updated=3`, `rows_created=0`, and survivorship counters reflecting field-level updates (phone/email) without inserting new volunteers. |
| `volunteers_email_vs_phone.csv` | 2 | Run after seeding happy-path data; expect auto-dedupe merges when either email or phone matches (`core.rows_deduped_auto=2`) and stable `external_id_map` entries documenting the merge source. |
| `volunteers_fuzzy_seed.csv` | 3 | Seeds full-profile volunteers (DOB, address, employer) that act as the “ground truth” for fuzzy dedupe scoring. Run once before any fuzzy candidate scenarios so reference data exists in staging/core. |
| `volunteers_fuzzy_candidates.csv` | 3 | Run after `volunteers_fuzzy_seed.csv` (and deterministic seeds). Expected outcomes **once Sprint 5 is delivered**:<br/>• Row 1 (`fuzzy-candidate-001`) should land in the high-confidence band (score ≥0.95) and auto-merge when fuzzy dedupe is enabled.<br/>• Row 2 (`fuzzy-candidate-002`) should fall into the manual review band (0.80–0.95) and surface in the Merge UI queue.<br/>• Row 3 (`fuzzy-candidate-003`) should remain a new volunteer (<0.80) and insert into core without creating a suggestion. |

Document additional nuances (DQ messages, counts, etc.) as the importer matures. For IMP-11, expect the invalid CSV to yield the following per-rule counts when run via CLI or worker:

- `VOL_CONTACT_REQUIRED`: 1 (missing both email and phone)
- `VOL_EMAIL_FORMAT`: 1 (bad email + malformed phone)
- `VOL_PHONE_E164`: 1 (phone not normalized to E.164)

Run locally with:

```
flask importer run --source csv --file ops/testdata/importer_golden_dataset_v0/volunteers_invalid.csv
```

The command summary and `import_runs.counts_json["dq"]["volunteers"]` should reflect the tallies above.

To inspect duplicate skips in the core load stage:

```
flask importer run --source csv --file ops/testdata/importer_golden_dataset_v0/volunteers_duplicate_skip.csv --summary-json
```

The emitted JSON summary now includes `"core": {"rows_created": 0, "rows_updated": 1, "rows_deduped_auto": 1, ...}` plus a `dedupe_suggestions` record with `decision="auto_merged"` and `match_type="email"`. In the Importer Runs dashboard, the "Auto-resolved duplicates" summary card and per-run badge should reflect the deterministic merge count, and the run detail modal will display "1 row auto-resolved."

## Extending the Dataset

1. Add new rows to existing CSVs or introduce additional files (e.g., events) as schemas become available.
2. Update the table above (or add a new section) with expected behavior after each importer enhancement (idempotency, fuzzy dedupe, etc.).
3. Reference this dataset from story DoR/DoD checklists so every ticket identifies the scenarios it uses.

### Sprint 3 Idempotency & Dedupe Regression Playbook

1. **Seed happy-path data**: Run `volunteers_valid.csv` once to populate core with the baseline volunteers.
2. **Idempotent replay**: Run `volunteers_idempotent_replay.csv` in dry-run and live modes. Expect identical counters between runs (`rows_created=0`, `rows_updated=0`, `core.rows_deduped_auto=0`) and verify the emitted `idempotency_summary.json` reports `external_id_map_diff="none"`.
3. **Update-vs-insert checks**: Execute `volunteers_changed_payload.csv` to confirm the importer surfaces `rows_updated=3`, leaves `rows_created=0`, and records field-level survivorship decisions for email/phone updates.
4. **Signal-specific dedupe**: Replay `volunteers_email_vs_phone.csv`. Verify each row auto-merges into the existing core volunteer via email or phone match (`core.rows_deduped_auto=2`) while preserving the latest contact info per precedence.
5. **Partial/out-of-order simulations**: Re-run a subset of rows (e.g., only `vol-001` and `vol-phone-002`) to ensure the importer treats them idempotently—repeat runs should leave `rows_created` unchanged and only increment `rows_updated` when payloads differ.
6. **Survivorship pair**: When validating steward overrides, execute `volunteers_survivorship_seed.csv` followed by `volunteers_survivorship_updates.csv`, updating expectations if precedence logic changes.

### Sprint 5 Fuzzy Dedupe Playbook (prep)

1. **Seed fuzzy baseline**: Run `volunteers_fuzzy_seed.csv` to add enriched volunteers (DOB, address, employer) that future fuzzy matches will reference. Confirm staging rows persist the additional attributes.
2. **Execute fuzzy scenarios**: After the baseline run, process `volunteers_fuzzy_candidates.csv`.
   - `fuzzy-candidate-001`: Expect a high-confidence score driven by matching DOB, address, and alternate phone/email aliases (auto-merge once thresholds configured ≥0.95).
   - `fuzzy-candidate-002`: Expect a borderline score (nickname + nearby address). This should enqueue to the Merge UI review band so stewards can adjudicate.
   - `fuzzy-candidate-003`: Expect a truly new volunteer—the differing DOB, city, and phone should drive the score below the review threshold.
3. **Document scores**: Once Sprint 5 scoring is implemented, record the observed scores and decisions here so QA can regress future changes.
4. **Automated regression**: Incorporate both CSVs into the fuzzy dedupe regression suite (planned Sprint 5) so candidate generation + merge outcomes stay stable over time.

Re-run these scenarios whenever importer survivorship or dedupe logic evolves, and refresh the expected counters above so QA can quickly validate regression outcomes.
