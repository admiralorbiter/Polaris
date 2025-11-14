# Data Import Platform

[volunteer_import_platform_markdown_backlog.md](volunteer_import_platform_markdown_backlog.md)

# Volunteer Data Import & Quality Platform

**Target**: Flask app with optional Salesforce (and other source) imports

**Style**: Modular monolith now; microservice-ready later

## 0) Executive Summary

- Build an **import platform** inside your Flask repo, but fully **optional** and **adapter-based**.
- Use an **ELT pipeline** with **staging → clean → core** layers, plus **identity resolution** and **data-quality (DQ)** gates.
- Provide an **Admin UI** for run monitoring, quarantines, duplicates, mappings, and reconciliation.
- Capture **metrics, logs, and lineage** so you can detect “leaks” (missing, stale, or malformed data) fast.
- Package adapters (Salesforce, CSV, Google Sheets) as **plug-ins**—only enabled when needed.
- Keep all features **configuration-driven** (env, flags, YAML), so other orgs can use the app with or without imports.

## 1) Goals, Non‑Goals, and Guiding Principles

### Goals

1. Reliable, repeatable imports with **idempotent upserts**.
2. **Human-in-the-loop** remediation for DQ issues and duplicates.
3. **Observability**: clear status, metrics, errors, and lineage.
4. **Optionality**: app works fine without any importer enabled.
5. **Open-source readiness**: adapters are pluggable; default CSV path.

### Non‑Goals

- Rebuild Salesforce; instead, **normalize** it into your clean domain.
- Real-time streaming: start **batch/incremental**; consider streaming later.
- Hard dependency on any single vendor or tool.

### Principles

- **Contracts at the boundary** (canonical ingest models).
- **Schema separation**: `staging_*` and `import_*` are isolated from `core_*`.
- **Fail-safe defaults**: quarantine on uncertainty; never silently drop data.
- **Auditability** over cleverness; keep a paper trail for every mutation.

## 2) Architecture Overview

### 2.1 High-Level Components

- **Core domain**: Volunteers, Organizations/Schools, Events, Shifts, Signups/Attendance, Roles, Skills, Consents.
- **Importer package** (internal module):
    - **Adapters**: Salesforce, CSV, Google Sheets (extensible).
    - **Contracts**: canonical entity payloads (e.g., VolunteerIngest).
    - **DQ**: field/row/set rules; quarantines.
    - **Dedupe**: deterministic + fuzzy matching; merge decisions.
    - **Orchestrator**: job graph (extract → validate → dedupe → upsert → reconcile).
    - **Admin UI**: runs, DQ inbox, data quality dashboard, duplicates, reconciliation, mappings, controls.
- **Worker process**: Celery worker on the `imports` queue, defaulting to a SQLite-backed broker/result store so local development needs only Python; swap to Redis/Postgres for higher throughput deployments.
- **Storage**: Postgres (recommended), Redis (queues), object storage (CSV uploads & exports).

### 2.2 Modular Monolith Today, Microservice Later

- Keep importer **in-repo**, mounted via feature flag (`IMPORTER_ENABLED`).
- If growth demands it, lift importer out unchanged: connect via shared DB schema or REST/queue endpoints.

## 3) Data Layers & Tables (no code, just structure)

### 3.1 Staging (raw land)

- `staging_volunteers`, `staging_events`, `staging_signups`, etc.
- Columns:
    - `run_id` (FK to `import_runs`), `source`, `external_id`, `payload_json`, `extracted_at`.
- Purpose: store raw records exactly as extracted (for replay & audits).

### 3.2 Import/Control

- `import_runs` — one row per run: `id`, `source`, `status` (pending/running/succeeded/failed/partially_failed), timestamps, `counts_json` (per-entity in/out), `error_summary`, `freshness_max_timestamp`, `hashes`, `anomaly_flags`.
- `dq_violations` — `run_id`, `entity_type`, `record_key`, `rule_code`, `severity`, `details_json`, `status` (open/fixed/suppressed).
- `dedupe_suggestions` — candidate pairs with score & features; `decision` (auto-merged/accept/reject/defer).
- `external_id_map` — `(entity_type, external_system, external_id) → core_id`, `first_seen_at`, `last_seen_at`.
- `merge_log` — merges/undo merges with provenance & survivorship.
- `change_log` — field-level changes to core entities (who/when/why).

### 3.3 Clean layer (normalized views/tables)

- Normalize/validate from staging to “clean” equivalents (`clean_*`) using rules. Records failing rules remain in quarantine.
- `clean_volunteers` stores normalized payloads, staging back-references, row checksums (future idempotency drift detection), and eventual load actions (`inserted`, `skipped_duplicate`, etc.) to give operators lineage into core.

### 3.4 Core domain

- Your existing clean schema (`core_volunteer`, `core_event`, etc.)—the importer **upserts** here, never bypassing rules.

## 4) Canonical Ingest Contracts (what crosses the boundary)

Define **canonical fields** per entity. Examples (select highlights):

### VolunteerIngest (canonical)

- Identity: `external_system`, `external_id`, `first_name`, `last_name`
- Contacts: `email_normalized`, `phone_e164`, `alt_emails`, `alt_phones`
- Demographics (optional): `dob`, `gender`, `race_ethnicity` (if collected)
- Address (normalized): `street`, `city`, `state_code`, `postal_code`, `country_code`
- Org linkage: `employer`, `school_affiliation`, `student_flag`
- Compliance: `consent_signed_at`, `background_check_status`, `background_check_date`, `photo_release`
- Meta: `source_updated_at`, `ingested_at`, `ingest_version`

### EventIngest / SignupIngest

- Events: `title`, `start_at`, `end_at`, `location`, `host_org_id`, `program_type`
- Signups: `(volunteer_ref, event_ref, shift_ref)`, `rsvp_status`, `attended_flag`, `hours`, `role`

