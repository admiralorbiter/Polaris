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

**Definition of Done (DoD)**  
- Feature behind flag (if applicable) • unit/functional tests • docs updated • counters/metrics visible in Runs • security reviewed • rollback strategy noted.

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

### IMP-4 — DoR/DoD checklists & Golden Dataset scaffold _(3 pts)_
**User story**: As QA/PM, I want shared criteria and seed test data.  
**Acceptance Criteria**
- DoR/DoD documents added.  
- Golden dataset v0 spec created (CSV with edge cases).  
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

### IMP-11 — Minimal DQ: required & format _(5 pts)_
**User story**: As a data steward, invalid rows are quarantined with clear reasons.  
**Acceptance Criteria**
- Rules: must have `{email || phone}`; email format; phone E.164.  
- Violations logged with rule codes & details; good rows pass to next step.  
**Dependencies**: IMP-10.  

### IMP-12 — Upsert (create-only) into core volunteers _(8 pts)_
**User story**: As an operator, clean new rows load into core; duplicates (by email) are skipped for now.  
**Acceptance Criteria**
- Inserts succeed; exact-email duplicates skipped; counters recorded in `counts_json`.  
- Batch transactions; no deadlocks.  
**Dependencies**: IMP-11.  

### IMP-13 — CLI & admin action: start a run _(3 pts)_
**User story**: As an admin, I can start an import via CLI and UI.  
**Acceptance Criteria**
- `flask importer run --source csv --file <path>` returns `run_id`.  
- UI upload starts a run; run status visible.  
**Dependencies**: IMP-3.

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

### IMP-21 — DQ inbox (basic) with export _(8 pts)_
**User story**: As a steward, I can filter violations and export them.  
**Acceptance Criteria**
- Filter by rule/severity/run; row detail shows raw & normalized views.  
- Export CSV of violations.  
**Dependencies**: IMP-11.

### IMP-22 — Remediate: edit & requeue _(8 pts)_
**User story**: As a steward, I can fix a quarantined row and requeue it.  
**Acceptance Criteria**
- Edit form validates; on save, DQ re-runs; if clean, row proceeds to upsert.  
- Violation status moves to `fixed`; audit recorded.  
**Dependencies**: IMP-21, IMP-12.

### IMP-23 — Dry-run mode _(3 pts)_
**User story**: As an operator, I can simulate an import without writes.  
**Acceptance Criteria**
- `--dry-run`/UI toggle executes pipeline but skips core writes; run clearly labeled.  
**Dependencies**: IMP-12, IMP-20.

---

## Sprint 3 — Idempotency + Deterministic Dedupe
**Epic**: EPIC-3  
**Goal**: True idempotency via `external_id_map`; deterministic matching (email/phone); survivorship v1.

### IMP-30 — External ID map & idempotent upsert _(8 pts)_
**User story**: As an operator, retries do not create duplicates.  
**Acceptance Criteria**
- `(external_system, external_id)` recorded; `first_seen_at`/`last_seen_at` maintained.  
- Retries update not insert; counters reflect created/updated/skipped.  
**Dependencies**: IMP-2, IMP-12.

### IMP-31 — Deterministic dedupe (email/phone) _(8 pts)_
**User story**: As a steward, exact matches resolve to the same core person.  
**Acceptance Criteria**
- Blocking on normalized email & E.164 phone; updates instead of inserts.  
- Counters for resolved vs inserted.  
**Dependencies**: IMP-30.

### IMP-32 — Survivorship v1 _(5 pts)_
**User story**: As a steward, conflicts resolve predictably.  
**Acceptance Criteria**
- Prefer non-null; prefer manual edits; prefer most-recent verified.  
- Change log entries created.  
**Dependencies**: IMP-31.

### IMP-33 — Idempotency regression tests _(3 pts)_
**User story**: As QA, running the same file twice yields no net new records.  
**Acceptance Criteria**
- Replay test passes; diffs only when payload changed.  
**Dependencies**: IMP-30.

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

