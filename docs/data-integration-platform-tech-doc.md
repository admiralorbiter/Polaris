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
- `docs/sprint2-retrospective.md` — Sprint 2 completion retrospective, lessons learned, and recommendations for Sprint 3
- `docs/sprint3-retrospective.md` — Sprint 3 completion retrospective, lessons learned, and recommendations for Sprint 4
- `docs/sprint4-retrospective.md` — Sprint 4 completion retrospective, lessons learned, and recommendations for Sprint 5

**Operational Guides**:
- `docs/importer-feature-flag.md` — Feature flag configuration, troubleshooting, and verification checklist
- `docs/commands.md` — CLI command reference with troubleshooting and debugging tips
- `docs/importer-dor.md` — Definition of Ready checklist for importer tickets
- `docs/importer-dod.md` — Definition of Done checklist for importer tickets
- `docs/salesforce-mapping-guide.md` — Salesforce mapping architecture, vertical/horizontal scaling guidance, and troubleshooting
- `docs/salesforce-transforms-reference.md` — Transform registry reference with patterns for custom mapping transforms
- `docs/salesforce-mapping-examples.md` — Copy/paste mapping recipes and real-world examples for expanding adapters

**Test Data & Scenarios**:
- `ops/testdata/importer_golden_dataset_v0/README.md` — Golden dataset documentation with expected outcomes

---

## Epics Overview

- **EPIC-0**: Foundations — feature flags, schema, worker process, golden data.  
- **EPIC-1**: CSV adapter + ELT skeleton (Volunteers).  
- **EPIC-2**: Runs dashboard + DQ inbox (required/format) + remediation.  
- **EPIC-3**: Deterministic dedupe + idempotent upsert + external ID map.  
- **EPIC-4**: Salesforce adapter (optional) + incremental.  
- **EPIC-5**: Fuzzy Dedupe + Merge UI + survivorship + undo.  
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

### SQLite Concurrency Tips (development)