**Version** contracts (e.g., `ingest_version=1.3`) so mappings can evolve without breaking.

## 5) End‑to‑End Pipeline (E‑L‑T‑L‑R)

1. **Extract**
    - Salesforce: SOQL/Bulk API or your existing SQL pulls (via replication DB).
    - Incremental key: `SystemModstamp`/`LastModifiedDate` (SF) or `updated_at` in your replica/SQL.
    - Controls: `since` parameter; **dry-run** support.
2. **Land (Staging)**
    - Write raw rows to `staging_*` with `run_id`.
    - Record extract counts, window (`since`, `until`), max source timestamp.
3. **Transform & Validate (Clean)**
    - Normalize email (lowercase; optionally strip `+tags`), phone (E.164), names (trim/title-case), addresses.
    - Apply DQ rules (see §6): required fields, format, domain, cross-field, reference, set-level.
    - Good rows → `clean_*`; bad rows → `dq_violations` + quarantine.
4. **Link & Dedupe (Identity Resolution)**
    - Deterministic blocking: email, phone, external_id_map.
    - Fuzzy features (see §7): name similarity, DOB, address, employer, school ties.
    - Decisions: auto-merge, human-review queue, or new record.
    - Always update `external_id_map`.
5. **Load (Upsert to Core)**
    - Idempotent upserts keyed by `(external_system, external_id)` **or** resolved `core_id`.
    - Create-only v1 skips exact-email duplicates, records metrics (`rows_skipped_duplicates`, duplicate email roster), and annotates clean/staging rows for observability.
    - **Field survivorship** policies (see §7.4).
6. **Reconcile (Leak detection)**
    - Compare source vs loaded counts; drift/anomalies; **freshness**; hashes of canonical payloads.
    - Write metrics to `import_runs.counts_json` and expose in UI.

## 6) Data Quality (DQ) Rules & Quarantine

### 6.1 Rule Types

- **Required**: must have at least one contact (email or phone), name present, event start/end valid.
- **Format**: email RFC-like, E.164 phone, ISO dates, 2-letter state codes.
- **Domain**: no disposable email domains; birthdate not in future; grad year plausible [1900..current+10].
- **Cross-field**: if `consent_required=true` ⇒ `consent_signed_at` present; if `attended=true` ⇒ `hours ≥ 0`.
- **Reference**: event/site codes exist; org/school foreign keys resolvable.
- **Set-level**: null-rate spikes, duplicate-rate spikes, distribution anomalies (e.g., 90% of records suddenly from one school).

Each rule has: `rule_code`, `severity` (error/warn/info), remediation hints, and category.

> Minimal gate (IMP-11) hard-codes three error rules today: `VOL_CONTACT_REQUIRED`, `VOL_EMAIL_FORMAT`, and `VOL_PHONE_E164`. The pipeline records outcomes in `import_runs.counts_json["dq"]["volunteers"]` and mirrors full evaluation metrics (even for dry-runs) in `metrics_json`; CLI/worker logs echo per-rule tallies to fast-track triage.

### 6.2 Quarantine & Remediation Flow

- Violations logged per row with context (raw + normalized view).
- **Statuses**: open → fixed (edited & re-queued) / suppressed (exemption) / won’t-fix (with reason).
- Bulk actions: fix common errors (e.g., normalize a known bad domain), re-run DQ.
- Export/import CSV for offline cleanup; re-ingest without losing lineage.

### 6.3 Anomaly Detectors (Leak Alarms)

- **Freshness guard**: latest `source_updated_at` older than N hours.
- **Delta guard**: new volunteers today deviate > 3σ from 14-day mean.
- **Null drift**: missing phone/email exceeds 2× trailing baseline.
- **Upsert parity**: sample canonical hashes pre- vs post-load must match.

## 7) Identity Resolution (Duplicates & Merges)

### 7.0 Duplicate Detection Scope

**Important**: The import pipeline performs **one-way duplicate detection**:
- **During Import**: New records from the current import run are checked against **existing volunteers** in the database
- **Limitation**: Duplicates among **existing volunteers** (that were imported before duplicate review existed, or created through other means) are **not automatically detected** during import
- **Manual Scan Required**: To find duplicates among existing volunteers, operators must run a **manual scan** via the Duplicate Review UI

**Why this design?**
- Import-time dedupe is **O(n)** where n = new records (efficient)
- Full scan of all volunteers is **O(n²)** where n = all volunteers (expensive)
- Manual scans are run periodically for historical cleanup, not on every import

**When to use each:**
- **Import-time dedupe**: Automatically runs on every import to prevent new duplicates
- **Manual scan**: Run periodically (e.g., monthly) to find duplicates in historical data, or after bulk imports from legacy systems

### 7.1 Blocking Keys (fast candidates)

- Normalized email
- Phone in E.164
- `(first_name_soundex, last_name_soundex, postal_code)`
- `(first_initial, last_name, birth_year)` for family-shared emails/phones

### 7.2 Similarity Features (scored)

- Name (first+last) similarity (token + Jaro–Winkler/Levenshtein)
- DOB exact/close
- Address similarity (house + street + postal)
- Employer/school match
- Event co-attendance patterns (soft signal)
- Email user-part similarity (handle) and domain equality
- Phone last-4 match when full unavailable

### 7.3 Thresholds & Actions

- Score ≥ 0.95 → **auto-merge**
- 0.80–0.95 → **human review** queue
- < 0.80 → **new person**

### 7.4 Merge & Survivorship Policies

- **Field-level rules**:
    - Prefer **non-null** over null.
    - Prefer **most recently verified** source.
    - Source priority: **manual edits in app** > your ingestion > Salesforce (tuneable).
    - For addresses/phones/emails, maintain **multi-valued** lists; mark a **primary**.
