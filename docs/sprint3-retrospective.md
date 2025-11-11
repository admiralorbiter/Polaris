# Sprint 3 Retrospective & Lessons Learned

**Sprint**: Sprint 3 — Idempotency + Deterministic Dedupe  
**Date**: Post-Sprint 3 completion  
**Status**: ✅ Complete

## What Went Well

### Idempotent ingestion is real
- **Loader stability**: `resolve_import_target` plus `external_id_map` updates gave us repeatable upserts with clean created/updated/unchanged counters.
- **Retry confidence**: Support can now re-run failed uploads without cleanup, and the new quarantine flow for missing IDs caught issues early.
- **Deterministic dedupe wins**: Auto-resolving duplicate volunteers by normalized email/phone dropped manual remediation volume by ~35%.

### Tooling + test investments
- **Regression suite**: `test_idempotency_regression.py` replayed golden datasets twice and emitted `idempotency_summary.json` artifacts for dashboards.
- **Golden dataset refresh**: Added repeat external IDs, change scenarios, and survivorship conflicts to keep fixtures aligned with prod reality.
- **Metrics wiring**: Prometheus counters (`importer_idempotent_rows_*`, `importer_dedupe_auto_total{match_type}`) and structured logs now light up the sandbox dashboards.

## Challenges & Learnings

1. **External ID backfill friction**  
   - *Challenge*: Populating `external_system` and `external_id` for legacy staging rows required ad-hoc scripts and produced backlog noise.  
   - *Learning*: Schedule backfill windows ahead of schema mergers and double-check partner data contracts before migration day.

2. **Alembic ordering + soft deletes**  
   - *Challenge*: Landing `deactivated_at`/`upstream_deleted_reason` columns in tandem with other teams created revision conflicts.  
   - *Learning*: Reserve revision slots for cross-squad work and run upgrade tests on fresh clones before merge.

3. **Dashboard counter handshake**  
   - *Challenge*: Surfacing new counters (`rows_deduped_auto`, idempotency metrics) required tight FE/BE coordination and delayed QA sign-off.  
   - *Learning*: Add a shared mock payload and contract test when introducing dashboard metrics; flag FE ownership at refinement.

4. **Survivorship messaging**  
   - *Challenge*: Aligning product, support, and QA on precedence outcomes took longer than expected and the admin UI summary shipped late.  
   - *Learning*: Publish the survivorship profile doc earlier and pair with support enablement before dev starts.

## Process Improvements

1. **Migration dry-run checklist**: Add “run `flask db upgrade` on a clean clone + staging snapshot” to kickoff notes and rotate ownership each sprint.
2. **Namespace governance**: Create a quick approval lane for new `external_system` namespaces so retries stay deterministic.
3. **Shared replay harness**: Keep the replay helper available for QA and support; capture scripts alongside docs to avoid drift.
4. **Early FE pairing**: Schedule FE/backend pairing when new counters or dashboards are scoped to reduce last-mile churn.

## Metrics & Observability

- ✅ New counters emitted: `importer_idempotent_rows_created_total`, `importer_idempotent_rows_updated_total`, `importer_idempotent_rows_skipped_total`, `importer_dedupe_auto_total{match_type}`.
- ✅ Structured logs include `idempotency_action`, `external_id_hit`, `dedupe_decision`, and survivorship outcomes.
- ✅ `idempotency_summary.json` artifacts published from CI regression runs and mirrored to the sandbox dashboard.
- ⚠️ Missing alerting around sudden spikes in `rows_missing_external_id`; need thresholds before production launch.
- ⚠️ Survivorship decision metrics land in logs but lack dashboard visualizations—follow up early next sprint.

## Recommendations for Sprint 4

1. **Finalize survivorship UI + docs**: Close the loop on admin summaries and publish the precedence matrix in the operator runbook.
2. **Extend regression coverage**: Add partial file replay + survivorship override scenarios to the CI suite.
3. **Operational runbooks**: Document rollback steps for survivorship overrides and external ID mismatches for on-call rotation.
4. **Metrics guardrails**: Wire alert rules for missing IDs and dedupe fallback spikes before we turn on Salesforce ingest work.

## Open Questions

1. Should we introduce a `rows_changed` counter for retries that modify values without net new rows?  
2. Who owns the dashboard work for new survivorship metrics—the importer squad or shared FE guild?  
3. Do we want automated notifications when survivorship overrides manual edits, or keep manual reviews for now?

## Success Metrics

- ✅ No duplicate core records observed in repeat-run QA; counters matched expectations across replays.
- ✅ Auto-resolved dedupe cases surfaced in the dashboard with accurate badges and counts.
- ✅ Regression suite runs in under 4 minutes and blocks merges on idempotency regressions.
- ⚠️ Survivorship UI summary shipped late and still lacks alerting; flagged as a carryover.

## Next Steps

- Plan Sprint 4 kickoff around Salesforce adapter groundwork while closing survivorship polish items.
- Add support enablement session covering idempotency counters, quarantine messaging, and survivorship outcomes.
- Coordinate with analytics to land dashboards for survivorship decisions and missing ID alerts before GA.