- SQLite connections are forced into WAL mode with `synchronous=NORMAL` and a 5s busy timeout so the admin UI can read while importer batches write.
- SQLAlchemy uses `check_same_thread=False`; always run the Celery worker in a separate process from the Flask dev server.
- CSV and Salesforce staging now commit after each batch (~500 rows) instead of holding a single long transaction; expect more frequent, smaller writes.
- If you see `database is locked`, check that only one heavy import runs at a time and consider `sqlite3` commands `wal_checkpoint` / `VACUUM` to clear the WAL file.
- Production should graduate to PostgreSQL, but these tweaks keep local dev usable until that migration happens.

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
- DQ inbox lacks bulk actions (suppress/mark won't fix) — backlog for Sprint 3+
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
- **Retrospective**: See [Sprint 3 Retrospective](./sprint3-retrospective.md) for outcomes and lessons learned.

### IMP-30 — External ID map & idempotent upsert _(8 pts)_
**User story**: As an operator, retries do not create duplicates.  
**Acceptance Criteria**
- `(external_system, external_id)` recorded; `first_seen_at`/`last_seen_at` maintained.  
- Retries update not insert; counters reflect created/updated/skipped.  
- `counts_json.core.volunteers` tracks `rows_created`, `rows_updated`, `rows_skipped_no_change`.  
- DQ/retry flows respect external IDs and avoid duplicate staging promotions.  
**Dependencies**: IMP-2, IMP-12.
**Status**: ✅ Delivered (Nov 2025).
**Outcome Notes**:
- Loader reuses shared `resolve_import_target` helper; idempotent counters populate `counts_json.core.volunteers`.
- Support runbook updated with retry guidance and quarantine messaging for missing external IDs.
- Prometheus counters (`importer_idempotent_rows_created_total`, `..._updated_total`, `..._skipped_total`) live in sandbox dashboards.
**Follow-ups**:
- Add alerting thresholds for `rows_missing_external_id` spikes before GA.
- Continue monitoring `external_id_map` backfill scripts until all legacy rows carry `external_system`.
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
**Status**: ✅ Delivered (Nov 2025) — gated on IMP-30 rollout.
**Outcome Notes**:
- Deterministic email/phone matching reduced manual remediation volume; results surfaced via `rows_deduped_auto` counters and dashboard badges.
- Structured logs capture `dedupe_decision` and `dedupe_match_type` for audit and analytics.
**Follow-ups**:
- Track manual fallback rate (no email/phone) to scope fuzzy dedupe in EPIC-5.
- Coordinate with FE guild on long-term ownership of dedupe-related dashboard components.
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
**Status**: 🟡 Partially delivered — engine live for contact identity; admin UI + alerts carrying into Sprint 4.
**Outcome Notes**:
- `apply_survivorship` helper merged with precedence profiles for contact fields; change-log entries now record per-field winners.
- Logging and metrics (`importer_survivorship_decisions_total`) enabled for sandbox analysis.
**Follow-ups**:
- Ship admin dashboard summary and support documentation highlighting active profile.
- Define alerting/notification strategy when survivorship overrides manual remediation.
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
**Status**: ✅ Delivered (Nov 2025).
**Outcome Notes**:
- Regression suite (`tests/importer/test_idempotency_regression.py`) replays golden datasets (dry-run + live) and asserts stable counters.
- CI publishes `idempotency_summary.json` artifacts to `ci_artifacts/idempotency/` and blocks merges on regressions.
**Follow-ups**:
- Extend coverage for survivorship override scenarios and partial file subsets next sprint.
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

### Sprint 4 Overview
- **Theme**: Introduce a Salesforce adapter that reuses the importer pipeline, keeping the feature completely optional until licensed customers request it.
- **Shared architecture work**: Establish adapter bootstrapping, secure credential management, and shared watermark helpers so future adapters (e.g., NationBuilder) can plug in quickly.
- **Data & schema**: Confirm staging tables and change-log columns already support Salesforce-specific metadata (OwnerId, RecordTypeId, SystemModstamp); plan minimal migrations for watermark bookkeeping.
- **Operational readiness**: Document deployment toggles, credential rotation SOPs, and rollback steps if Salesforce limits or schema changes break ingestion.
- **Risks / assumptions**: Reliance on API quotas, variability in customer-specific Salesforce fields, and the need for robust backoff/retry handling across long-running exports.
- **Clarifications requested**: Finalize which Salesforce edition(s) we target first, how we expose OAuth/username-password flows, and whether customer admins or Polaris support owns connected app provisioning.

### IMP-40 — Adapter loader & optional deps _(3 pts)_
**User story**: As an operator, Salesforce is installable only when needed.  
**Acceptance Criteria**
- `[salesforce]` Python extra declared; pip install without extra keeps dependencies out.  
- Importer warns clearly when adapter enabled but deps/creds missing.  
- Admin toggle hides Salesforce UI affordances when adapter disabled.  
**Dependencies**: IMP-1.
**Status**: ✅ Implemented on dev branch (Nov 2025); staging rollout pending connector QA.

**Implementation Notes (Nov 2025)**
- Added `project.optional-dependencies["importer-salesforce"]` and `requirements-optional.txt` (with hashes) so operators install extras via `pip install ".[importer-salesforce]"` or `pip install -r requirements-optional.txt`.
- Runtime readiness uses `importer.adapters.salesforce.check_salesforce_adapter_readiness()` to validate optional deps, creds, and (optionally) live auth; failures surface actionable messages in logs, CLI, and the admin UI.
- New CLI surface: `flask importer adapters list [--auth-ping]` renders status per adapter (CSV, Salesforce) and can perform a live auth ping when dependencies/creds are present.
- Admin Importer dashboard now contains an "Adapter Availability" card (under Admin → Imports) with status pill, toggle indicator, and setup guide link (configurable via `IMPORTER_SALESFORCE_DOC_URL`).
- `ImportRun.adapter_health_json` stores a snapshot of adapter readiness when a run is queued (CLI or admin), improving post-mortem diagnostics.
- Deployment note: include `requirements-optional.txt` in the optional Docker layer that bakes Salesforce support; omit the file when producing the slim base image.

**Implementation Outline**
- Add adapter registration to `importer/adapters/__init__.py`; guard import behind feature flag + extra check.
- Implement `ensure_salesforce_adapter_ready()` that validates env vars (`SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`) required for username/password+token auth with Simple Salesforce.
- Instantiate the client via `from simple_salesforce import Salesforce, SalesforceAuthenticationFailed`, surfacing clear failure messaging when auth fails.
- Update CLI (`flask importer adapters list`) to indicate availability and dependency status.
- Extend admin settings page to show Salesforce card with enable/disable toggle and doc links.

**Data Model & Storage**
- Added nullable `ImportRun.adapter_health_json` (JSON) to persist readiness metadata alongside run metrics for troubleshooting.

**Metrics & Telemetry**
- Emit `importer_salesforce_adapter_enabled_total` gauge and auth attempt counters with success/failure labels.
- Log adapter readiness checks with structured fields (`adapter="salesforce"`, `status`, `missing_env_vars`).

**Testing Expectations**
- **Unit**: Adapter availability checks, feature flag gating, CLI messages for missing deps.
- **Integration**: Install extra in CI job, verify adapter registers, and disable without extra to assert clean failure.
- **Packaging**: Smoke install on slim Docker image ensuring optional layer works.

**Open Questions / Clarifications**
- ✅ Launch authentication flow uses username/password + security token via Simple Salesforce; evaluate OAuth in future sprints.
- ✅ Connected app provisioning remains a Polaris Support responsibility for v1; long-term plan is a shared hand-off (support bootstraps, customer IT finalises).
- ✅ Adapter health surfaces on the existing Admin → Imports page (Adapter Availability card); revisit a dedicated integrations page when more adapters ship.

### IMP-41 — Salesforce extract → staging _(8 pts)_
**User story**: As an operator, Contacts pull incrementally into staging.  
**Acceptance Criteria**
- `since` watermark respected; raw payload stored; rate-limit backoff.  
- Partial failures logged to run; retries safe.  
- Resume from `SalesforceWatermark` record when run restarts.  
**Dependencies**: IMP-40, IMP-3.
**Status**: ✅ Implemented on dev branch (Nov 2025); staging rollout pending Bulk API smoke tests with sandbox data.

**Implementation Notes (Nov 2025)**
- Added `SalesforceExtractor` (Bulk API 2.0) with incremental SOQL builder (`SystemModstamp` gating, optional `LIMIT`) and CSV parsing backed by hashed optional deps from `requirements-optional.txt`.
- New Celery task `importer.pipeline.ingest_salesforce_contacts` fetches Contacts only (batch size 5k, 5s poll) and streams into staging via `pipeline.salesforce.ingest_salesforce_contacts`, respecting dry runs and capturing max modstamp per batch.
- `importer_watermarks` table tracks `(adapter, object)` cursor state (`last_successful_modstamp`, `last_run_id`, metadata); `ImportRun.metrics_json["salesforce"]` now records batches processed, records received, and watermark timestamp.
- Staging rows persist the full Salesforce payload in `payload_json` plus normalized hints (name/email/phone, object identifiers) for mapping work in IMP-42. Dry runs skip inserts but still populate counts/metrics.

**Data Model & Storage**
- Added `ImporterWatermark` SQLAlchemy model/table. Watermark updates only commit after successful job completion; dry runs leave the cursor unchanged.
- `ImportRun` metrics/counters now updated via shared staging helper (`update_staging_counts`) so CSV and Salesforce runs surface consistent counts.

**Metrics & Telemetry**
- Prometheus: `importer_salesforce_batches_total{status}` counter, `importer_salesforce_batch_duration_seconds` histogram, plus existing adapter-enabled/auth metrics.
- Structured logs per batch (`batch_sequence`, `records`, `locator`, `duration_seconds`) and run summary log on completion.

**Operational Runbook**
- Config knobs exposed via env vars: `IMPORTER_SALESFORCE_OBJECTS` (default `contacts`), `IMPORTER_SALESFORCE_BATCH_SIZE` (default `5000`). Credentials remain env-driven (`SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`, optional domain/client id/secret).
- CLI/worker workflow: run `pip install -r requirements-optional.txt`, enable adapter, queue runs via Celery task, monitor via admin Adapter Availability + run metrics.

**Testing Coverage**
- Unit: SOQL builder edge cases, extractor polling/CSV parsing, watermark math, staging helper logic.
- Integration: pipeline unit tests simulate Bulk batches to validate staging inserts/dry runs, watermark advancement, metrics updates. (Full sandbox/Bulk smoke tests tracked in staging checklist.)

**Open Questions / Clarifications**
- ✅ MVP scope = Contacts only (Campaign Member ingest deferred).
- ✅ Secrets remain env-driven for v1; revisit Vault when multi-tenant support lands.
- ✅ Org does not use Salesforce multi-currency today; raw amount handling deferred to revenue objects in future sprints.

### IMP-42 — Salesforce → canonical mapping v1 _(8 pts)_
**User story**: As a dev, SF fields map to `VolunteerIngest`.  
**Acceptance Criteria**
- Declarative mapping file; unmapped fields surfaced in run summary.  
- Required/format DQ applied; violations created.  
- Mapping supports field-level transforms (e.g., picklist normalization).  
**Dependencies**: IMP-41, IMP-11.
**Status**: ✅ Implemented on dev branch (Nov 2025); dashboard/CLI wired, customer-specific overrides deferred to Sprint 7.

**Implementation Notes (Nov 2025)**
- Introduced YAML source of truth (`config/mappings/salesforce_contact_v1.yaml`) plus loader/validator; YAML checksum + version captured in run metrics.
- Added `SalesforceMappingTransformer` to apply transforms (phone normalization, date parsing) and populate canonical volunteer dicts directly in `StagingVolunteer.normalized_json`.
- Admin → Imports card now surfaces mapping metadata, unmapped-field warnings, and provides a download link for the active YAML. CLI exposes `flask importer mappings show` to inspect the spec.
- Mapping metrics: per-run `metrics_json["salesforce"]` records unmapped fields/errors; Prometheus counter `importer_salesforce_mapping_unmapped_total{field}` tracks hotspots.
- Detailed guidance for extending mappings (new fields, transforms, or Salesforce objects) now lives in `docs/salesforce-mapping-guide.md`, `docs/salesforce-transforms-reference.md`, and `docs/salesforce-mapping-examples.md`.

**Testing Expectations**
- **Unit**: YAML loader validation, transformer behavior, mapping CLI command.
- **Integration**: Salesforce pipeline test ensures mapped payloads land in staging and unmapped counters stay in sync.
- **Documentation**: When making mapping changes, cross-reference the mapping guide to ensure vertical (new fields) and horizontal (new objects) updates follow the documented workflow.

**Open Questions / Clarifications**
- ✅ Mapping curated internally (single Contact spec for v1); customer overrides scheduled for Sprint 7.
- ✅ Diff exposure handled via downloadable YAML + admin messaging (dashboard).

### IMP-43 — Incremental upsert & reconciliation counters _(5 pts)_
**User story**: As an operator, I see created/updated/unchanged counts for the window.  
**Acceptance Criteria**
- Counters visible; `max(source_updated_at)` recorded.  
- Run summary exposes `rows_created`, `rows_updated`, `rows_unchanged`, `rows_deleted`.  
- Salesforce watermark advanced only after successful commit.  
**Dependencies**: IMP-42, IMP-30.
**Status**: ✅ Implemented on dev branch (Nov 2025); loader + counters live, dashboards refreshed on completion.

**Implementation Notes (Nov 2025)**
- Added `SalesforceContactLoader` (two-phase commit) that snapshots staging rows, upserts against `external_id_map` (`entity_type="salesforce_contact"`, placeholder `entity_id=0` until canonical contacts land), handles soft deletes inline, and advances the watermark only after core updates succeed.
- Persist reconciliation counters under `counts_json.core.volunteers.salesforce` (`created/updated/unchanged/deleted`) and store the latest source timestamp in `import_runs.max_source_updated_at` (new column). Prometheus now exposes `importer_salesforce_rows_total{action}` and `importer_salesforce_watermark_seconds`.
- Celery task (`flask importer run-salesforce --run-id <id>`) queues the ingest + loader combo; task logs include per-action counters. Admin card summarizes the last run counters and still links to the mapping YAML.
- Admin Imports page now exposes a dedicated Salesforce trigger panel when the adapter is ready. Operators can queue dry runs, set a test record limit, optionally reset the Salesforce watermark (with confirmation), and poll live status. UI triggers are rate limited (1 per minute per user) and capture adapter readiness snapshots in the associated `ImportRun`.

**Metrics & Telemetry**
- `importer_salesforce_rows_total{action}` counters, `importer_salesforce_watermark_seconds` gauge, plus structured logs (job id, batches, rows per action).
- `ImportRun.metrics_json["salesforce"]["max_source_updated_at"]` records freshness for dashboard polling (refreshes within ~1 minute post-run).

**Testing Expectations**
- **Unit**: Loader branching for create/update/unchanged/delete, watermark advancement, counter persistence.
- **Integration**: Replay create→update→delete sequences to ensure counters stay accurate and watermark advances exactly once; dry-run skips loader but preserves staging metrics.
- **Regression**: Combined with idempotency + ingest suites to guard against duplicate records or counter regressions.

**Open Questions / Clarifications**
- ✅ Two-phase commit implemented: watermark advances only after successful core database commit.
- ✅ Counters surface within ~1 minute post-run via dashboard refresh.
- ✅ Salesforce deletes processed in same run for fresher counts; no nightly batching required.
---

## Sprint 5 — Fuzzy Dedupe + Merge UI
**Epic**: EPIC-5  
**Status**: 🗓️ Planned (post-Sprint 4)
**Goal**: Human-in-the-loop identity resolution; auto-merge & undo.

### Sprint 5 Overview
- Complete the identity-resolution loop by layering fuzzy scoring on top of deterministic dedupe delivered in Sprint 3.
- Ship an operator-facing merge experience that mirrors survivorship policy decisions captured in Sprint 3.
- Automate "obvious" merges while keeping undo safety nets and detailed audit trails.
- Extend dashboards/metrics so stewards can see dedupe throughput, manual workload, and automation coverage.

### Scope Highlights
- Expand dedupe engine with feature extraction, scoring, and configurable thresholds.
- Build Merge UI flows (list, compare, merge, defer) with survivorship controls.
- Implement auto-merge pipelines with undo mechanics and notifications.
- Update Runs dashboard with dedupe metrics and drill-down links into review queues.

### Pre-Sprint Dependencies & Prep
- Golden dataset: add fuzzy-match scenarios (name variants, shared households, address proximity).
- Update survivorship documentation (`apply_survivorship` profile) with UI copy and help text.
- Align product/ops on threshold defaults and manual review workflows.
- Ensure audit log schema can record merge/undo events (verify fields on `merge_log`, `change_log`).

### Testing & QA Strategy
- Extend regression suite with fuzzy-dedupe cases (scores around thresholds, conflicting identities).
- UI tests for merge flows (side-by-side diffing, field-level selections, error handling).
- Property-based tests for feature scoring to guard against regressions in normalization.
- Performance testing on candidate generation for large tenant datasets (~100k volunteers).

### Metrics & Observability
- Prometheus counters: `importer_dedupe_candidates_total`, `importer_dedupe_auto_total`, `importer_dedupe_manual_total`.
- Histogram for candidate scoring latency; gauge for review queue size.
- Structured logs capturing `dedupe_score`, `match_type`, `decision`, `actor` (for manual merges).
- Dashboard widgets summarizing auto vs manual merges, undo rate, and median resolution time.

### Risks & Mitigations
- **False positives**: keep aggressive thresholds behind feature flag; require manual confirmation for borderline scores.
- **Undo complexity**: implement atomic merge transactions with reversible snapshots stored in `merge_log`.
- **Performance**: batch candidate generation and reuse deterministic caches (email/phone) to limit fuzzy comparisons.
- **Operator adoption**: deliver training materials and in-product help text derived from survivorship docs.

### Support & Follow-up Work
- Update admin help center with merge workflow runbook.
- Coordinate with analytics to add dedupe KPIs to Ops dashboards.
- Build post-sprint migration script to backfill `dedupe_suggestions` for existing staging rows (if needed).
- Ensure the new Salesforce mapping docs (Sprint 4 deliverable) call out dedupe feature dependencies where relevant.

### IMP-50 — Candidate generation & scoring _(8 pts)_
**User story**: As a steward, likely duplicates appear with scores & features.  
**Acceptance Criteria**
- Blocking keys (email/phone/name+zip); features (name, DOB, address, employer/school).
- Scores stored in `dedupe_suggestions` with features JSON; thresholds configurable.
**Dependencies**: IMP-31.
**Implementation Notes (planned)**
- Introduce feature extraction service composing deterministic keys (email, phone) with fuzzy features (Jaro–Winkler name, DOB proximity, address token overlap, employer/school similarity).
- Persist features JSON on `dedupe_suggestions` to power UI explainability and offline analysis.
- Provide configuration for feature weights/thresholds via settings module (hooked to Sprint 7 Config UI).
- Batch candidate generation in Celery tasks to avoid long blocking transactions; reuse staging `normalized_json` when available.

**Testing Expectations**
- Unit: feature calculators, scoring aggregation, threshold evaluation.
- Integration: ingest golden dataset with known duplicates; verify candidate list accuracy and score bands.
- Performance: benchmark candidate generation on 50k+ volunteers, ensuring <5 min runtime with caching.
- Regression: confirm deterministic dedupe paths unchanged; fuzzy pipeline should fall back gracefully when data sparse.

### IMP-51 — Merge UI _(13 pts)_
**User story**: As an admin, I can compare, choose field winners, and merge safely.  
**Acceptance Criteria**
- Side-by-side compare; field highlights; survivorship controls.
- On merge: `merge_log`, `external_id_map` unify, `change_log` diffs recorded.
- Actions: accept, reject, defer.
**Dependencies**: IMP-50, IMP-32.
**Implementation Notes (planned)**
- React (or Flask template) component renders side-by-side views with highlighting off features JSON from IMP-50.
- Integrate survivorship engine (`apply_survivorship`) allowing per-field override; record decisions in `change_log`.
- Provide bulk actions (accept/reject) and comment log for steward notes.
- Enforce RBAC: only Admin/Data Steward roles may merge; viewer sees read-only comparison.
- Expose API endpoints for fetching candidate details, merging, deferring, and undo triggers.

**Testing Expectations**
- UI: Cypress (or equivalent) flows for review, field toggle, merge execution, undo.
- Backend: Unit tests for merge transaction, undo rollback, audit logging.
- Accessibility: keyboard navigation, screen reader announcements for diffs.
- Security: verify RBAC enforcement and CSRF protection on merge actions.

### IMP-52 — Auto-merge + undo merge _(8 pts)_
**User story**: As an operator, obvious dupes auto-merge; I can undo.  
**Acceptance Criteria**
- Auto-merge for score ≥ threshold; undo restores state fully.
**Dependencies**: IMP-51.
**Implementation Notes (planned)**
- Define high-confidence threshold (≥0.95) aligned with IMP-50 scoring; run auto-merge as background job with rate limiting.
- Capture full pre/post snapshots in `merge_log` for undo; include survivorship outcomes and provenance.
- Provide UI/CLI `undo-merge` command with safety confirmations and audit logging.
- Implement notification hooks (email/Slack) for auto-merge batches with summary stats (successful, skipped, errors).

**Testing Expectations**
- Unit: auto-merge decision logic, undo rollback idempotency.
- Integration: simulate batch of high-confidence duplicates; verify counts, audit entries, and undo path.
- Chaos: inject failures mid-merge to ensure transaction rollback leaves data consistent.
- Monitoring: confirm metrics for auto-merge/undo publish as expected.

### IMP-53 — Dedupe metrics on runs _(3 pts)_
**User story**: As an admin, I see auto-merged & needs-review counts per run.  
**Acceptance Criteria**
- New run columns and links to review queue.
**Dependencies**: IMP-50.
**Implementation Notes (planned)**
- Extend Runs dashboard API to include dedupe counters (`rows_dedupe_auto`, `rows_dedupe_manual_review`).
- Surface drill-down links into Merge UI filtered by run/threshold band.
- Add export option for dedupe summaries (CSV/JSON) to feed Ops reporting.
- Update Prometheus metrics with run labels for dedupe outcomes.

**Testing Expectations**
- Unit: serialization of new counters, permissions on dashboard endpoints.
- Integration: run importer with synthetic duplicates; ensure counts populate and UI renders badges.
- Observability: verify alerts trigger when manual review queue backlog exceeds threshold.

---

## Sprint 6 — Reconciliation, Anomalies, Alerts
**Epic**: EPIC-6  
**Status**: 🗓️ Planned (post-Sprint 5)
**Goal**: Detect leaks/staleness/spikes; trend views; operator alerts.

### Sprint 6 Overview
- Establish guardrails that surface stale or missing data quickly, reducing mean time to detection for source anomalies.
- Give operators proactive alerts so they can intervene before downstream teams feel data quality pain.
- Provide trend visualizations that highlight regressions in ingest volume, duplicates, or DQ violations over time.

### Scope Highlights
- Reconciliation service comparing source payloads vs core loads with freshness tracking.
- Anomaly detectors leveraging historical baselines for reject/null/drift metrics.
- Multi-channel alerting (email/Slack/webhook) with tunable thresholds and run deep-links.
- Trend dashboards for PM/ops stakeholders with export support.

### Pre-Sprint Dependencies & Prep
- Finalize metric schema (`counts_json`, `metrics_json`) to accommodate reconciliation stats.
- Partner with analytics to define baselines used for anomaly detection (14-day rolling averages, etc.).
- Ensure alert channels and secrets management patterns are in place (Vault/ENV) with runbooks.
- Capture operator requirements for alert escalation policies and service levels.

### Testing & QA Strategy
- Unit tests for reconciliation calculators, anomaly scoring functions, and alert fan-out logic.
- Integration tests simulating stale source data, spike in rejects, duplicate surge.
- Load tests on reconciliation queries to validate performance at scale (large `import_runs` history).
- End-to-end dry runs verifying alerts reach configured channels with correct payload.

### Metrics & Observability
- Counters/gauges: `importer_reconciliation_mismatch_total`, `importer_freshness_lag_seconds`, `importer_anomaly_flags_total{type}`.
- Alert delivery metrics (success/failure) for each channel.
- Dashboard tiles summarizing freshness lag, reject rate trend, anomaly flag distribution.
- Structured logs for reconciliation runs including diff summaries and anomaly explanations.

### Risks & Mitigations
- **False alarms**: Start in "warn-only" mode, use rolling baselines, and expose config UI to tune thresholds.
- **Alert fatigue**: Provide deduping window and severity levels; integrate with Ops on escalation rules.
- **Performance**: Pre-compute aggregates via scheduled jobs to avoid real-time heavy queries.
- **Secrets management**: Use consistent secret storage for webhook credentials; add synthetic monitoring.

### Support & Follow-up Work
- Draft incident response playbook for alert types (freshness breach, reject spike, anomaly flag).
- Train Ops on interpreting reconciliation dashboards; include example screenshots.
- Coordinate with reliability team for pager integration if needed.
- Connect Sprint 5 dedupe metrics so anomalies include dedupe-related drift warnings when relevant.

### IMP-60 — Reconciliation & freshness _(8 pts)_
**User story**: As an operator, I know if data is stale or missing.  
**Acceptance Criteria**
- Freshness (now - max(source_updated_at)); thresholds; run labels.
- Source vs core counts; hash parity spot checks; metrics saved to `counts_json`.
**Dependencies**: IMP-43.
**Implementation Notes (planned)**
- Compute source vs core counts per entity in near-real time, storing results in `counts_json.reconciliation` with per-entity breakdowns.
- Track `max(source_updated_at)` and `max(core_updated_at)` to calculate freshness lag; annotate runs with badges when lag exceeds thresholds.
- Provide reconciliation drill-down UI with diff snapshots (counts, hashes) and quick links to impacted runs/entities.
- Store hash parity checksums for sampling canonical payloads to detect silent drift.

**Testing Expectations**
- Unit: reconciliation calculators, freshness lag formatting, hash comparison utilities.
- Integration: simulate mismatched counts and stale data; ensure UI/API highlights issues and metrics update.
- Regression: confirm reconciliation logic respects dry-run mode and doesn't advance watermarks.
- Performance: verify queries remain performant with 180k+ staging rows and long lookback windows.

### IMP-61 — Anomaly detectors _(8 pts)_
**User story**: As a PM, I see drift in rejects/dupes/null rates.  
**Acceptance Criteria**
- Delta guard (3σ), null drift (2× baseline), rule offenders ranked.
- Flags shown on runs and Source Health page.
**Dependencies**: IMP-60.
**Implementation Notes (planned)**
- Implement statistical guards: z-score/rolling median to flag spikes in rejects, duplicates, null rates, or dedupe automation gaps.
- Persist anomaly metadata in `import_runs.anomaly_flags` with type, severity, baseline window, and supporting metrics.
- Provide Source Health page summarizing recent anomalies with recommended actions (link to docs/runbooks).
- Allow operators to acknowledge/resolve anomalies, feeding into Ops reporting.

**Testing Expectations**
- Unit: anomaly scoring math, normalization of baselines, severity assignment.
- Integration: synthetic data generating spikes/declines; confirm anomalies surface and interplay with reconciliation badges.
- Alert integration: ensure anomaly flags propagate to IMP-62 alert system with dedupe suppression windows.
- Observability: ensure metrics for anomalies align with dashboards (counts per type, resolutions).

### IMP-62 — Alerts (email/Slack/webhook) _(5 pts)_
**User story**: As an operator, I'm notified on failures or critical anomalies.  
**Acceptance Criteria**
- Channels configurable; links point to run/queue; on/off per source.
**Dependencies**: IMP-61.
**Implementation Notes (planned)**
- Support multiple alert channels via pluggable transport interface (email SMTP, Slack webhook, generic webhook).
- Configurable per-source thresholds and notification preferences (warn vs enforce) stored in config service (Sprint 7 integration).
- Include deep links to run detail, DQ inbox, merge queue depending on alert type.
- Log delivery outcomes, retries, and escalate on repeated failures.

**Testing Expectations**
- Unit: channel fan-out, payload templating, retry/backoff logic.
- Integration: send alerts to sandbox endpoints verifying formatting and links.
- Security: validate webhook payload signing/secret usage.
- Monitoring: alert delivery metrics and synthetic heartbeat alerts to detect silent failures.

### IMP-63 — Trend views _(5 pts)_
**User story**: As a PM, I can view 30-day trends for ingests/rejects/dupes/freshness.  
**Acceptance Criteria**
- Charts render; filterable dates; export CSV/PNG.
**Dependencies**: IMP-60.
**Implementation Notes (planned)**
- Build dashboard module (charts/tables) visualizing rolling metrics: ingests, rejects, dedupe actions, freshness, anomaly counts.
- Implement backend endpoints aggregating data with pagination and export to CSV/PNG.
- Provide filters by source, entity, severity, date range; support compare-to-baseline overlays.
- Add "share report" feature generating snapshot links for stakeholders.

**Testing Expectations**
- UI: chart rendering, filter combinations, export/download functionality.
- Backend: aggregation accuracy, pagination correctness, performance under long ranges (90 days).
- Accessibility: ensure charts have alternative text or table representations.
- Observability: confirm dashboards update within expected latency (<5 minutes post-run).

---

## Sprint 7 — Mapping Versioning + Config UI + Backfills
**Epic**: EPIC-7  
**Status**: 🗓️ Planned (post-Sprint 6)
**Goal**: Version mappings; in-app config; safe backfills.

### Sprint 7 Overview
- Introduce governance around mapping changes so teams can iterate safely without breaking historical runs.
- Deliver in-app configuration for importer thresholds, schedules, and rule modes to reduce env-variable churn.
- Provide first-class backfill tooling supporting safe reprocessing and historical imports.

### Scope Highlights
- Versioned mapping storage with run-level traceability and diff tooling.
- Config UI enabling threshold tweaks, rule severity changes, schedule management, and adapter toggles.
- Backfill UX/CLI supporting `--since` windows, pausable runs, and dry-run validation.
- Mapping diff/suggestion system surfacing unmapped Salesforce fields post-ingest.

### Pre-Sprint Dependencies & Prep
- Finalize mapping documentation (delivered Sprint 4) and determine versioning metadata requirements (`mapping_version`, checksum, changelog).
- Align with Security/Compliance on configuration audit logging expectations.
- Gather operator requirements for backfill workflows (pause/resume, progress visibility, concurrency constraints).
- Ensure database migrations in place for new config tables, mapping history, and backfill metadata.

### Testing & QA Strategy
- Unit tests for mapping version loader, config service, and CLI backfill scheduler.
- Integration tests performing mapping version upgrades and rollbacks; verify run traceability.
- UI/UX tests for Config UI (form validation, audit logging visibility) and backfill screens.
- Dry-run simulations for backfill to confirm no unintended core writes.

### Metrics & Observability
- Counters: `importer_mapping_version_total`, `importer_backfill_runs_total`, `importer_config_change_total`.
- Audit log entries recording config changes (who/when/what) surfaced in admin UI.
- Monitoring for backfill progress (rows processed, ETA) and error rates.
- Structured logs linking mapping version to run IDs for downstream analytics.

### Risks & Mitigations
- **Mapping drift**: enforce review workflow with automated diff summaries and docs references.
- **Config misuse**: implement RBAC gating and validation rules; add "preview impact" tooltips.
- **Backfill overload**: include concurrency caps, throttle settings, and Ops notifications before large runs.
- **Version rollback complexity**: store prior versions and provide CLI/UI rollback actions with warnings.

### Support & Follow-up Work
- Update mapping guide with versioning instructions and Config UI documentation.
- Produce runbook for executing large backfills (pre-checks, monitoring, rollback).
- Coordinate with Ops to schedule maintenance windows for heavy backfills.
- Ensure anomaly detectors (Sprint 6) respect backfill context to avoid false alarms.

### IMP-70 — Versioned mappings _(8 pts)_
**User story**: As a dev, I can evolve mappings without breaking history.  
**Acceptance Criteria**
- `mapping_version` stored on runs; UI shows current/prior; unmapped field warnings.
**Dependencies**: IMP-42.
**Implementation Notes (planned)**
+- Store mapping specs with version metadata (`version`, `checksum`, `released_at`, `notes`) in dedicated table and reference from runs.
+- CLI/CI tooling to validate mapping changes (lint, diff, test) before promotion.
+- Admin UI showing current/previous mapping versions with diff viewer and download links.
+- Provide migration path for existing installs (auto-register v1 mapping on upgrade).
+
+**Testing Expectations**
+- Unit: mapping persistence, version retrieval, diff generation utilities.
+- Integration: run imports across version upgrades ensuring run records capture correct mapping reference.
+- Regression: ensure `IMPORTER_SALESFORCE_MAPPING_PATH` override still works for custom deployments.
+- Security: verify only authorized roles can promote or rollback mappings.

### IMP-71 — Config UI & thresholds _(8 pts)_
**User story**: As an admin, I can tune thresholds, rules, and schedules.  
**Acceptance Criteria**
- Edit dedupe thresholds, anomaly thresholds, cron schedule, rule modes (warn/enforce); audit config changes.
**Dependencies**: IMP-60, IMP-61.
**Implementation Notes (planned)**
+- Build configuration service storing importer settings (dedupe thresholds, anomaly thresholds, schedules, rule modes) with audit trail.
+- UI forms with live validation, preview of impacted metrics, and "draft vs applied" states.
+- Integrate with Celery beat/cron to update schedules dynamically without redeploy.
+- Record config changes in `change_log`/audit log for compliance reporting.
+
+**Testing Expectations**
+- Unit: config schema validation, RBAC enforcement, audit logging.
+- Integration: modify thresholds and confirm dedupe/anomaly pipelines pick up changes immediately.
+- UI: accessibility, error handling, diff preview for new vs current values.
+- Security: protect against CSRF/injection; ensure secrets (if any) masked.

### IMP-72 — Backfill UX & CLI _(5 pts)_
**User story**: As an operator, I can backfill since a date, with dry-run.  
**Acceptance Criteria**
- `--since` param; run labeled "backfill"; concurrency caps; pausable.
**Dependencies**: IMP-43.
**Implementation Notes (planned)**
+- Extend CLI (`flask importer backfill --since <date>`) and Admin UI wizard guiding operators through dry-run, scope selection, concurrency limits.
+- Track backfill runs with labels (backfill, dry-run) and progress state (queued, running, paused, completed).
+- Provide pause/resume controls and checkpointing so long backfills can be safely interrupted.
+- Ensure backfills integrate with anomaly detectors (muting or adjusting thresholds) to avoid noise.
+
+**Testing Expectations**
+- Unit: CLI argument parsing, checkpoint persistence, resume logic.
+- Integration: run backfill scenarios (dry-run, full run) and validate no duplicate inserts thanks to idempotency.
+- Operational: stress test concurrency controls and pause/resume under load.
+- UX: confirm progress indicators and notifications update in real time.

### IMP-73 — Mapping diffs & suggestions _(5 pts)_
**User story**: As a dev, I get suggestions when new SF fields appear.  
**Acceptance Criteria**
- Run summary lists unmapped fields with samples; exportable.
**Dependencies**: IMP-70.
**Implementation Notes (planned)**
+- After each run, analyze unmapped Salesforce fields and store samples; surface them in mapping UI with suggestions.
+- Provide "generate stub mapping entry" actions to accelerate adoption of new fields.
+- Export unmapped field report (CSV/JSON) for stakeholder review.
+- Integrate with docs to prompt updates to mapping guide when new fields accepted.
+
+**Testing Expectations**
+- Unit: unmapped field detection, suggestion generation, export formatting.
+- Integration: simulate schema drift (new fields) and verify UI/API surfaces suggestions.
+- Regression: ensure existing mapped fields not flagged due to case differences or aliases.
+- Analytics: confirm metrics count unmapped suggestions for prioritization dashboards.

---

## Sprint 8 — Events & Signups/Attendance
**Epic**: EPIC-8  
**Status**: 🗓️ Planned (post-Sprint 7)
**Goal**: Bring pipeline to Events + Signups/Attendance with cross-entity DQ.

### Sprint 8 Overview
- Extend importer architecture beyond volunteers to cover Events, Shifts, and Signups/Attendance.
- Enforce cross-entity data quality, ensuring references resolve and attendance metrics stay accurate.
- Update dashboards and reconciliation logic to span multiple entity types.

### Scope Highlights
- New staging/clean schemas for events and signups, with canonical contracts defined.
- Reference validation leveraging `external_id_map` and core foreign keys.
- Idempotent upsert flows for events/attendance, including concurrency-safe hour calculations.
- Cross-entity dashboards and health views aggregating pipeline performance.

### Pre-Sprint Dependencies & Prep
- Define canonical Event/Signup contracts (fields, required relationships, statuses) and document them.
- Expand golden dataset with multi-entity scenarios (events with multiple shifts, signups referencing volunteers/events, invalid references).
- Review Salesforce mapping requirements (Contacts → Events) and determine adapter changes (e.g., Campaigns, CampaignMembers).
- Ensure backfill tooling (Sprint 7) supports multi-entity flows.

### Testing & QA Strategy
- Unit tests for new staging models, reference resolution helpers, and attendance calculations.
- Integration tests covering ingest → DQ → upsert for events and signups (CSV + Salesforce adapters).
- Cross-entity DQ tests ensuring invalid references quarantined with actionable errors.
- End-to-end tests verifying dashboards display combined metrics and filters behave correctly.

### Metrics & Observability
- Counters: `importer_events_rows_total{action}`, `importer_signups_rows_total{action}`, reference failure metrics.
- Dashboards showing event ingest throughput, signup attendance ratios, and reference violation trends.
- Logs capturing event/attendance anomalies (hours mismatch, double-booked volunteers).
- Reconciliation updates (Sprint 6) to cover new entity types.

### Risks & Mitigations
- **Schema complexity**: isolate per-entity staging tables and maintain contract docs to prevent confusion.
- **Reference integrity**: enforce FK resolution before load; provide remediation flows for missing volunteers/events.
- **Performance**: apply batching strategies to signups (high volume) and track memory usage.
- **User adoption**: refresh training materials to cover new entity workflows and dashboards.

### Support & Follow-up Work
- Update contracts documentation (overview + mapping guide) to include events/signups models.
- Provide onboarding materials for event coordinators using new dashboards.
- Align analytics on KPI definitions (attendance rate, no-show rate) and ensure metrics pipeline consistent.
- Prepare migration plan for existing event data (if any) to new importer pathways.

### IMP-80 — Staging + contracts for Events/Signups _(8 pts)_
**User story**: As an operator, I can ingest events and signups via CSV/SF.  
**Acceptance Criteria**
- `staging_events`, `staging_signups` exist; contracts validate times & required fields.
**Dependencies**: IMP-2, IMP-41.
**Implementation Notes (planned)**
+- Create `staging_events`, `staging_signups` tables mirroring volunteer staging patterns (status, payload, normalized JSON, checksum).
+- Define canonical contracts for events (title, start/end, location) and signups (volunteer/event references, attendance, hours).
+- Update CSV adapter and Salesforce adapter to emit canonical payloads; include mapping YAMLs for new objects.
+- Document new contracts in `docs/data-integration-platform-overview.md` and mapping guides.
+
+**Testing Expectations**
+- Unit: schema migrations, contract validators, adapter payload normalization.
+- Integration: import golden dataset for events & signups ensuring staging rows created and normalized.
+- Regression: verify volunteer pipeline unaffected by new staging tables.
+- Docs: confirm contract documentation updated with field lists and examples.

### IMP-81 — Reference DQ & FK checks _(8 pts)_
**User story**: As a steward, cross-entity references are validated.  
**Acceptance Criteria**
- FKs resolved via `external_id_map`/core keys; violations REF-401 with hints.
**Dependencies**: IMP-80.
**Implementation Notes (planned)**
+- Implement reference validators ensuring `signups` link to existing volunteers/events via `external_id_map` or core IDs.
+- Surfacing violations with codes (e.g., `REF_EVENT_MISSING`, `REF_VOLUNTEER_MISSING`) and remediation hints.
+- Provide remediation workflow to create missing references or adjust mapping before requeue.
+- Log reference resolution stats for monitoring (success vs fallback vs failure).
+
+**Testing Expectations**
+- Unit: reference lookup helpers, violation writers, remediation endpoints.
+- Integration: simulate missing volunteers/events and ensure quarantine flow works end-to-end.
+- Regression: confirm reference DQ does not block valid imports or introduce race conditions.
+- Observability: verify metrics/alerts fire when reference violation rate spikes.

### IMP-82 — Upsert for events & attendance _(8 pts)_
**User story**: As an operator, events/signups upsert idempotently.  
**Acceptance Criteria**
- `(external_system, external_id)` maintained; hours & attendance flags correct.
**Dependencies**: IMP-81, IMP-30.
**Implementation Notes (planned)**
+- Reuse idempotent upsert helpers with `(external_system, external_id)` keys for events and signups.
+- Handle attendance updates: update hours, status, and handle reinstatements/cancellations gracefully.
+- Capture change logs, survivorship decisions (e.g., manual overrides vs import updates) for attendance records.
+- Integrate with dedupe/external ID map to avoid duplicate volunteer assignments.
+
+**Testing Expectations**
+- Unit: upsert branching (create/update/unchanged) for events and signups.
+- Integration: re-import same data to confirm idempotency; test updates to attendance/hours.
+- Performance: evaluate batch processing for high-volume attendance data (thousands per run).
+- Monitoring: ensure counts appear in reconciliation/trend dashboards.

### IMP-83 — Cross-entity dashboards _(5 pts)_
**User story**: As a PM, I can view pipeline health across entities.  
**Acceptance Criteria**
- Filters by entity; combined metrics; links to entity-specific queues.
**Dependencies**: IMP-82.
**Implementation Notes (planned)**
+- Extend Runs dashboard and Source Health views with entity filters/tabs summarizing volunteers, events, signups.
+- Provide combined metrics (e.g., volunteer attendance rate, event coverage) with drill-downs to relevant queues.
+- Support exports for ops reporting and embed charts into stakeholder dashboards.
+- Align with Sprint 6 trend view components for consistent look and feel.
+
+**Testing Expectations**
+- UI: verify filters, tabs, and combined charts render across devices.
+- Backend: ensure aggregation endpoints support multi-entity queries efficiently.
+- Accessibility: confirm tables/charts accessible and properly labeled.
+- Ops validation: gather feedback from PM/Ops on dashboard usefulness before GA.

---

## Sprint 9 — Security, Audit, Packaging
**Epic**: EPIC-9  
**Status**: 🗓️ Planned (post-Sprint 8)
**Goal**: Harden for PII; clear roles; audit trails; packaging & OSS readiness.

### Sprint 9 Overview
- Enforce role-based access and sensitive-field protections to meet privacy and compliance obligations.
- Close audit gaps by ensuring every admin/steward action is captured and exportable.
- Implement data retention and hygiene policies, including safe export handling.
- Package importer features for distribution (optional dependencies, quickstart docs) to support OSS/community adoption.

### Scope Highlights
- RBAC enforcement across importer UI/API with sensitive-field masking.
- Comprehensive audit logging pipeline with export tooling.
- Retention jobs and CSV injection protections for quarantines/exports.
- Packaging improvements: optional dependency groups, installer docs, samples.

### Pre-Sprint Dependencies & Prep
- Align with legal/compliance on data retention windows, masking requirements, and audit export formats.
- Review existing audit tables/logs for gaps identified in Sprints 1–8 (merge undo, config changes, backfills).
- Coordinate with DevRel/Docs on packaging quickstarts and OSS positioning.
- Ensure security review of RBAC design, including threat modeling.

### Testing & QA Strategy
- Unit tests for RBAC policy enforcement, audit log writers, retention jobs.
- Security tests (manual/automated) for privilege escalation, sensitive data exposure, export sanitization.
- Integration tests for packaging flow (pip install extras, optional adapter enablement) and smoke tests for new install path.
- Compliance validation: generate sample audit exports and retention reports for review.

### Metrics & Observability
- Counters: `importer_audit_events_total{action}`, `importer_retention_jobs_total`, `importer_sensitive_field_access_total`.
- Logs capturing RBAC denials and retention job outcomes.
- Alerting on retention job failures or audit export errors.
- OSS download metrics or telemetry (if applicable) to monitor adoption.

### Risks & Mitigations
- **RBAC regressions**: add automated policy tests and maintain matrix in docs.
- **Audit gaps**: maintain checklist of importer actions; require sign-off before release.
- **Retention job incidents**: run jobs in dry-run mode first; include safety checks/time limits.
- **Packaging drift**: add CI job to install extras and run smoke tests; document support boundaries.

### Support & Follow-up Work
- Produce security runbooks (incident response, breach notification contacts, access reviews).
- Train support staff on RBAC roles and sensitive-field escalation paths.
- Publish packaging quickstart (README, screenshots, sample data) and coordinate with marketing.
- Plan ongoing compliance reviews (annual) and map to importer features.

### IMP-90 — RBAC & sensitive-field gating _(8 pts)_
**User story**: As an admin, roles control visibility and actions (DOB, merges).  
**Acceptance Criteria**
- Roles: Admin, Data Steward, Viewer; masks for sensitive fields; merge/undo require Admin.
**Dependencies**: IMP-51.
**Implementation Notes (planned)**
+- Define role matrix (Admin, Data Steward, Viewer) with granular permissions (view sensitive fields, execute merges, change config).
+- Implement policy enforcement at API/service layers; mask sensitive attributes in responses for non-privileged users.
+- Add security logging for access to sensitive data and privileged actions.
+- Update UI to respect masking (e.g., reveal-on-demand with audit log entry).
+
+**Testing Expectations**
+- Unit: policy checks, masking helpers, RBAC decorators.
+- Integration: role-based scenarios ensuring unauthorized actions blocked and logged.
+- Security: penetration tests for privilege escalation and data leakage.
+- UX: confirm role-based UI adjustments (disabled buttons, tooltips) behave correctly.
 
 ### IMP-91 — Audit completeness _(5 pts)_
 **User story**: As compliance, every admin action is logged.  
@@
-**Dependencies**: IMP-22, IMP-51, IMP-71.
+**Dependencies**: IMP-22, IMP-51, IMP-71.
+**Implementation Notes (planned)**
+- Expand audit logger to cover merges/undo, remediation edits, config changes, backfill actions, alert acknowledgements.
+- Store structured audit events with actor, action, entity, before/after diffs, context metadata.
+- Provide export APIs (CSV/JSON) with filters (date, user, action) and integrity checks (hash/signature optional).
+- Integrate with retention/archival workflows (e.g., S3 storage) per compliance timelines.
+
+**Testing Expectations**
+- Unit: audit event creation, serialization, export formatting.
+- Integration: run representative workflows ensuring audit entries produced and retrievable.
+- Compliance: validate sample exports with governance stakeholders.
+- Performance: ensure audit writes don't impact request latency; consider async batching if needed.
 
 ### IMP-92 — Retention & PII hygiene _(5 pts)_
 **User story**: As a steward, staging/quarantine have retention (e.g., 90 days) and safe exports.  
@@
-**Dependencies**: IMP-21.
+**Dependencies**: IMP-21.
+**Implementation Notes (planned)**
+- Implement retention jobs (scheduled) to purge or anonymize staging/quarantine data past configured window.
+- Provide dry-run mode for retention jobs with reporting before destructive actions.
+- Harden CSV exports against injection (escape special characters, provide sanitized preview) and add encrypted export option if needed.
+- Update documentation/runbooks with retention schedules, manual override process, and compliance sign-offs.
+
+**Testing Expectations**
+- Unit: retention eligibility logic, anonymization helpers, export sanitization functions.
+- Integration: execute retention job in sandbox verifying records purged/anonymized correctly, backups taken when required.
+- Security: ensure exported files sanitized and access-controlled.
+- Monitoring: track retention job metrics and alerts on failures.
 
 ### IMP-93 — Packaging & adapter extras _(5 pts)_
 **User story**: As a dev, I can install with or without Salesforce.  
@@
-**Dependencies**: IMP-40.
+**Dependencies**: IMP-40.
+**Implementation Notes (planned)**
+- Maintain optional dependency groups (`[importer]`, `[salesforce]`, potential future `[events]`) with hashed lockfiles.
+- Publish installation guides (pip, Docker, Heroku) with sample configs and screenshots.
+- Add smoke test suite executed in CI for each extras bundle to ensure dependencies resolve and basic commands run.
+- Provide OSS packaging artifacts (README badges, contribution guide, code owners) and ensure security posture documented.
+
+**Testing Expectations**
+- CI: install each extras group and execute minimal smoke tests (CLI run, mapping show, worker ping).
+- Documentation: verify quickstart steps accurate via fresh environment walkthrough.
+- Packaging: ensure optional adapters stay optional—core app runs without Salesforce deps.
+- Compliance: confirm license notices and third-party dependency tracking up to date.

---