- Log all merges to `merge_log`; allow **undo merge** with complete reversal.
- Write back to `external_id_map` so future imports resolve to the merged `core_id`.

### 7.5 Edge Cases

- Shared emails (households, minors) → treat as **household** link, not necessarily same person.
- Name collisions in common names (e.g., "John Smith") → require extra signals (DOB, address).
- International phone formats; missing country → infer by locale or site default.
- SF merges/splits: detect when an `external_id` disappears or points to a different Contact → reconcile map.

## 8) Admin UI (Operator Experience)

### 8.1 Runs Dashboard

- Columns: Run ID, Source, Status, Started/Ended, Duration, Rows In/Out, Rejects, Auto‑merges, Review‑needed, Freshness, Anomaly flags.
- Actions: **drill-down**, **download quarantines**, **rerun step**, **cancel**, **retry failed step**.
- Filters: by date, source, status.

### 8.2 DQ Inbox

- Filters: rule, severity, entity, run.
- Row detail: raw payload, normalized view, errors list, remediation hints.
- Actions: **edit & requeue**, **suppress**, **bulk-fix** patterns, **export**.

### 8.3 Duplicate Review

- Side-by-side compare; highlight differences and feature contributions.
- Actions: **merge**, **not a duplicate**, **defer**; pick survivorship per field.
- Batch-mode for obvious matches.

### 8.4 Data Quality Dashboard

- **Field-Level Completeness**: Monitor data completeness across all entities (Contacts, Volunteers, Students, Teachers, Events, Organizations, Users, Affiliations)
- **Overall Health Score**: Weighted health score (0-100%) based on field completeness
- **Entity Cards**: Visual cards showing completeness per entity type with key metrics
- **Field Tables**: Detailed field-level completeness metrics with status indicators
- **Organization Filtering**: Filter metrics by organization (super admins) or view organization-specific metrics
- **Export**: Export metrics as CSV or JSON for analysis and tracking
- **Caching**: 5-minute cache for performance with manual refresh option
- **Access**: `/admin/data-quality` (requires `view_users` permission)

> **Note**: The Data Quality Dashboard is separate from the DQ Inbox. The dashboard provides field-level completeness metrics for all entities, while the DQ Inbox focuses on import violations. See `docs/reference/data-quality/data-quality-dashboard.md` for detailed documentation.

### 8.5 Reconciliation & Source Health

- Trend charts: records ingested over time, reject rate, duplicate rate, freshness lag.
- Source card: credentials status, rate limits, last success, next scheduled.
- Data drift widgets: null-rate, distribution changes, top rule offenders.

### 8.6 Mappings & Settings

- View the **Salesforce → Canonical** field mapping; versioned.
- Toggle rules, set thresholds, source priorities.
- Configure schedules, backfill windows, dry-run, alert thresholds.

### 8.7 Audit & Lineage

- Entity detail page: provenance timeline (which source, when, what changed), link to run & change logs.

## 9) Orchestration, Scheduling, Idempotency

- **Tasks**: `extract`, `land`, `validate`, `dedupe`, `upsert`, `reconcile`.
- **Worker**: Celery/RQ on Redis; concurrency controlled per source to avoid rate-limits.
- **Scheduling**: cron/Celery Beat; per-source frequency (e.g., Salesforce hourly, CSV manual).
- **Idempotency**:
    - Use `(external_system, external_id)` and/or a **payload hash** (`idempotency_key`) to avoid duplicate work.
    - Upserts must be **atomic**; soft-fail records individually, not the whole batch.
- **Retries & Backoff**:
    - Transient errors (network/429) → exponential backoff.
    - Permanent errors → quarantine with actionable message.
- **Checkpointing**:
    - Store `since` watermark per entity/source; on success, advance; on failure, keep previous.

## 10) Optionality & Packaging (for other orgs)

- **Feature flags**: `IMPORTER_ENABLED=false` by default.
- **Adapter list**: `IMPORTER_ADAPTERS=csv` (others opt-in).
- **Optional dependencies**: import extras only when adapters are enabled (e.g., Salesforce client).
- **Installation**: ship `env.example` (copy to `.env`) with importer disabled and document `pip install ".[importer]"` for feature-specific extras.
- **CSV-first**: ship sample CSV templates & a CSV adapter so anyone can use the importer without Salesforce.
- **Extension points**: adapters registered via entry points; DQ rules and dedupe features support plug-in registration.
- **Documentation**: quickstart for CSV, separate guide for Salesforce.
- CLI supports `--summary-json` to emit machine-readable run statistics for automation harnesses and regression scripts.

## 11) Security, Privacy, Compliance

- **PII classification**: name, email, phone, DOB, address → protect in transit & at rest.
- **Least privilege**: separate DB roles for importer vs web app; narrow Salesforce scopes.
- **Secrets**: environment vault (no secrets in the DB/UI).
- **RBAC**: importer UI accessible only to specific admin roles; field-level permissions for sensitive fields (DOB).
- **Audit**: all admin actions (edits, suppressions, merges) recorded with actor, timestamp, reason.
- **Data retention**: define retention for staging & quarantines (e.g., 90 days); anonymize old records.
- **Consent provenance**: store consent source & timestamp; never overwrite a valid consent with null.
- **Export safety**: CSV export sanitizes formulas to avoid CSV/Excel injection.

## 12) Observability & Alerts

- **Metrics** (per run and over time):
    - Extracted vs loaded counts by entity
    - Reject rate, duplicate rate (auto vs manual)
    - Clean promotion vs core insert counts, duplicate skips, and duplicate email roster
    - Freshness lag (now − max source timestamp)
    - Anomaly flags (delta/null drift)
    - Task durations & queue latency
