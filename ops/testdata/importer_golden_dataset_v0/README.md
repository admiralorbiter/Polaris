# Importer Golden Dataset v0

This directory contains sample inputs and expected outcomes for the volunteer importer. Start here when validating new importer work or debugging regressions.

## Files

- `volunteers_valid.csv` — happy-path records that should stage and load successfully.
- `volunteers_invalid.csv` — rows that trigger current validation rules (required contact info, format checks).
- `volunteers_duplicates.csv` — rows representing deterministic duplicate scenarios (same email/phone).
- `volunteers_duplicate_skip.csv` — demonstrates deterministic auto-dedupe resolving an existing volunteer via email.
- `volunteers_survivorship_seed.csv` — baseline records to seed core data before exercising survivorship precedence.
- `volunteers_survivorship_updates.csv` — follow-up records with conflicting values to demonstrate incoming overrides vs. manual wins.

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

### Sprint 3 Prep (Idempotency, Dedupe & Survivorship)

- **`volunteers_idempotent_replay.csv` (planned)** — identical to `volunteers_valid.csv`; rerun after an initial import to confirm zero new inserts and `rows_updated` tracking.
- **`volunteers_changed_payload.csv` (planned)** — same `external_id` with updated contact details to exercise update-vs-insert survivorship logic.
- **`volunteers_email_vs_phone.csv` (planned)** — conflicting records where email matches but phone differs and vice versa; validates deterministic dedupe paths (expect `rows_deduped_auto` increments when heuristics are decisive).
- **`volunteers_survivorship_seed.csv` + `volunteers_survivorship_updates.csv` (new)** — sequential run pair; first seeds steward-verified data, second introduces conflicting source payloads so the UI and metrics surface survivorship decisions. Update the change-log expectations if precedence rules evolve.
- Update this README with expected counters once Sprint 3 implementation lands, including `rows_updated`, `dedupe.decisions`, and change-log assertions.
