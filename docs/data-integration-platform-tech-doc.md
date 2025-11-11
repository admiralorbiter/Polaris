# Volunteer Import Platform — Markdown Backlog

**Project**: Optional Importer for Volunteer Management (Flask + Postgres + Celery — SQLite transport by default, Redis optional)  
**Owner**: @jlane  
**Date**: 2025-11-08  
**Version**: v1.0 (Markdown planning artifact)  
**Ticket Prefix**: `IMP-###` (Epics: `EPIC-X`)  
**Story Points**: 1, 2, 3, 5, 8, 13  

> This backlog is organized by **Sprints** and **Epics**, with user stories, acceptance criteria, dependencies, and notes. Copy/paste into Jira/Linear or keep as Markdown.

---

## Table of Contents
- [Epics Overview](#epics-overview)
- [Cross-Team Quality Bars](#cross-team-quality-bars)
- [Supporting Documentation](#supporting-documentation)
- [Sprint 0 — Foundations](#sprint-0--foundations)
- [Sprint 1 — CSV Adapter + ELT Skeleton](#sprint-1--csv-adapter--elt-skeleton)
- [Sprint 2 — Runs Dashboard + DQ Inbox](#sprint-2--runs-dashboard--dq-inbox)
- [Sprint 3 — Idempotency + Deterministic Dedupe](#sprint-3--idempotency--deterministic-dedupe)
- [Sprint 4 — Salesforce Adapter (Optional)](#sprint-4--salesforce-adapter-optional)
- [Sprint 5 — Fuzzy Dedupe + Merge UI](#sprint-5--fuzzy-dedupe--merge-ui)
- [Sprint 6 — Reconciliation, Anomalies, Alerts](#sprint-6--reconciliation-anomalies-alerts)
- [Sprint 7 — Mapping Versioning + Config UI + Backfills](#sprint-7--mapping-versioning--config-ui--backfills)
- [Sprint 8 — Events & Signups/Attendance](#sprint-8--events--signupsattendance)
- [Sprint 9 — Security, Audit, Packaging](#sprint-9--security-audit-packaging)
- [Backlog (Nice-to-Have)](#backlog-nice-to-have)
- [Roles & RACI](#roles--raci)
- [Risk Register](#risk-register)

---

## Supporting Documentation

**Architecture & Design**:
- `docs/data-integration-platform-overview.md` — High-level architecture, data layers, pipeline flow, and design principles
- Architecture diagram (future): End-to-end pipeline flow diagram showing Extract → Land → Transform → Link → Load → Reconcile stages

**Sprint Retrospectives & Learnings**:
- `docs/sprint1-retrospective.md` — Sprint 1 completion retrospective, lessons learned, and recommendations for Sprint 2

**Operational Guides**:
- `docs/importer-feature-flag.md` — Feature flag configuration, troubleshooting, and verification checklist
- `docs/commands.md` — CLI command reference with troubleshooting and debugging tips
- `docs/importer-dor.md` — Definition of Ready checklist for importer tickets
- `docs/importer-dod.md` — Definition of Done checklist for importer tickets

**Test Data & Scenarios**:
- `ops/testdata/importer_golden_dataset_v0/README.md` — Golden dataset documentation with expected outcomes

---

## Epics Overview

- **EPIC-0**: Foundations — feature flags, schema, worker process, golden data.  
- **EPIC-1**: CSV adapter + ELT skeleton (Volunteers).  
- **EPIC-2**: Runs dashboard + DQ inbox (required/format) + remediation.  
- **EPIC-3**: Deterministic dedupe + idempotent upsert + external ID map.  
- **EPIC-4**: Salesforce adapter (optional) + incremental.  
- **EPIC-5**: Fuzzy dedupe + Merge UI + survivorship + undo.  
- **EPIC-6**: Reconciliation, anomaly detection, alerts, trends.  
- **EPIC-7**: Mapping versioning, config UI, backfill tooling.  
- **EPIC-8**: Events & Signups/Attendance + cross-entity DQ.  
- **EPIC-9**: Security/RBAC/Audit/Retention + packaging & OSS.

---

## Cross-Team Quality Bars

**Definition of Ready (DoR)**  
- Story written; AC clear; dependencies listed; flags/config keys named; test data identified.
- Importer DoR checklist: see `docs/importer-dor.md` (link this document in Jira issues).

**Definition of Done (DoD)**  
- Feature behind flag (if applicable) • unit/functional tests • docs updated • counters/metrics visible in Runs • security reviewed • rollback strategy noted.
- Importer DoD checklist: see `docs/importer-dod.md`; include the checklist when closing importer tickets.

---

## Sprint 0 — Foundations
**Epic**: EPIC-0  
**Goal**: Importer exists inside the Flask repo, optional & isolated; worker process alive; base schema & golden dataset.

### IMP-1 — Feature flags & optional mounting _(5 pts)_
**User story**: As an admin, I can disable the importer so non-import installs have no importer menus, routes, or deps.  
**Acceptance Criteria**
- `IMPORTER_ENABLED=false` hides importer routes/menus/CLI; app boots cleanly.  
- `IMPORTER_ADAPTERS` parsed (e.g., `csv,salesforce`) but not loaded when disabled.  
- Conditional blueprint registration confirmed by smoke test.  
**Dependencies**: none.  
**Notes**: Ship config docs; `env.example` (copy to `.env`) shows importer disabled with sample adapters and points to `pip install ".[importer]"` for optional extras.

### IMP-2 — Base DB schema for imports _(8 pts)_
**User story**: As a dev, I need schema for runs, staging, violations, dedupe, id maps, merges, and change log.  
**Acceptance Criteria**
- Tables: `import_runs`, `staging_volunteers`, `dq_violations`, `dedupe_suggestions`, `external_id_map`, `merge_log`, `change_log`.  
- FKs & indexes on `run_id`, `(external_system, external_id)`.  
- Migrations idempotent; rollback verified.  
**Dependencies**: IMP-1.  
**Notes**: Namespaced `import_*`/`staging_*` to isolate from core.
- Schema snapshot (v1):
  - `import_runs`: status enum, adapter/source metadata, counters JSON, anomaly flags, start/finish timestamps, FK `triggered_by_user_id`.
  - `staging_volunteers`: raw + normalized payload JSON, checksum, status enum, FK `run_id`, `(external_system, external_id)` index, unique `(run_id, sequence_number)`.
  - `dq_violations`: FK `run_id` + `staging_volunteer_id`, enums for severity/status, remediation audit columns, rule code index.
  - `dedupe_suggestions`: FK `run_id`, optional staging row + contacts, score/features JSON, decision enum with FK `decided_by_user_id`.
  - `external_id_map`: unique `(entity_type, external_system, external_id)`, timestamps for first/last seen, FK `run_id`.
  - `merge_log`: FK `run_id`, contact/user relationships, before/after/undo JSON snapshots.
  - `change_log`: FK `run_id`, entity + field metadata, audit FK `changed_by_user_id`, constraint `field_name` non-empty.

### IMP-3 — Worker process + queues _(5 pts)_
**User story**: As an operator, long-running tasks run off the web thread.  
**Acceptance Criteria**
- Celery worker consumes the `imports` queue using the SQLite/SQLAlchemy transport by default (no Redis required); configuration supports swapping to Redis/Postgres via env vars.  
- Health check (`flask importer worker ping` or REST endpoint) round-trips a heartbeat task.  
- Worker startup (`flask importer worker run`) and shutdown honour SIGTERM/SIGINT, draining in-flight tasks gracefully.  
**Dependencies**: IMP-1.  
**Notes**: Document env vars (`IMPORTER_WORKER_ENABLED`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`), Procfile/compose snippets, and optional Redis upgrade path for higher throughput.  
**Implementation outline**:
- `flask importer worker run` wraps `celery worker -A flask_app.importer.tasks -Q imports`; honours `IMPORTER_WORKER_ENABLED`.
- Health diagnostics: `flask importer worker ping` (CLI) and `/importer/worker_health` when importer enabled.
- Default transport: SQLite file at `instance/celery.sqlite`; production override via `CELERY_BROKER_URL=redis://...` and matching result backend.
- Provide Procfile entry (`worker: flask importer worker run`) and optional `docker-compose.worker.yml` snippet for Redis deployments.
- Windows tip: launch with a solo pool (`flask importer worker run --pool=solo`) because the default prefork pool is unavailable on Windows.

### IMP-4 — DoR/DoD checklists & Golden Dataset scaffold _(3 pts)_
**User story**: As QA/PM, I want shared criteria and seed test data.  
**Acceptance Criteria**
- DoR/DoD documents added (`docs/importer-dor.md`, `docs/importer-dod.md`) and referenced from backlog.  
- Golden dataset v0 scaffold created under `ops/testdata/importer_golden_dataset_v0/` with starter volunteer samples (happy path, validation failures, duplicates) plus README noting expected outcomes and extension guidance.  
**Dependencies**: none.

---

## Sprint 1 — CSV Adapter + ELT Skeleton
**Epic**: EPIC-1  
**Goal**: End-to-end import for Volunteers via CSV → staging → minimal DQ → create-only upsert.

### IMP-10 — CSV adapter & ingest contracts _(5 pts)_
**User story**: As an operator, I can ingest volunteers from a canonical CSV.  
**Acceptance Criteria**
- CSV header validation; helpful errors.  
- Rows written to `staging_volunteers` with `run_id`, raw payload, extracted counts.  
**Dependencies**: IMP-2.  
**Notes**: Document canonical fields.

**Canonical CSV columns (v1.0)**

| Column             | Required | Notes |
|--------------------|----------|-------|
| `external_system`  | No       | Defaults to `csv` when omitted. |
| `external_id`      | No       | Stable identifier from the source system. |
| `first_name`       | Yes      | Volunteer given name. |
| `last_name`        | Yes      | Volunteer family name. |
| `email`            | No       | Primary email; DQ ensures at least one of `{email, phone}` downstream. |
| `phone`            | No       | Primary phone in any readable format (normalized later). |
| `alternate_emails` | No       | Comma-separated list; stored raw for future DQ. |
| `alternate_phones` | No       | Comma-separated list; stored raw for future DQ. |
| `source_updated_at`| No       | ISO-8601 timestamp from source (used for freshness). |
| `ingest_version`   | No       | Contract version stamp to help migrations. |

> The adapter accepts sensible aliases (`First Name`, `Email Address`, `Phone Number`, etc.) and normalizes headers to the canonical names above.

**CLI usage (synchronous)**

```
flask importer run --source csv --file ops/testdata/importer_golden_dataset_v0/volunteers_valid.csv
```

The command creates an `import_run`, validates the header, stages rows (or performs a dry-run), and updates `counts_json`/`metrics_json` with `{rows_processed, rows_staged, rows_skipped_blank, dry_run, headers}`.

### IMP-11 — Minimal DQ: required & format _(5 pts)_
**User story**: As a data steward, invalid rows are quarantined with clear reasons.  
**Acceptance Criteria**
- Rules: must have `{email || phone}`; email format; phone E.164.  
- Violations logged with rule codes & details; good rows pass to next step.  
**Dependencies**: IMP-10.  
**Implementation Notes**
- Rule codes ship as: `VOL_CONTACT_REQUIRED`, `VOL_EMAIL_FORMAT`, `VOL_PHONE_E164` (all `error` severity today).  
- DQ engine writes status transitions (`LANDED → VALIDATED/QUARANTINED`) on `staging_volunteers`, with timestamps and first violation message stored in `last_error`.  
- Each violation is persisted into `dq_violations.details_json` with offending fields and values; `ImportRun.counts_json.dq.volunteers` aggregates `{rows_evaluated, rows_validated, rows_quarantined, rule_counts}` while `metrics_json` preserves full counts even for dry-runs.  
- CLI and worker summaries surface per-rule tallies so stewards can spot systemic issues immediately after a run.

### IMP-12 — Upsert (create-only) into core volunteers _(8 pts)_
**User story**: As an operator, clean new rows load into core; duplicates (by email) are skipped for now.  
**Acceptance Criteria**
- Inserts succeed; exact-email duplicates skipped; counters recorded in `counts_json`.  
- Batch transactions; no deadlocks.  
**Dependencies**: IMP-11.  
**Implementation Notes**
- Validated staging rows promote into `clean_volunteers` with normalized payloads, stable checksum (`staging_volunteers.checksum` copy), and provenance (`load_action`, core IDs when inserted).  
- Core load runs synchronously today, inserts `contacts`/`volunteers` plus primary `contact_emails`/`contact_phones`. Duplicate emails stay in clean w/ `load_action="skipped_duplicate"` and mark staging rows `LOADED` with explanatory `last_error`.  
- `ImportRun.counts_json.core.volunteers` tracks `{rows_processed, rows_created, rows_updated, rows_reactivated, rows_changed, rows_skipped_duplicates, rows_skipped_no_change, rows_missing_external_id, rows_soft_deleted, dry_run}` while `metrics_json` mirrors attempted creations during dry-runs. Logger emits per-run summaries and duplicate email/no-change lists for observability.  
- CLI/worker paths emit combined summaries; `flask importer run --summary-json` outputs machine-readable stats for automation/regression scripts. Golden data includes `volunteers_duplicate_skip.csv` to verify skip behavior.

### IMP-13 — CLI & admin action: start a run _(3 pts)_
**User story**: As an admin, I can start an import via CLI and UI.  
**Acceptance Criteria**
- `flask importer run --source csv --file <path>` returns `run_id`.  
- UI upload starts a run; run status visible.  
**Dependencies**: IMP-3.
**Implementation Notes**
- CLI enqueues runs to the Celery `imports` queue by default, emitting a JSON payload such as `{"run_id": 42, "task_id": "...", "status": "queued"}` to stdout so scripts can parse results. A `--inline` override keeps the synchronous path for local debugging and reuses the existing summary output hooks.
- `--summary-json` continues to stream the detailed payload only when the pipeline executes inline (e.g., during tests); queued executions rely on polling the run record for counters and status.

**Admin UI Flow**
- Upload form accepts CSV, performs lightweight validation (extension, size) client-side, and posts to a Flask endpoint that persists the file (temp storage or object store) and creates the `ImportRun` record with `triggered_by_user_id`.
- Server enqueues the Celery task with resolved file path/source metadata, then responds immediately with JSON `{run_id, task_id}`; the UI transitions to a run detail page or modal that polls `/importer/runs/<id>` for status and counters.
- Polling interval backs off (e.g., 1s → 5s) and surfaces progress: `pending` → `running` → `succeeded/failed`; failures expose `error_summary` and downloadable logs when available.
- UI surfaces links to download the original upload, view DQ violations count, and deep-link into the Runs dashboard (IMP-20) once it lands.

**Operational Considerations**
- Require the `manage_imports` (or equivalent) permission to upload; audit log `triggered_by_user_id`, client IP, and filename.
- Log enqueue/complete/failure events with Celery task ids for cross-correlation; emit metrics (run counts, latency) to the monitoring pipeline.
- Guard against duplicate submissions by disabling the submit button while enqueueing and by deduplicating identical files within a short TTL.
- Ensure storage lifecycle policy removes temporary uploads after the run concludes or after a retention window. Admin uploads set `keep_file=True` in `ingest_params_json` to retain files for retry capability; CLI runs default to `keep_file=False` since they reference existing files.
- Configuration knobs: `IMPORTER_UPLOAD_DIR` (defaults to `instance/import_uploads`), `IMPORTER_MAX_UPLOAD_MB` (25 MB default), and `IMPORTER_SHOW_RECENT_RUNS` (toggles dashboard table); document expected overrides in `env.example`.
- Maintenance CLI: `flask importer cleanup-uploads --max-age-hours <hours>` prunes stale local uploads for on-prem deployments without object storage. Note: this command should not remove files that are still referenced by runs with `keep_file=True`; consider filtering by run association or using a longer retention window.

**Retry Support**
- Failed or pending runs can be retried via CLI (`flask importer retry --run-id <id>`) or admin UI (Retry button in Recent Runs table).
- Retry requires `ImportRun.ingest_params_json` to be populated with `file_path`, `source_system`, `dry_run`, and `keep_file` flags. Runs created before retry support was added cannot be retried.
- Retry validates file existence before enqueueing; if the upload was cleaned up, retry will fail with a clear error message.
- On retry, the run status resets to `PENDING`, clears `error_summary`/`counts_json`/`metrics_json`, and re-enqueues the Celery task with the original parameters. Admin retries are logged via `AdminLog` with action `IMPORT_RUN_RETRIED`.

---

### Sprint 1 Completion Status

**Status**: ✅ **COMPLETE** — All core stories delivered and tested.

**Delivered Features**:
- ✅ CSV adapter with canonical field support and header normalization (`IMP-10`)
- ✅ Minimal DQ rules: `VOL_CONTACT_REQUIRED`, `VOL_EMAIL_FORMAT`, `VOL_PHONE_E164` (`IMP-11`)
- ✅ Create-only upsert with duplicate email detection (`IMP-12`)
- ✅ CLI and admin UI for triggering runs with async/sync modes (`IMP-13`)
- ✅ Worker process with SQLite transport (Redis optional) (`IMP-3`)
- ✅ Feature flag system and optional mounting (`IMP-1`)
- ✅ Base schema migrations (`IMP-2`)
- ✅ Golden dataset v0 with test scenarios (`IMP-4`)

**Test Coverage**:
- Unit tests: CSV adapter, DQ rules, pipeline stages, CLI commands
- Integration tests: End-to-end runs against golden dataset
- Test files: `test_importer_csv_adapter.py`, `test_importer_dq_minimal.py`, `test_importer_pipeline_*.py`, `test_importer_cli_csv.py`, `test_importer_feature_flag.py`

**Known Limitations & Deferred Items**:
- UI for viewing runs is basic (admin page shows recent runs table; full dashboard in Sprint 2)
- DQ violations viewable via database queries only (DQ inbox UI in Sprint 2)
- No remediation workflow yet (edit & requeue in Sprint 2)
- Dry-run mode implemented but not exposed in UI toggle (Sprint 2)
- Deterministic dedupe not yet implemented (Sprint 3)
- External ID mapping not yet used for idempotency (Sprint 3)

**Metrics & Observability**:
- `counts_json` populated with staging, DQ, and core load metrics
- `metrics_json` preserves full evaluation counts (including dry-runs)
- CLI `--summary-json` outputs machine-readable stats
- Worker health check via `flask importer worker ping` and `/importer/worker_health`

**Next Steps for Sprint 2**:
- Build Runs dashboard with filtering and drill-down
- Implement DQ inbox with export capability
- Add remediation workflow (edit & requeue)
- Expose dry-run toggle in UI
- Enhance run detail views with violation summaries

**See Also**: `docs/sprint1-retrospective.md` for detailed retrospective, lessons learned, and Sprint 2 recommendations.

---

## Sprint 2 — Runs Dashboard + DQ Inbox
**Epic**: EPIC-2  
**Goal**: Operator UX for monitoring runs and quarantines with basic remediation.

### IMP-20 — Runs dashboard _(5 pts)_
**User story**: As an admin, I can see runs with status and counts.  
**Acceptance Criteria**
- Columns: run id, source, started/ended, status, rows in/out, rejects.  
- Drill-down shows `counts_json` & timestamps.  
- Filters: source/status/date; pagination.  
**Dependencies**: IMP-13.
**Status**: ✅ Delivered in Sprint 2 — Dashboard lists runs with summary cards, auto-refresh, drill-down modal, retry/download, and dry-run indicators.

**UI Wireframe & Layout**:
- **Main table**: Sortable columns (run_id, source, status badge, started_at, ended_at, duration, rows_staged, rows_validated, rows_quarantined, rows_created, rows_updated, rows_skipped_no_change, rows_skipped_duplicates)
- **Status badges**: Color-coded (pending=yellow, running=blue, succeeded=green, failed=red, partially_failed=orange)
- **Filters**: Dropdowns for source (`csv`, future adapters), status (all/pending/running/succeeded/failed), date range picker (last 7/30/90 days, custom)
- **Pagination**: 25/50/100 rows per page; total count displayed
- **Drill-down modal/page**: Expandable row or detail route (`/importer/runs/<id>`) showing:
  - Full `counts_json` breakdown (staging, DQ, core) with nested JSON viewer
  - `metrics_json` for dry-runs
  - `error_summary` if failed
  - Links to DQ violations count (deep-link to inbox filtered by run_id)
  - Download original upload (if `keep_file=True`)
  - Retry button (if failed/pending and retry-capable)
- **Dashboard polish**:
  - Topline summary cards (runs in view, health breakdown, leading source, auto-refresh cadence)
  - Auto-refresh toggle (default 30s) with manual refresh button and spinner feedback
  - Bootstrap toasts for error/success feedback, copy-to-clipboard for counts digest
  - Graceful empty states, filter/reset UX, pagination summary `x–y of z`
  - Accessible modal with `aria-live` updates, keyboard focus management, responsive table
- **Actions & safeguards**:
  - Retry action posts to `/admin/imports/<run_id>/retry` with optimistic toast
  - Download original upload via `/admin/imports/<run_id>/download` with path whitelisting
  - Copy JSON quick action (counts digest) for incident triage
  - Audit log entry (`IMPORT_RUN_VIEW` / `IMPORT_RUN_DETAIL_VIEW`) on every interaction
  - 401/403 JSON responses for API calls (no redirects), consistent error envelope `{"error": "..."}`

**Access Control**:
- Route: `/importer/runs` (or `/admin/imports/runs` if namespaced)
- Permission: `manage_imports` or equivalent admin role
- Audit: Log view events (run_id, user_id, timestamp) for compliance

**Metrics & Telemetry**:
- Track dashboard load time (p95/p99)
- Track filter/pagination interactions (client-side events)
- Expose run counts via API endpoint for external monitoring: `GET /importer/runs/stats?source=csv&status=succeeded&days=7`
- Dashboard should render within 2s for 1000 runs (indexed queries, pagination)
- Prometheus metrics exposed via `ImporterMonitoring`:
  - `importer_runs_list_requests_total`, `importer_runs_list_request_seconds`, `importer_runs_list_result_size`
  - `importer_runs_detail_requests_total`, latency histogram, and stats variants
- **New counters (Sprint 2)**: `importer_runs_enqueued_total{status="success",dry_run="true|false"}`, `importer_dry_run_total{status}`, and `importer_dry_run_request_seconds` histogram record enqueue/dry-run telemetry.
- Structured logs attach `importer_*` fields (status, source, response_time_ms, run_id)
- Client telemetry hooks via `data-component`/`data-action` attributes for future instrumentation

**Testing Expectations**:
- **Unit tests**: Dashboard route handlers, filter/pagination logic, JSON serialization
- **Integration tests**: Render dashboard with 50+ runs, verify filters, pagination, drill-down
- **Golden data**: Use existing runs from Sprint 1 test fixtures; create test runs with various statuses
- **UI tests**: Verify status badge colors, filter dropdowns, pagination controls (HTML structure)
- **Performance tests**: Load dashboard with 1000 runs, verify <2s render time
- **Telemetry verification**: Assert Prometheus counters increment (smoke), audit log entries persisted
- **Download security**: Ensure upload download path is constrained to `import_uploads/` root, 404 on tampering
- **Accessibility checks**: axe-core pass for modal/table, keyboard navigation validated manually

### IMP-21 — DQ inbox (basic) with export _(8 pts)_
**User story**: As a steward, I can filter violations and export them.  
**Acceptance Criteria**
- Filter by rule/severity/run; row detail shows raw & normalized views.  
- Export CSV of violations.  
**Dependencies**: IMP-11.
**Status**: ✅ Delivered in Sprint 2 — Inbox includes filters, CSV export, violation detail modal, remediation launcher, and remediation stats cards.

**UI Wireframe & Layout**:
- **Main table**: Columns (violation_id, run_id link, staging_volunteer_id, rule_code badge, severity badge, status badge, created_at, staging row preview)
- **Filters**: Rule code dropdown (populated from `dq_violations.rule_code` distinct), severity (all/error/warn/info), run_id (autocomplete or dropdown), date range
- **Row detail modal/sidebar**: Click row to expand showing:
  - Raw staging payload (`staging_volunteers.payload_json`) formatted JSON viewer
  - Normalized preview (extracted fields: first_name, last_name, email, phone)
  - Violation details (`dq_violations.details_json`) with highlighted offending fields
  - Remediation hints (rule-specific guidance)
  - Actions: Edit & Requeue (IMP-22), Suppress (future), Mark as Won't Fix (future)
- **Export button**: Generates CSV with columns: violation_id, run_id, rule_code, severity, status, staging_row_data (flattened), violation_details, created_at
- **Bulk actions toolbar**: Select multiple violations, bulk export, bulk suppress (future)
- **Dashboard polish**:
  - Summary cards (total, by severity, by status, top rule) with live stats endpoint
  - Status/severity badges aligned with palette; tooltips/hints surfaced in detail modal
  - Admin nav entry under `Admin ▸ DQ Inbox` gated by importer flag/permissions
  - Responsive table with wrapping preview text and accessible pagination/ARIA updates
  - Toast notifications for errors, CSV export feedback

**Access Control**:
- Route: `/importer/dq-inbox` (or `/admin/imports/violations`)
- Permission: `manage_imports` or `view_imports` (read-only) vs `remediate_imports` (edit actions)
- PII considerations: Mask sensitive fields (email, phone) for non-admin roles (future enhancement)

**Metrics & Telemetry**:
- Track violation counts by rule_code (dashboard widget or summary card)
- Track export events (user_id, rule_code filter, row count)
- Expose violation stats API: `GET /importer/violations/stats?rule_code=VOL_CONTACT_REQUIRED&days=7`
- Export CSV should sanitize formula injection (prepend `'` to cells starting with `=`, `+`, `-`, `@`)
- Prometheus metrics: list/detail/stats/export counters & latency histograms (`importer_dq_*`) + export row count histogram
- Structured logs attach `dq_` prefixed fields (rule_code, response time, row counts) to facilitate incident review
- API surface: rule code lookup (`GET /importer/violations/rule_codes`) for dynamic filter population

**Testing Expectations**:
- **Unit tests**: Violation query filters, CSV export sanitization, JSON serialization
- **Integration tests**: Filter by rule_code, export CSV, verify file download, verify CSV injection prevention
- **Golden data**: Use `volunteers_invalid.csv` from golden dataset; verify expected violations appear
- **UI tests**: Verify filter dropdowns, row detail modal, export button (HTML structure)
- **Security tests**: Verify CSV export sanitization prevents formula injection

### IMP-22 — Remediate: edit & requeue _(8 pts)_
**User story**: As a steward, I can fix a quarantined row and requeue it.  
**Acceptance Criteria**
- Edit form validates; on save, DQ re-runs; if clean, row proceeds to upsert.  
- Violation status moves to `fixed`; audit recorded.  
**Dependencies**: IMP-21, IMP-12.

**UI Wireframe & Layout**:
- **Edit form modal/page**: Pre-populated with staging row fields (first_name, last_name, email, phone, etc.)
- **Field-level validation**: Real-time client-side validation matching DQ rules (email format, phone E.164, contact required)
- **Save & Requeue button**: On submit:
  1. Validate form client-side
  2. POST to `/importer/violations/<violation_id>/remediate` with edited payload
  3. Server re-runs DQ rules on edited row
  4. If clean: proceed to upsert (single-row import), update violation status to `fixed`, create audit log
  5. If still invalid: return validation errors, keep violation status `open`, show new violation details
- **Success feedback**: Toast notification "Row fixed and queued for import" with link to new run
- **Error feedback**: Display validation errors inline, highlight offending fields

**Access Control**:
- Route: `POST /importer/violations/<id>/remediate`
- Permission: `remediate_imports` or equivalent (stricter than view-only)
- Audit: Log remediation events (violation_id, user_id, edited_fields JSON diff, timestamp, outcome)
**Status**: ✅ Delivered in Sprint 2 — JSON edit modal with validation, single-row remediation run, audit trail, and remediation stats endpoint.

**Metrics & Telemetry**:
- Track remediation success rate (fixed vs still-quarantined)
- Track common fixes (which fields edited most often, which rules resolved)
- Expose remediation stats: `GET /importer/remediation/stats?days=30`
- Re-queue should create a new mini-run (single-row import) or batch with other remediated rows
- **New endpoints**: `/admin/imports/remediation/stats?days=<N>` powers DQ inbox summary cards; responses feed remediation success telemetry dashboards.

**Testing Expectations**:
- **Unit tests**: Edit form validation, DQ re-run logic, violation status transitions, audit logging
- **Integration tests**: Edit row, save, verify DQ re-run, verify upsert if clean, verify violation status update
- **Golden data**: Use violations from `volunteers_invalid.csv`, fix email format, verify resolution
- **UI tests**: Verify form pre-population, validation errors, success/error feedback (HTML structure)
- **Edge cases**: Multi-violation rows (fix one, verify others remain), partial edits (null handling)

### IMP-23 — Dry-run mode _(3 pts)_
**User story**: As an operator, I can simulate an import without writing to core.  
**Acceptance Criteria**
- `--dry-run`/UI toggle executes pipeline but skips core writes; run clearly labeled.  
**Dependencies**: IMP-12, IMP-20.
**Status**: ✅ Delivered in Sprint 2 — UI/CLI propagate `dry_run`, runs tagged with DRY RUN badges, detail messaging, Prometheus counters, and include-dry-runs filter.

**UI Wireframe & Layout**:
- **Upload form toggle**: Checkbox "Dry run (no writes to database)" above file upload
- **CLI flag**: `--dry-run` already implemented; ensure UI passes flag to backend
- **Run badge**: Dry-run runs show special badge "DRY RUN" in dashboard (distinct from status)
- **Run detail**: Clear messaging "This was a dry run. No data was written to core tables."
- **Metrics display**: Show what would have been inserted/updated (from `metrics_json`)

**Access Control**:
- Permission: Same as regular import (`manage_imports`)
- Audit: Log dry-run events (user_id, file, dry_run=true)

**Metrics & Telemetry**:
- Track dry-run usage (frequency, user_id)
- Dry-run runs should still populate `metrics_json` with full evaluation counts
- Dashboard filter: "Include dry runs" toggle (default: show all)
- `GET /importer/runs/stats?include_dry_runs=0|1` provides aggregate counts for monitoring dashboards; ensure API response labels dry-run state.

**Testing Expectations**:
- **Unit tests**: Dry-run flag propagation, core write skip logic, metrics_json population
- **Integration tests**: Upload with dry-run toggle, verify no core inserts, verify metrics_json populated
- **Golden data**: Run `volunteers_valid.csv` with dry-run, verify counts in metrics_json, verify no core records
- **UI tests**: Verify dry-run checkbox, badge display, messaging (HTML structure)

---

### Sprint 2 Completion Status

**Status**: ✅ **COMPLETE** — Dashboard, DQ inbox, remediation, and dry-run UX shipped.

**Delivered Features**:
- ✅ Runs dashboard with filters, auto-refresh, drill-down modal, retry/download, and dry-run labels (`IMP-20`)
- ✅ DQ inbox with rule/severity filters, CSV export, remediation launcher, and stats cards (`IMP-21`)
- ✅ Remediation workflow with steward edit modal, DQ re-run, audit logging, and remediation metrics endpoint (`IMP-22`)
- ✅ Dry-run UI toggle, run badges, include-dry-runs filter, and telemetry counters (`IMP-23`)

**Test Coverage**:
- Unit tests: run filters & serialization, violation queries, remediation service, dry-run propagation
- Integration tests: admin remediation API, runs list filters, dry-run pipeline behavior, CSV export
- UI/JS tests: dashboard interactions, DQ inbox modal submission, dry-run checkbox/error handling
- Golden data: `volunteers_invalid.csv` remediation fix, `volunteers_valid.csv` dry-run verification

**Metrics & Observability**:
- Added Prometheus counters/histograms for dry-run enqueue + latency (`importer_runs_enqueued_total`, `importer_dry_run_total`, `importer_dry_run_request_seconds`)
- Remediation stats endpoint surfaces success/failure rates and common fixes
- Dashboard includes dry-run filter state in API payloads for analytics

**Known Limitations & Follow-ups**:
- DQ inbox lacks bulk actions (suppress/mark won’t fix) — backlog for Sprint 3+
- Remediation runs execute sequentially; batching noted for evaluation in Sprint 3
- Need expanded golden dataset scenarios for idempotent replays and deterministic dedupe (Sprint 3 prep)

**Next Steps for Sprint 3**:
- Implement `external_id_map`-driven idempotent upsert and deterministic dedupe
- Define survivorship rules and change log recording for updates
- Extend golden dataset with replay + duplicate scenarios; add regression tests for idempotency (`IMP-33`)
- Capture additional telemetry for update vs insert paths and dedupe outcomes

---

## Sprint 3 — Idempotency + Deterministic Dedupe
**Epic**: EPIC-3  
**Goal**: True idempotency via `external_id_map`; deterministic matching (email/phone); survivorship v1.

### Sprint 3 Overview
- **Theme**: Harden ingestion so repeated runs, deterministic identity decisions, and conflict resolution stay consistent without manual cleanup.
- **Shared architecture work**: Align loader, dedupe, and survivorship stages around a common `resolve_import_target` helper backed by `external_id_map`.
- **Data & schema**: Evaluate `external_id_map` index coverage, add `ingest_version`/`last_seen_at` defaults, and stage Alembic migrations ahead of dev work.
- **Operational readiness**: Document retry behavior changes for support, define rollback steps if survivorship overwrites regress, and brief QA on new regression suites.
- **Risks / assumptions**: Consistent normalization (email/phone), availability of external IDs in staging, and acceptable latency for repeated `external_id_map` lookups.
- **Clarifications requested**: Confirm external system namespaces, whether survivorship precedence differs by field group, and who owns dashboard updates for new counters.

### IMP-30 — External ID map & idempotent upsert _(8 pts)_
**User story**: As an operator, retries do not create duplicates.  
**Acceptance Criteria**
- `(external_system, external_id)` recorded; `first_seen_at`/`last_seen_at` maintained.  
- Retries update not insert; counters reflect created/updated/skipped.  
- `counts_json.core.volunteers` tracks `rows_created`, `rows_updated`, `rows_skipped_no_change`.  
- DQ/retry flows respect external IDs and avoid duplicate staging promotions.  
**Dependencies**: IMP-2, IMP-12.
**Status**: 🚧 Planned for Sprint 3 kickoff.
**Implementation Notes (Sprint 3 prep)**:
- Reuse `external_id_map` schema from IMP-2; ensure staging rows populate `external_system`/`external_id` before promotion.
- Add soft-delete columns (`deactivated_at`, `upstream_deleted_reason`) and normalize `is_active` semantics so loader/reactivation logic can avoid destructive deletes while preserving history.
- Loader should lookup `external_id_map` to decide between `UPDATE` vs `INSERT`, writing outcomes to `counts_json.core.volunteers`.
- Persist provenance in `change_log` when updates occur; include `ingest_version` for conflict tracking.
- Expose run-level metrics: `rows_updated`, `rows_created`, `rows_skipped_no_change`, `rows_missing_external_id`, `rows_reactivated`.

**Implementation Outline**:
- Introduce shared `resolve_import_target(volunteer_row)` wrapping normalization and `external_id_map` lookup for loader + remediation reuse.
- On misses, create core person and seed `external_id_map` with `first_seen_at`; on hits, route to update workflow and bump `last_seen_at`.
- Update promotion job to persist `ingest_version` on `external_id_map` and tie `change_log` entries back to the triggering run.
- Adjust retry controller to short-circuit inserts when `external_id_map` already links a core record.
- Surface actionable errors when incoming payloads omit `external_id`; quarantine those rows with descriptive remediation guidance.

**Data Model & Storage**:
- Add covering index on `external_id_map(external_system, external_id, core_person_id)`.
- Backfill missing `external_system` values and set default `last_seen_at` via migration.
- Append nullable `ingest_version` column (Alembic) populated from run metadata.

**Metrics & Telemetry**:
- Emit Prometheus counters `importer_idempotent_rows_created_total`, `importer_idempotent_rows_updated_total`, `importer_idempotent_rows_skipped_total` (labeled by source system).
- Log `idempotency_action` and `external_id_hit` fields for each loader decision alongside soft-delete transitions.
- Surface counters (`rows_created`, `rows_updated`, `rows_reactivated`, `rows_skipped_no_change`, `rows_missing_external_id`, `rows_skipped_duplicates`) in run summary payloads for dashboard consumption.

**Testing Expectations**:
- **Unit**: `resolve_import_target`, loader branching, change-log serialization.
- **Integration**: Replay same file after success + after payload change; assert no duplicate inserts and counters update correctly.
- **Regression**: Verify imports missing external IDs fail fast with actionable errors and surface quarantine status.
- **Golden data**: Extend dataset with repeated external IDs covering insert/update/skip cases.

**Open Questions / Clarifications**:
- ✅ Soft deletes handled: `external_id_map` retains inactive links (`is_active=false`, `deactivated_at`, `upstream_deleted_reason`) and loader reactivates them on reappearance.
- Should modified retries increment a distinct `rows_changed` counter?
- Who will implement FE changes for the new idempotency counters in dashboards?

### IMP-31 — Deterministic dedupe (email/phone) _(8 pts)_
**User story**: As a steward, exact matches resolve to the same core person.  
**Acceptance Criteria**
- Blocking on normalized email & E.164 phone; updates instead of inserts.  
- Counters for resolved vs inserted.  
- `dedupe_suggestions` captures `decision="auto_resolved"` for deterministic matches.  
- `counts_json.core.volunteers` increments `rows_deduped_auto`.  
**Dependencies**: IMP-30.
**Status**: 🟢 Delivered (Nov 2025) — gated on IMP-30 rollout.
**Implementation Notes (Sprint 3 prep)**:
- Normalize inputs with existing helper (`normalize_contact_fields`) prior to lookup.
- Priority: email match → phone match → combined heuristics; flag ambiguous cases for future FUZZY dedupe.
- Record dedupe decisions in `dedupe_suggestions` with `decision="auto_resolved"` for audit.
- Update UI summaries to highlight when runs resolve duplicates vs create new contacts.
- Runs dashboard exposes `rows_deduped_auto` in the list view (auto-resolved card + per-row badge) and detail modal for steward confirmation.
- Rows lacking both email and phone remain manual remediation; deterministic flow requires at least one normalized key.

**Implementation Outline**:
- Layer deterministic checks immediately after external ID resolution: email → phone → combined heuristic.
- When match found, route to update path and pass normalized payload into survivorship helper.
- Persist result in `dedupe_suggestions` with `match_type` (`email`, `phone`, `combined`) and provenance data.
- Funnel ambiguous multi-match cases into backlog queue for future fuzzy dedupe flow.

**Data Model & Storage**:
- Add index on `core_people.normalized_email` and confirm E.164 storage for `normalized_phone`.
- Extend `dedupe_suggestions` with `match_type` and optional `confidence_score` (default `1.0` for deterministic).
- Ensure run summary schema supports `rows_deduped_auto`.

**Metrics & Telemetry**:
- Emit `importer_dedupe_auto_total{match_type}` and response-time histogram for deterministic checks.
- Include dedupe outcomes in structured logs (`dedupe_decision`, `dedupe_match_type`).
- Surface resolved vs inserted counts in dashboard summary cards.

**Testing Expectations**:
- **Unit**: Normalization pathways, deterministic match branching, audit writes.
- **Integration**: Import duplicates across email/phone combos; confirm updates not inserts and counters accurate.
- **Golden data**: Create fixtures for email-only, phone-only, and dual-match scenarios plus ambiguous matches.
- **UI**: Smoke-test dashboard summary for dedupe counts, ensure no regressions.

**Open Questions / Clarifications**:
- ❗ Contacts without email/phone remain manual until fuzzy dedupe work lands (no auto resolution).
- ✅ Deterministic dedupe treats case-insensitive emails with plus addressing as the same record.
- UX approvals handled by importer squad lead (no change to existing workflow).

### IMP-32 — Survivorship v1 _(5 pts)_
**User story**: As a steward, conflicts resolve predictably.  
**Acceptance Criteria**
- Prefer non-null; prefer manual edits; prefer most-recent verified.  
- Change log entries created.  
- Per-field decisions include before/after payloads and `source_run_id`.  
- Admin UI surfaces survivorship summary in run detail.  
**Dependencies**: IMP-31.
**Status**: ⚪ Discovery in progress — precedence matrix pending sign-off.
**Implementation Notes (Sprint 3 prep)**:
- Define field precedence tables (manual remediation > source freshest > existing core). Final implementation lives in `config/survivorship.py` with per-field-group profiles and optional overrides via `IMPORTER_SURVIVORSHIP_PROFILE_PATH`.
- Store per-field decisions in `change_log` with before/after payloads, winner/loser sources, and `source_run_id` where available.
- Provide helper for comparing timestamps/verified flags; reuse in remediation success analytics. When timestamps tie, the engine keeps the prior core value so results remain deterministic.
- Update admin UI messaging to surface survivorship outcomes when viewing run detail and surface the active profile summary in the dashboard header.

**Implementation Outline**:
- Implement `apply_survivorship(core_person, incoming_payload, context)` returning merged record plus decision log.
- Persist change-log entries with per-field provenance, including `ingest_version` and verification timestamps (when present), plus manual override provenance.
- Update run detail API to expose survivorship breakdown (counts and notable overrides) for the UI and provide summary counters for dashboard cards.
- Coordinate with remediation tooling so manual edits register as highest-precedence inputs (leveraging `edited_fields_json` / `edited_payload_json` on violations and remediation run metadata).

**Data Model & Storage**:
- Extend `change_log` with `field_name`, `provenance_json`, and `verified_at` metadata if missing.
- Evaluate need for `core_people.last_verified_at` (or equivalent) to inform precedence.
- Confirm migrations land prior to QA so fixtures stay consistent.

**Metrics & Telemetry**:
- Add `importer_survivorship_decisions_total{decision}` counter capturing override vs keep scenarios.
- Log warnings when survivorship overrides recent manual remediation to flag potential misconfigurations.
- Include survivorship summary in dashboard/API payloads for transparency and surface the active profile metadata in the admin dashboard.

**Testing Expectations**:
- **Unit**: Precedence matrix permutations, helper comparisons for timestamps/verified flags.
- **Integration**: Conflict imports verifying change-log entries and UI payload updates.
- **Golden data**: Scenarios where verified data should prevail vs newest but unverified data.
- **Regression**: Ensure survivorship honors dry-run mode and remediation flows. Extend golden dataset fixtures with conflict rows covering manual wins vs. incoming overrides.

**Open Questions / Clarifications**:
- ✅ Tie-breaker when timestamps share identical precision: keep the pre-existing core value so results remain deterministic.
- ✅ Precedence configurable per field group via profiles (contact identity, communication, notes).
- ✅ Admin UI copy handled within importer dashboard (profile banner + run detail summary).

### IMP-33 — Idempotency regression tests _(3 pts)_
**User story**: As QA, running the same file twice yields no net new records.  
**Acceptance Criteria**
- Replay test passes; diffs only when payload changed.  
- Metrics emitted for created vs updated vs skipped remain stable between runs.  
- `idempotency_summary.json` artifact generated for dashboards.  
**Dependencies**: IMP-30.
**Status**: 🟢 Ready to start once IMP-30 lands.
**Implementation Notes (Sprint 3 prep)**:
- Extend golden dataset with duplicate IDs and changed payload revisions.
- Add pytest fixture to run same CSV twice (dry-run + real run) asserting counts + external map stability.
- Cover edge cases where contact data changes but dedupe path should update rather than insert.
- Capture regression metrics via CI job (export `idempotency_summary.json`) for dashboards.

**Implementation Outline**:
- Build pytest scenario executing dry-run then real run with identical file, asserting zero net new core records.
- Create helper assertions ensuring `external_id_map` entries remain stable apart from timestamp updates.
- Integrate regression suite into CI (`tests/importer/test_idempotency_regression.py`), publishing `idempotency_summary.json` artifacts for dashboards.

**Data & Fixtures**:
- Expand golden dataset with identical replays, changed payloads, and deterministic dedupe coverage.
- Annotate fixtures with expected counters and survivorship outcomes for quick validation (see `ops/testdata/importer_golden_dataset_v0/README.md`).
- Document regeneration process when schema or counters evolve.

**Metrics & Telemetry**:
- Push synthetic metrics from regression suite into monitoring sandbox to validate dashboard ingestion.
- Emit `idempotency_summary.json` under `instance/import_artifacts/run_<id>/` and mirror to `ci_artifacts/idempotency/` for CI consumption.
- Prefix monitoring labels via `IMPORTER_METRICS_ENV` (default `sandbox`); disable production emission with `IMPORTER_METRICS_SANDBOX_ENABLED`.
- Alert on deltas >0 in created rows between replay runs.
- Log test run IDs and outcomes for traceability. Regression failures surfaced via dashboards are triaged by the importer maintainer (Admir).

**Testing Expectations**:
- **Pytest**: Parametrize dry-run vs live run combos and multiple sources.
- **Pytest regression suite**: `tests/importer/test_idempotency_regression.py` exercises replays, changed payloads, deterministic dedupe, and partial/out-of-order subsets.
- **CLI smoke**: Validate scripted replay via existing tooling (e.g. admin helpers).
- **CI**: Ensure run completes in <5 minutes and blocks merge on regression.

**Open Questions / Clarifications**:
- ✅ Covered: partial file replays or out-of-order retries (`test_partial_replay_subset_is_idempotent`).
- ✅ Covered: regression failures surfaced via dashboards are triaged by the importer maintainer (Admir).
- ✅ Covered: use `IMPORTER_METRICS_SANDBOX_ENABLED` + `IMPORTER_METRICS_ENV` to keep regression metrics out of production dashboards until we're ready.
---

## Sprint 4 — Salesforce Adapter (Optional)
**Epic**: EPIC-4  
**Goal**: Optional Salesforce ingestion using existing queries/SOQL; incremental via watermark.

### IMP-40 — Adapter loader & optional deps _(3 pts)_
**User story**: As an operator, Salesforce is installable only when needed.  
**Acceptance Criteria**
- `[salesforce]` extra declared; clear error if misconfigured.  
**Dependencies**: IMP-1.

### IMP-41 — Salesforce extract → staging _(8 pts)_
**User story**: As an operator, Contacts pull incrementally into staging.  
**Acceptance Criteria**
- `since` watermark respected; raw payload stored; rate-limit backoff.  
- Partial failures logged to run; retries safe.  
**Dependencies**: IMP-40, IMP-3.

### IMP-42 — Salesforce → canonical mapping v1 _(8 pts)_
**User story**: As a dev, SF fields map to `VolunteerIngest`.  
**Acceptance Criteria**
- Declarative mapping file; unmapped fields surfaced in run summary.  
- Required/format DQ applied; violations created.  
**Dependencies**: IMP-41, IMP-11.

### IMP-43 — Incremental upsert & reconciliation counters _(5 pts)_
**User story**: As an operator, I see created/updated/unchanged counts for the window.  
**Acceptance Criteria**
- Counters visible; `max(source_updated_at)` recorded.  
**Dependencies**: IMP-42, IMP-30.

---

## Sprint 5 — Fuzzy Dedupe + Merge UI
**Epic**: EPIC-5  
**Goal**: Human-in-the-loop identity resolution; auto-merge & undo.

### IMP-50 — Candidate generation & scoring _(8 pts)_
**User story**: As a steward, likely duplicates appear with scores & features.  
**Acceptance Criteria**
- Blocking keys (email/phone/name+zip); features (name, DOB, address, employer/school).  
- Scores stored in `dedupe_suggestions` with features JSON; thresholds configurable.  
**Dependencies**: IMP-31.

### IMP-51 — Merge UI _(13 pts)_
**User story**: As an admin, I can compare, choose field winners, and merge safely.  
**Acceptance Criteria**
- Side-by-side compare; field highlights; survivorship controls.  
- On merge: `merge_log`, `external_id_map` unify, `change_log` diffs recorded.  
- Actions: accept, reject, defer.  
**Dependencies**: IMP-50, IMP-32.

### IMP-52 — Auto-merge + undo merge _(8 pts)_
**User story**: As an operator, obvious dupes auto-merge; I can undo.  
**Acceptance Criteria**
- Auto-merge for score ≥ threshold; undo restores state fully.  
**Dependencies**: IMP-51.

### IMP-53 — Dedupe metrics on runs _(3 pts)_
**User story**: As an admin, I see auto-merged & needs-review counts per run.  
**Acceptance Criteria**
- New run columns and links to review queue.  
**Dependencies**: IMP-50.

---

## Sprint 6 — Reconciliation, Anomalies, Alerts
**Epic**: EPIC-6  
**Goal**: Detect leaks/staleness/spikes; trend views; operator alerts.

### IMP-60 — Reconciliation & freshness _(8 pts)_
**User story**: As an operator, I know if data is stale or missing.  
**Acceptance Criteria**
- Freshness (`now - max(source_updated_at)`); thresholds; run labels.  
- Source vs core counts; hash parity spot checks; metrics saved to `counts_json`.  
**Dependencies**: IMP-43.

### IMP-61 — Anomaly detectors _(8 pts)_
**User story**: As a PM, I see drift in rejects/dupes/null rates.  
**Acceptance Criteria**
- Delta guard (3σ), null drift (2× baseline), rule offenders ranked.  
- Flags shown on runs and Source Health page.  
**Dependencies**: IMP-60.

### IMP-62 — Alerts (email/Slack/webhook) _(5 pts)_
**User story**: As an operator, I’m notified on failures or critical anomalies.  
**Acceptance Criteria**
- Channels configurable; links point to run/queue; on/off per source.  
**Dependencies**: IMP-61.

### IMP-63 — Trend views _(5 pts)_
**User story**: As a PM, I can view 30-day trends for ingests/rejects/dupes/freshness.  
**Acceptance Criteria**
- Charts render; filterable dates; export CSV/PNG.  
**Dependencies**: IMP-60.

---

## Sprint 7 — Mapping Versioning + Config UI + Backfills
**Epic**: EPIC-7  
**Goal**: Version mappings; in-app config; safe backfills.

### IMP-70 — Versioned mappings _(8 pts)_
**User story**: As a dev, I can evolve mappings without breaking history.  
**Acceptance Criteria**
- `mapping_version` stored on runs; UI shows current/prior; unmapped field warnings.  
**Dependencies**: IMP-42.

### IMP-71 — Config UI & thresholds _(8 pts)_
**User story**: As an admin, I can tune thresholds, rules, and schedules.  
**Acceptance Criteria**
- Edit dedupe thresholds, anomaly thresholds, cron schedule, rule modes (warn/enforce); audit config changes.  
**Dependencies**: IMP-60, IMP-61.

### IMP-72 — Backfill UX & CLI _(5 pts)_
**User story**: As an operator, I can backfill since a date, with dry-run.  
**Acceptance Criteria**
- `--since` param; run labeled “backfill”; concurrency caps; pausable.  
**Dependencies**: IMP-43.

### IMP-73 — Mapping diffs & suggestions _(5 pts)_
**User story**: As a dev, I get suggestions when new SF fields appear.  
**Acceptance Criteria**
- Run summary lists unmapped fields with samples; exportable.  
**Dependencies**: IMP-70.

---

## Sprint 8 — Events & Signups/Attendance
**Epic**: EPIC-8  
**Goal**: Bring pipeline to Events + Signups/Attendance with cross-entity DQ.

### IMP-80 — Staging + contracts for Events/Signups _(8 pts)_
**User story**: As an operator, I can ingest events and signups via CSV/SF.  
**Acceptance Criteria**
- `staging_events`, `staging_signups` exist; contracts validate times & required fields.  
**Dependencies**: IMP-2, IMP-41.

### IMP-81 — Reference DQ & FK checks _(8 pts)_
**User story**: As a steward, cross-entity references are validated.  
**Acceptance Criteria**
- FKs resolved via `external_id_map`/core keys; violations `REF-401` with hints.  
**Dependencies**: IMP-80.

### IMP-82 — Upsert for events & attendance _(8 pts)_
**User story**: As an operator, events/signups upsert idempotently.  
**Acceptance Criteria**
- `(external_system, external_id)` maintained; hours & attendance flags correct.  
**Dependencies**: IMP-81, IMP-30.

### IMP-83 — Cross-entity dashboards _(5 pts)_
**User story**: As a PM, I can view pipeline health across entities.  
**Acceptance Criteria**
- Filters by entity; combined metrics; links to entity-specific queues.  
**Dependencies**: IMP-82.

---

## Sprint 9 — Security, Audit, Packaging
**Epic**: EPIC-9  
**Goal**: Harden for PII; clear roles; audit trails; packaging & OSS readiness.

### IMP-90 — RBAC & sensitive-field gating _(8 pts)_
**User story**: As an admin, roles control visibility and actions (DOB, merges).  
**Acceptance Criteria**
- Roles: Admin, Data Steward, Viewer; masks for sensitive fields; merge/undo require Admin.  
**Dependencies**: IMP-51.

### IMP-91 — Audit completeness _(5 pts)_
**User story**: As compliance, every admin action is logged.  
**Acceptance Criteria**
- Audits for edits, suppressions, merges, config changes; exportable trail.  
**Dependencies**: IMP-22, IMP-51, IMP-71.

### IMP-92 — Retention & PII hygiene _(5 pts)_
**User story**: As a steward, staging/quarantine have retention (e.g., 90 days) and safe exports.  
**Acceptance Criteria**
- TTL jobs purge/anonymize; CSV export neutralizes formula injection.  
**Dependencies**: IMP-21.

### IMP-93 — Packaging & adapter extras _(5 pts)_
**User story**: As a dev, I can install with or without Salesforce.  
**Acceptance Criteria**
- Optional deps groups `[importer]`, `[salesforce]`; README quickstart; sample data & screenshots.  
**Dependencies**: IMP-40.

---

## Backlog (Nice-to-Have)
- Streaming/near-real-time ingestion (webhooks/CDC).  
- OpenTelemetry tracing with `run_id` correlation.  
- Household modeling (shared emails/phones for minors).  
- Address verification (USPS/LoQate) & geocoding.  
- Schema drift auto-PRs when mapping changes.  
- Microservice extraction (shared DB or queue boundary).  
- Advanced anomaly detection (seasonality via STL/Prophet).

---

## Roles & RACI
- **PM**: backlog, priorities, acceptance review.  
- **Backend**: pipelines, adapters, idempotency, dedupe engine.  
- **Full‑stack**: Runs/DQ/Merge/Health/Config UIs.  
- **QA/Data Steward**: golden data, DQ tuning, review workflows.  
- **Ops**: secrets, worker scaling, alert channels.

---

## Risk Register
- **Over‑coupling to web app** → strict module boundaries; feature flags.  
- **Migration collisions** → namespaced tables; idempotent migrations.  
- **Data churn from bad dedupe** → start deterministic + high thresholds; enable auto‑merge later.  
- **Rate limits/long backfills** → concurrency caps; retry/backoff; pausable runs.  
- **PII exposure** → RBAC, masking, audit logs, retention policies.