- **Structured logs**: run_id, entity, source, record_key, error_code.
- **Tracing** (optional): OpenTelemetry spans per task with run_id correlation.
- **Alerts**:
    - Run failure or partial failure
    - Freshness lag over threshold
    - Reject rate or duplicate rate spike
    - Credentials expired / rate limit exhaustion

## 13) Testing & QA Strategy

- **Golden dataset**: curated sample with known duplicates, edge-case emails/phones, minors/household scenarios, and DQ violations.
- **Property-based tests** (conceptually): normalization invariants (e.g., email lowercasing stable, phone formatting reversible).
- **Contract tests**: validate adapter outputs against canonical models.
- **Replay tests**: run the same input twice to prove idempotency.
- **Load tests**: large backfills; watch memory/queue behavior; ensure quarantining scales.
- **Migration tests**: simulate Salesforce schema drift (new/renamed fields).

## 14) Deployment & Ops

- **Processes**: web (Flask) and worker (Celery) as separate processes/containers; locally, `flask importer worker run` uses the built-in SQLite transport so no Redis is required.
- On Windows, add `--pool=solo` when launching the CLI worker so Celery uses the compatible single-process pool.
- **Production tuning**: set `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` to Redis or Postgres, adjust worker concurrency flags, and run `celery beat` (or cron) for scheduled nightly imports.
- **Migrations**: add importer tables first; keep core untouched.
- **Blue/Green or canary** for enabling new rules—start as **warn-only** before enforcing.
- **Backfill runbook**:
    1. Dry‑run with sampling enabled.
    2. Run low-volume canary source/site.
    3. Scale to full backfill with lower concurrency.
    4. Monitor anomaly metrics; pause on spikes.
- **Rollback**: if a bad upsert occurs, use `change_log` to revert field-level changes or roll back the run using the captured diffs.

## 15) Data Mapping & Governance

- **Mapping workbook** (store in repo as YAML/JSON):
    - For each entity: source field → canonical field, transform, required?, default, notes.
    - Versioned (`mapping_version`), referenced by runs.
- **Change control**:
    - Promote mapping changes through review; record in `import_runs` which mapping version was used.
- **Schema drift handling**:
    - When adapter sees new source fields, flag as **unmapped** in the run summary.
    - Provide a “mapping suggestions” panel in UI.

## 16) Edge Cases & Gotchas (expanded)

- **No email & no phone**: hold in quarantine; allow manual creation with a **temporary identifier**.
- **Multiple people share one phone**: avoid auto-merge unless DOB/address also match.
- **Gmail `+tag` addresses**: optionally strip tags for matching; store original too.
- **Internationalization**: names with diacritics; normalize but keep originals for display.
- **Time zones**: store timestamps in UTC; display by org/site time zone.
- **Daylight Saving Time**: never schedule imports exactly at DST shift; prefer UTC cron.
- **Soft deletes**: if source marks a record inactive/deleted, define policy (archive vs delete) and provenance.
- **Reactivated volunteers**: keep history; avoid new core_id.
- **Salesforce merges**: detect when two external_ids now map to one SF Contact; unify in `external_id_map`.
- **CSV injection**: escape `=`, `+`, , `@` at cell start in exports.
- **Rate limits**: throttle; align concurrency with SF Bulk API quotas.
- **Large attachments**: if sources include blobs (photos, PDFs), process asynchronously and reference by URL/key.

## 17) Roadmap (sensible sequence)

**Phase 1 (MVP)**

- Staging tables, `import_runs`, `dq_violations`, `external_id_map`, `dedupe_suggestions`.
- CSV adapter + Salesforce adapter using your existing SQL queries.
- Required/format rules; deterministic dedupe (email/phone).
- Runs dashboard + DQ inbox (basic).
- Dry-run mode, backfill since.

**Phase 2**

- Fuzzy dedupe with thresholds + Merge UI.
- Reconciliation metrics & anomaly detectors.
- Mapping workbook UI; versioning.
- Source health page, alerts (email/Slack).

**Phase 3**

- Multi-entity expansion (events, signups, attendance, consent).
- Drift detection and schema-diff alerts.
- Undo-merge & advanced survivorship.
- Microservice option (if needed): shared DB or queue boundary.

## 18) Acceptance Criteria (concrete)

- A run can be started (UI/CLI), shows **running**, then **succeeded** with counts and freshness.
- If a rule is violated, the record appears in **DQ inbox** with clear error and remediation.
- If an import is retried, **no duplicates** appear in core.
- Duplicate pairs ≥ threshold are auto-merged; 0.80–0.95 appear in **Duplicate Review**.
- Operators can export quarantines, fix, and requeue; the run summary updates.
- Disabling the importer removes all importer UI; the rest of the app is unaffected.
- With importer off, CSV bulk create still works for core entities (no Salesforce dependency).

## 19) Implementation Pointers (where things live)

- **Repo layout**
    - `/app/core` — domain models & services
    - `/app/web` — main Flask routes/templates
    - `/app/importer` — adapters, contracts, dq, dedupe, orchestrator, admin UI
- **Config**
    - ENV vars: `IMPORTER_ENABLED`, `IMPORTER_ADAPTERS`, `IMPORTER_SCHEDULE`, `IMPORTER_RULES_MODE=warn|enforce`, thresholds.
    - Worker flags: `IMPORTER_WORKER_ENABLED` (default false), `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`; leave unset to use the bundled SQLite transport (`celery.sqlite`) so no Redis is required locally.
    - DoR/DoD checklists live in `docs/operations/importer-dor.md` and `docs/operations/importer-dod.md`; reference them from importer issues.
    - Golden dataset samples live under `ops/testdata/importer_golden_dataset_v0/`; update the README when new scenarios are added.
    - Baseline metrics/logging: record staging rows landed, validation failures (`dq_violations` per rule), dedupe suggestions/decisions, load insert/update/skip counts, and confirm worker heartbeat via CLI/health endpoint.
    - YAML mapping files stored under `/app/importer/mappings/`.
