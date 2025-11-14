# Sprint 1 Retrospective & Lessons Learned

**Sprint**: Sprint 1 — CSV Adapter + ELT Skeleton  
**Date**: Post-Sprint 1 completion  
**Status**: ✅ Complete

## What Went Well

### Architecture & Design Decisions
- **Feature flag system**: Clean separation via `IMPORTER_ENABLED` made it easy to test disabled state and optional mounting. The registry-based adapter validation caught configuration errors early.
- **SQLite transport default**: Using SQLite for Celery broker/results by default eliminated Redis dependency for local development, lowering onboarding friction.
- **Golden dataset approach**: Creating `ops/testdata/importer_golden_dataset_v0/` with documented expected outcomes provided a shared test harness that accelerated development and regression testing.
- **Structured metrics**: Populating `counts_json` and `metrics_json` from the start gave immediate observability into pipeline stages without requiring external monitoring tools.

### Implementation Highlights
- **CLI flexibility**: Supporting both `--inline` (synchronous) and async (default) modes made debugging easier while keeping production-ready async path.
- **Header normalization**: Accepting common CSV header aliases (`First Name`, `Email Address`) improved user experience without requiring strict column naming.
- **DQ rule codes**: Using structured rule codes (`VOL_CONTACT_REQUIRED`, `VOL_EMAIL_FORMAT`, `VOL_PHONE_E164`) made violations queryable and reportable from day one.
- **Retry support**: Building retry capability early (storing `ingest_params_json`) enabled recovery from transient failures without manual intervention.

### Testing & Quality
- **Comprehensive test coverage**: Unit tests for each pipeline stage (adapter, DQ, load) plus integration tests against golden dataset provided confidence in changes.
- **Golden dataset scenarios**: Covering happy path, validation failures, and duplicates in test data ensured edge cases were exercised.

## Challenges & Learnings

### Technical Challenges
1. **Windows worker pool**: Discovered Celery's default prefork pool doesn't work on Windows. **Solution**: Documented `--pool=solo` requirement and added to troubleshooting guides.
2. **Dry-run metrics**: Needed to preserve full evaluation counts in `metrics_json` even when skipping core writes, so dry-runs remain useful for validation. **Solution**: Separated `counts_json` (actual writes) from `metrics_json` (all evaluations).
3. **Duplicate detection scope**: Initially considered deterministic dedupe in Sprint 1, but deferred to Sprint 3 to keep scope manageable. **Learning**: Create-only upsert with email duplicate skip was sufficient MVP.

### Process Learnings
1. **Documentation timing**: Writing implementation notes alongside code (in tech doc) helped capture design decisions before they were forgotten.
2. **Golden dataset evolution**: Started with minimal test data, but quickly realized need for multiple scenarios (valid, invalid, duplicates). **Recommendation**: Expand golden dataset proactively as new edge cases emerge.
3. **CLI vs UI**: CLI path matured faster than UI, which helped validate pipeline logic independently. **Takeaway**: Parallel CLI/UI development can accelerate overall delivery.

## Decisions Made & Rationale

### Deferred to Sprint 2
- **Full Runs dashboard**: Basic admin page shows recent runs table, but full dashboard with filtering/pagination deferred to Sprint 2. **Rationale**: Core pipeline functionality prioritized over UI polish.
- **DQ inbox UI**: Violations viewable via database queries only. **Rationale**: Remediation workflow (IMP-22) requires inbox UI, so building together in Sprint 2 makes sense.
- **Dry-run UI toggle**: Dry-run works via CLI flag but not exposed in UI. **Rationale**: Low-priority UX enhancement; CLI sufficient for initial use cases.

### Deferred to Sprint 3
- **Deterministic dedupe**: Exact email/phone matching deferred. **Rationale**: Create-only upsert with duplicate skip provides basic protection; full dedupe requires external_id_map (Sprint 3).
- **External ID mapping**: Not yet used for idempotency. **Rationale**: Schema exists (IMP-2), but implementation requires dedupe logic, so grouped with Sprint 3.

### Architecture Decisions
- **Staging → Clean → Core separation**: Clear data flow made debugging easier and provided natural checkpointing for DQ violations.
- **JSON payload storage**: Storing raw payloads in `staging_volunteers.payload_json` preserved source data for replay and audit, even after normalization.
- **Status transitions**: Using enum statuses (`LANDED`, `VALIDATED`, `QUARANTINED`, `LOADED`) on staging rows provided clear state machine for troubleshooting.

## Metrics & Observability Gaps

### What We're Tracking
- ✅ Run counts (staging, DQ, core) in `counts_json`
- ✅ Per-rule violation tallies
- ✅ Worker health via ping endpoint
- ✅ CLI summary output (human-readable and JSON)

### What's Missing (Future Sprints)
- ⚠️ Dashboard load time metrics (Sprint 2)
- ⚠️ Violation export events (Sprint 2)
- ⚠️ Remediation success rate (Sprint 2)
- ⚠️ Run duration percentiles (Sprint 2)
- ⚠️ Anomaly detection (Sprint 6)

## Recommendations for Sprint 2

### Immediate Actions
1. **Expand golden dataset**: Add scenarios for remediation workflow (fixable violations, multi-violation rows).
2. **Performance baseline**: Measure dashboard render time with 100+ runs to establish performance targets.
3. **Access control audit**: Review permission requirements for dashboard, inbox, and remediation routes before implementation.

### Process Improvements
1. **UI wireframes**: Create mockups for dashboard, inbox, and remediation forms before coding to align on UX expectations.
2. **API contracts**: Define REST endpoints for dashboard/inbox early so frontend/backend can work in parallel.
3. **Test data generation**: Consider script to generate large test datasets (1000+ runs) for performance testing.

### Technical Debt
1. **Error handling**: Standardize error response format across CLI and API endpoints.
2. **Logging**: Add structured logging with `run_id` correlation for better traceability.
3. **Migration testing**: Verify migrations work on existing production-like databases (not just fresh installs).

## Open Questions

1. **Pagination strategy**: Client-side vs server-side pagination for dashboard? (Recommendation: Server-side for >100 runs)
2. **Violation retention**: How long should violations remain visible? (Recommendation: 90 days, configurable)
3. **Remediation batching**: Should remediated rows be batched into single run or individual runs? (Recommendation: Batch for efficiency, but track individually for audit)

## Success Metrics

- ✅ All Sprint 1 stories completed and tested
- ✅ Golden dataset created with documented expected outcomes
- ✅ CLI and admin UI both functional for triggering runs
- ✅ Worker process stable with SQLite transport
- ✅ Test coverage sufficient for regression confidence

## Next Steps

- Begin Sprint 2 with IMP-20 (Runs dashboard) as foundation for other UI work
- Review UI wireframes and API contracts before implementation
- Set up performance testing environment for dashboard load testing
- Expand golden dataset with remediation scenarios

---

**Related Documents**:
- `docs/reference/architecture/data-integration-platform-tech-doc.md` — Full backlog and Sprint 1 completion status
- `docs/operations/importer-feature-flag.md` — Configuration and troubleshooting
- `docs/operations/commands.md` — CLI reference
- `ops/testdata/importer_golden_dataset_v0/README.md` — Golden dataset documentation