- **Local dev bootstrap** (add to `.env` for quick testing)
    ```
    IMPORTER_ENABLED=true
    IMPORTER_ADAPTERS=csv
    IMPORTER_WORKER_ENABLED=true
    CELERY_CONFIG={"task_always_eager": true, "task_eager_propagates": true}
    ```
- **Processes**
- **Processes**
    - Web: `gunicorn ...`
    - Worker: `flask importer worker run` (wraps Celery with the configured transport)
    - Scheduler: `celery beat` or cron (reuses the same broker, still viable with SQLite for low-volume jobs)

## 20) Glossary

- **Adapter**: Source-specific extractor/mapper (Salesforce, CSV, etc.).
- **Canonical contract**: The normalized schema crossing into your system.
- **Quarantine**: Holding area for invalid records.
- **Run**: A single execution of the pipeline with metadata & results.
- **External ID map**: Bridge from source IDs to core IDs.
- **Identity resolution**: Matching/merging duplicates across/within sources.

## 21) Appendix A — DQ Rule Catalog (starter set)

- **REQ-001**: Volunteer must have at least one of `{email, phone}`.
- **FMT-101**: Email must match normalized format; domain has MX.
- **FMT-102**: Phone normalized to E.164; country default applied if absent.
- **DOM-201**: DOB not in future; age in [10..110] if present.
- **DOM-202**: Grad year ∈ [current_year − 50, current_year + 10].
- **XFLD-301**: `attended=true` ⇒ `hours ≥ 0`.
- **REF-401**: `event_id` must exist; `school_code` must map to known org.
- **SET-501**: Null email rate within 2× trailing 30-day average—or flag.

Each rule has: **severity**, **remediation hint**, **auto-fix? (y/n)**, **owner**.

## 22) Appendix B — Dedup Feature Weights (example starting point)

- Email exact match: **0.70**
- Phone exact match: **0.60**
- Name (first+last) similarity: **0.20**
- DOB exact: **0.20** (cap total at 1.0 with multiple features)
- Address similarity: **0.15**
- Employer/school match: **0.05**
- Adjust based on real data; keep human-review band (0.80–0.95).

## 23) Appendix C — Alert Thresholds (defaults)

- **Freshness lag** > 12 hours → warn; > 24 hours → page.
- **Reject rate** > 10% (5-run median) → warn; > 20% → page.
- **Duplicate rate** > 5% over baseline → warn.
- **Run failure** → page if not resolved within 30 minutes.

## 24) Appendix D — Operator Runbooks

**Backfill**

- Set `since` to a safe date; enable **dry-run**; check DQ counts.
- Run canary site; verify merges; move to full with concurrency=1 then increase.
- Monitor metrics; halt on anomalies; export quarantines for batch fixes.

**Credential Rotation**

- Use service account with minimal scopes; rotate quarterly; health page should show expiry countdown.

**Incident: Spike in Missing Phones**

- Check adapter mapping changes; examine SET-501 drift; sample rows; roll back mapping version if needed.

## High‑level roadmap (Epics)

- **EPIC‑0**: Foundations — feature flags, tables, processes, and “off‑by‑default”.
- **EPIC‑1**: CSV adapter + ELT skeleton (Volunteers only).
- **EPIC‑2**: Runs dashboard + DQ (required/format) + quarantine UX.
- **EPIC‑3**: Deterministic dedupe + idempotent upsert + external ID map.
- **EPIC‑4**: Salesforce adapter (via existing SQL/replica/SOQL), incremental runs.
- **EPIC‑5**: Fuzzy dedupe + Merge UI + survivorship + undo merge.
- **EPIC‑6**: Reconciliation & anomaly detection + metrics & alerts + health page.
- **EPIC‑7**: Mapping versioning + config UI + dry‑run/backfill tooling.
- **EPIC‑8**: Expand entities (Events, Signups/Attendance) + cross‑entity DQ.
- **EPIC‑9**: Security/RBAC/Audit/Retention + packaging & OSS‑readiness.

# Sprint 0 — Foundations (EPIC‑0)

**Goal**: Create the skeleton so the importer can live inside the Flask app, be **optional**, and run jobs in a separate worker.

**Out of scope**: Real data ingestion, UI polish.

### Tickets

**IMP‑1 — Feature flags & optional mounting (5 pts)**

**User story**: As an admin, I want the importer to be disable‑able so deployments that don’t need it see no importer UI or dependencies.

**Acceptance criteria**

- `IMPORTER_ENABLED=false` hides all importer routes/menus/CLI.
- `IMPORTER_ADAPTERS` is parsed (e.g., `csv`, `salesforce`), but nothing loads unless enabled.
- App boots with or without the importer installed.

    **Tasks**: App factory guard; conditional blueprint registration; config docs.


**IMP‑2 — Base DB schema for imports (8 pts)**

**User story**: As a developer, I need tables for runs, staging, violations, dedupe, and external ID mapping to support ELT.

**Acceptance criteria**

- Tables exist: `import_runs`, `staging_volunteers`, `dq_violations`, `dedupe_suggestions`, `external_id_map`, `merge_log`, `change_log`.
- Foreign keys & indexes for `run_id`, `(external_system, external_id)`.
- Migrations run cleanly on empty DB and existing app DB.

    **Tasks**: Migration scripts; index plan; roll‑back tested.

    **Edge cases**: schema idempotency; null‑safe columns.


**IMP‑3 — Worker process + queues (5 pts)**

**User story**: As an operator, I want long‑running tasks to run off the web thread.

**Acceptance criteria**

- Celery (or RQ) worker connects to Redis, consumes from `imports` queue.
- Health check endpoint shows worker connectivity.
- Graceful shutdown of tasks (SIGTERM).

    **Tasks**: Worker procfile/compose; env docs; sample “no‑op” task.


**IMP‑4 — “Definition of Ready/Done” & QA harness (3 pts)**

**User story**: As PM/QA, I want shared definitions and a golden dataset scaffold.

**Acceptance criteria**

- DoR/DoD checklists documented.
- A “Golden Dataset v0” spec exists (CSV with tricky emails/phones/names).
- Test data lives in `/ops/testdata` with README.

**Sprint 0 risks & mitigations**

- *Risk*: Over‑coupling importer to web app. → **Mitigation**: strict module boundaries (`/app/importer/*`).
- *Risk*: Migrations collide with core schema. → **Mitigation**: namespaced `import_*/staging_*` tables.

# Sprint 1 — CSV adapter + ELT skeleton (EPIC‑1)

**Goal**: End‑to‑end import for **Volunteers via CSV** through staging → minimal DQ → core (no dedupe yet).

### Tickets

**IMP‑10 — CSV adapter & ingest contracts (5 pts)**

**User story**: As an operator, I can ingest volunteers from a CSV that matches our canonical contract.

**Acceptance criteria**

- Canonical fields accepted (first/last/email/phone/etc.).
- Bad headers are rejected with actionable error.
- Extract writes to `staging_volunteers` with `run_id`.

    **Tasks**: Contract validation; header/row counters; error surfacing.

    **Dependencies**: IMP‑2.


**IMP‑11 — Minimal DQ: required & format (5 pts)**

**User story**: As a data steward, I want invalid rows quarantined with clear reasons.

**Acceptance criteria**

- Rules: at least one of `{email, phone}`; email format; phone E.164.
- Violations logged to `dq_violations` with rule codes.
- Clean rows flow to next step.

    **Tasks**: Validator functions; violation writer.


**IMP‑12 — Upsert (create‑only) into core volunteers (8 pts)**

**User story**: As an operator, I can load new volunteers into core without duplicates (for now assume unique email).

**Acceptance criteria**

- New rows insert; existing (exact email match) skipped with metric.
- Run shows counts: read/cleaned/loaded/skipped.
- No deadlocks; transaction per batch.

    **Tasks**: Upsert service; counters in `import_runs.counts_json`.

    **Edge cases**: empty email/phone.


**IMP‑13 — CLI & admin action: start a run (3 pts)**

**User story**: As an admin, I can trigger an import by file from UI or CLI.

**Acceptance criteria**

- `flask importer run --source csv --file …` queues a run and prints a JSON payload (`{"run_id":…, "task_id":…, "status":"queued"}`); operators can pass `--inline` for the legacy synchronous path.
- Admin Importer page (flagged) accepts CSV upload, enqueues the Celery task, and polls `/admin/imports/<run_id>/status` for live updates.
- Run status visible (pending/running/done/failed) with error summary surfaced on failure.

    **Dependencies**: IMP‑3.


**Sprint 1 demo success**

- Upload CSV ⇒ run completes ⇒ new volunteers visible in core.
- DQ violations viewable in raw table (UI to come).

# Sprint 2 — Runs dashboard + DQ inbox MVP (EPIC‑2)

**Goal**: Operator UX for runs and quarantines; basic remediation loop.

### Tickets

**IMP‑20 — Runs dashboard (5 pts)**

**User story**: As an admin, I can see a list of runs with status and counts.

**Acceptance criteria**

- Columns: `run_id`, source, started/ended, status, rows in/out, rejects.
- Drill‑down shows `counts_json`, latest anomalies (placeholder).
- Pagination & filter by source/status/date.

    **Dependencies**: IMP‑13.


**IMP‑21 — DQ inbox (basic) with CSV export (8 pts)**

**User story**: As a data steward, I can review violations and export for offline fixes.

**Acceptance criteria**

- Filter by rule code/severity/run.
- Row detail shows staging payload & normalized preview.
- Export button produces CSV of violations.

    **Tasks**: Read models; secure download.


**IMP‑22 — Remediate: edit & requeue (8 pts)**

**User story**: As a steward, I can correct a quarantined row and re‑queue it.

**Acceptance criteria**

- Edit form with validation; upon save, row is revalidated and (if clean) proceeds to upsert.
- Violation status transitions to `fixed`; audit trail records who/when/what.

    **Edge cases**: partial edits; multi‑violation rows.


**IMP‑23 — Dry‑run mode (3 pts)**

**User story**: As an operator, I can run an import without writing to core.

**Acceptance criteria**

- Flag `-dry-run` or UI toggle; everything executes except final upsert.
- Run result shows “no writes performed”.

    **Dependencies**: IMP‑12, IMP‑20.


# Sprint 3 — Deterministic dedupe + idempotent upsert (EPIC‑3)

**Goal**: True idempotency with `(external_system, external_id)` and deterministic matching on email/phone.

### Tickets

**IMP‑30 — External ID map & idempotent upsert (8 pts)**

**User story**: As an operator, I can re‑run imports without creating duplicates.

**Acceptance criteria**

- `external_id_map` populated for CSV (use `csv:<row-id>` or provided `external_id`).
- Upsert keyed by `(external_system, external_id)`; safe retries.
- `last_seen_at` updated; `first_seen_at` preserved.

    **Dependencies**: IMP‑2, IMP‑12.


**IMP‑31 — Deterministic dedupe (email/phone) (8 pts)**

**User story**: As a steward, I want exact email/phone matches to resolve to the same core person.

**Acceptance criteria**

- Blocking: normalized email; phone E.164.
- When match found, update existing core person rather than insert.
- Counters for “resolved vs inserted” visible on run.

    **Edge cases**: shared emails; empty fields.


**IMP‑32 — Survivorship v1 (field‑level) (5 pts)**

**User story**: As a steward, I need predictable rules when data conflicts.

**Acceptance criteria**

- Prefer non‑null over null; prefer manual edits over imports; prefer most recent verified timestamp.
- Rules documented and visible in UI tooltip.

    **Tasks**: Policy file/config; change log writes.


**IMP‑33 — Regression tests on idempotency (3 pts)**

**User story**: As QA, I want proof that a duplicate run produces no net new changes.

**Acceptance criteria**

- Same input twice ⇒ zero new inserts; updates only if data changed.
- Change log diff shows stable results.

# Sprint 4 — Salesforce adapter (optional) (EPIC‑4)

**Goal**: Wire in Salesforce **without making it a dependency**. Use your existing SQL/queries or SOQL/Bulk; support incremental by `LastModifiedDate/SystemModstamp`.

### Tickets

**IMP‑40 — Adapter loader & optional deps (3 pts)**

**User story**: As an operator, I can enable Salesforce only when needed.

**Acceptance criteria**

- `[salesforce]` extra declared (dependency optionality).
- If adapter not installed but configured, UI surfaces a clear error/help.

**IMP‑41 — Salesforce extract → staging (8 pts)**

**User story**: As an operator, I can pull Contacts incrementally into staging.

**Acceptance criteria**

- `since` watermark stored per entity/source and respected.
- Extract records `run_id`, `source_updated_at`, raw payload.
- Rate limit/backoff handling; partial failures logged to run.

    **Tasks**: SOQL/Bulk or replica SQL; creds config; retries.


**IMP‑42 — Salesforce→canonical mapping v1 (8 pts)**

**User story**: As a developer, I can transform SF fields to our canonical `VolunteerIngest`.

**Acceptance criteria**

- Declarative mapping file; unmapped fields listed in run summary.
- Required & format DQ applied; violations recorded.

    **Edge cases**: SF field nulls; picklist values; time zones.


**IMP‑43 — Incremental upsert & reconciliation counters (5 pts)**

**User story**: As an operator, I can see “new/updated/unchanged” counts for the window.

**Acceptance criteria**

- Per‑run counters for created/updated/skipped; last modified max timestamp recorded.
- Canary run succeeds with a small SF subset.

# Sprint 5 — Fuzzy dedupe + Merge UI + undo (EPIC‑5)

**Goal**: Human‑in‑the‑loop identity resolution for non‑exact matches.

### Tickets

**IMP‑50 — Candidate generation & scoring (8 pts)**

**User story**: As a steward, I can see likely duplicates scored by similarity.

**Acceptance criteria**

- Blocking keys (email/phone/name+zip); features (name similarity, DOB, address).
- Scores persisted to `dedupe_suggestions` with features JSON.
- Thresholds configurable: auto‑merge ≥0.95; review band 0.80–0.95.

    **Edge cases**: missing DOB; international addresses.


**IMP‑51 — Merge UI (13 pts)**

**User story**: As an admin, I can compare two records, choose field‑by‑field winners, and merge safely.

**Acceptance criteria**

- Side‑by‑side view; field highlights; survivorship controls.
- On merge: `merge_log` entry; `external_id_map` unified; `change_log` diffs written.
- “Not a duplicate” and “Defer” actions available.

    **Security**: action requires admin role.


**IMP‑52 — Auto‑merge + undo merge (8 pts)**

**User story**: As an operator, obvious dupes merge automatically, and I can undo if needed.

**Acceptance criteria**

- Auto‑merge obeys thresholds; safe for deterministic matches.
- Undo reverses merges with full state restoration.

    **Dependencies**: IMP‑50, IMP‑51.


**IMP‑53 — Dedupe metrics on runs dashboard (3 pts)**

**User story**: As an admin, I can see auto‑merged/needs‑review counts per run.

**Acceptance criteria**

- New columns on runs; link to review queue.

# Sprint 6 — Reconciliation, anomaly detection & alerts (EPIC‑6)

**Goal**: Detect “leaks”, staleness, or spikes; expose trends and send alerts.

### Tickets

**IMP‑60 — Reconciliation & freshness (8 pts)**

**User story**: As an operator, I can see if the import is stale or missing data.

**Acceptance criteria**

- Freshness: `now - max(source_updated_at)`; thresholds warn/page.
- Source vs core counts (new/updated/unchanged) for window; hash parity spot checks.
- Results stored in `counts_json` & shown in UI.

**IMP‑61 — Anomaly detectors (8 pts)**

**User story**: As a PM, I want to know when reject/duplicate/null rates drift.

**Acceptance criteria**

- Delta guard (3σ change); null drift (2× baseline); rule offender rankings.
- Flags appear on runs and a new “Source Health” page.

**IMP‑62 — Alerts (email/Slack/webhook) (5 pts)**

**User story**: As an operator, I get notified on failures or critical anomalies.

**Acceptance criteria**

- Configurable channels; on/off per source.
- Alerts include direct links to the failing run or queue.

**IMP‑63 — Trend views (5 pts)**

**User story**: As a PM, I can view 30‑day trends for ingests, rejects, dups, freshness.

**Acceptance criteria**

- Charts render without external services; date filters; export PNG/CSV.

# Sprint 7 — Mapping versioning, config UI, backfills (EPIC‑7)

**Goal**: Make mappings first‑class, versioned, and manageable; add safe backfills.

### Tickets

**IMP‑70 — Versioned mappings (8 pts)**

**User story**: As a developer, I can update mappings without breaking history.

**Acceptance criteria**

- `mapping_version` stored on runs.
- UI shows current/previous; unmapped field warnings.

**IMP‑71 — Config UI + feature flags & thresholds (8 pts)**

**User story**: As an admin, I can tune thresholds, rule severities, and schedules.

**Acceptance criteria**

- Editable values for dedupe thresholds, anomaly thresholds, schedule (cron), rule modes (warn/enforce).
- Audit trail for config changes.

**IMP‑72 — Backfill UX & CLI (5 pts)**

**User story**: As an operator, I can backfill since a date with dry‑run.

**Acceptance criteria**

- `-since` param; watermarks respected; run labels (“backfill”).
- Concurrency limits & pausable runs.

**IMP‑73 — Mapping diffs & suggestions (5 pts)**

**User story**: As a developer, I see suggested mappings when new SF fields appear.

**Acceptance criteria**

- Run highlights unmapped source fields with sample values; exportable list.

# Sprint 8 — Expand to Events/Signups + cross‑entity DQ (EPIC‑8)

**Goal**: Bring the same pipeline to Events and Signups/Attendance with reference checks.

### Tickets

**IMP‑80 — Staging + contracts for Events, Signups (8 pts)**

**User story**: As an operator, I can ingest events and signups via CSV & Salesforce.

**Acceptance criteria**

- Staging tables `staging_events`, `staging_signups`.
- Contracts validate start/end times, references.
- Quarantine on invalid references.

**IMP‑81 — Reference DQ & FK checks (8 pts)**

**User story**: As a steward, I want cross‑entity validation (event exists, volunteer exists).

**Acceptance criteria**

- FKs resolved via `external_id_map` or core keys.
- Violations emit rule `REF-401`, remediation hints.

**IMP‑82 — Upsert for events & attendance (8 pts)**

**User story**: As an operator, I can load or update events and signups with idempotency.

**Acceptance criteria**

- `(external_system, external_id)` maintained for events and shifts.
- Attendance writes hours and status safely.

**IMP‑83 — Cross‑entity dashboards (5 pts)**

**User story**: As a PM, I can see end‑to‑end pipeline health across entities.

**Acceptance criteria**

- Filters by entity; combined metrics.

# Sprint 9 — Security, audit, packaging & OSS (EPIC‑9)

**Goal**: Harden for real data and distribution.

### Tickets

**IMP‑90 — RBAC & sensitive‑field gating (8 pts)**

**User story**: As an admin, I can restrict who sees DOB and merge actions.

**Acceptance criteria**

- Roles: Admin, Data Steward, Viewer.
- Sensitive fields masked for non‑admins.
- Merge/undo requires Admin.

**IMP‑91 — Audit completeness (5 pts)**

**User story**: As compliance, I need every admin action logged with who/when/what.

**Acceptance criteria**

- Audit logs for edits, suppressions, merges, config changes.
- Exportable audit trail.

**IMP‑92 — Retention & PII hygiene (5 pts)**

**User story**: As a steward, I want staging/quarantine retention (e.g., 90 days).

**Acceptance criteria**

- TTL jobs purge or anonymize old staging & violations.
- Export sanitization to prevent CSV injection.

**IMP‑93 — Packaging & “adapter extras” (5 pts)**

**User story**: As a developer, I can install the importer with or without Salesforce.

**Acceptance criteria**

- Optional deps groups `[importer]`, `[salesforce]`.
- README quickstarts (CSV path default), sample data & screenshots.

## Backlog (prioritized “nice‑to‑haves”)

- Streaming/near‑real‑time ingestion (webhooks, CDC).
- OpenTelemetry tracing and span correlation with `run_id`.
- Household modeling (shared emails/phones for minors).
- Address verification (USPS/LoQate) & geocoding for program proximity.
- Schema drift auto‑PRs when mapping changes.
- Microservice extraction (shared DB boundary or queue boundary).
- Advanced anomaly detection (seasonality using STL/Prophet).

## Cross‑sprint quality bars

**Definition of Ready (DoR)**

- User story written; acceptance criteria clear; dependencies identified; test data listed; flags/config keys named.

**Definition of Done (DoD)**

- Feature behind a flag (if applicable).
- Unit/functional tests pass; docs (operator + admin help) updated.
- Metrics counters added & visible in runs dashboard.
- Security reviewed (roles, PII exposure).
- Rollback strategy documented.

## Dependencies & sequencing highlights

- S0 tables/worker/flags → unblock all later work.
- CSV path first (S1–S3) = universal & low‑risk; proves ELT + DQ + idempotency.
- Salesforce (S4) rides on proven pipeline; remains optional by extras.
- Fuzzy dedupe (S5) after deterministic + survivorship to reduce churn.
- Recon/alerts (S6) once inserts/updates are stable.
- Mapping versioning & backfills (S7) after we’ve learned from initial runs.
- New entities (S8) after the platform is solid.
- Security/packaging (S9) after scope stabilizes.

## Test strategy (where & how to validate)

- **Golden dataset** with: same‑email diffs, phone variants, Gmail `+tag`, DOB conflicts, address variants, minors/households, invalid school/event references.
- **Replay tests**: same file twice ⇒ unchanged core counts; idempotency proven.
- **Threshold tests**: push dupes to 0.96 score to see auto‑merge; 0.90 to see review queue.
- **Anomaly tests**: synthetic spike in missing phones; expect drift flag & alert.
- **Security tests**: verify non‑admin cannot see DOB or perform merges.
- **Perf tests**: 100k volunteers CSV; ensure worker memory steady; batched transactions.

## Roles & RACI (lightweight)

- **Product/PM**: writes stories & acceptance criteria; prioritizes backlog.
- **Backend dev**: pipelines, adapters, idempotency, dedupe engine.
- **Full‑stack dev**: admin UI (Runs, DQ, Merge, Health, Config).
- **QA/Data steward**: golden dataset, DQ rule tuning, manual review workflows.
- **Ops**: secrets, worker scaling, alert channels.
