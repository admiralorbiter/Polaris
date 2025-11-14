# Sprint 5 Analytics & Ops Alignment

Objective: ensure Analytics and Operations teams know which fuzzy dedupe metrics are shipping in Sprint 5, where they will surface, and how alerts should be configured.

## 1. Metric Inventory

| Metric | Description | Source | Status |
|--------|-------------|--------|--------|
| `importer_dedupe_candidates_total{match_type}` | Count of generated candidates by type (`deterministic_email`, `fuzzy_high`, `fuzzy_review`). | Prometheus counter (new). | ✅ Implemented |
| `importer_dedupe_auto_total{match_type}` | Auto merges executed automatically (deterministic + fuzzy). | Prometheus counter (existing deterministic, extend for fuzzy). | ✅ Implemented |
| `importer_dedupe_auto_per_run_total{run_id, source}` | Auto merges per run. | Prometheus counter. | ✅ Implemented |
| `importer_dedupe_manual_review_per_run_total{run_id, source}` | Manual review candidates per run. | Prometheus counter. | ✅ Implemented |
| `importer_dedupe_manual_total` | Manual merges completed via Merge UI. | Prometheus counter. | ❌ Not implemented (TODO: Sprint 6) |
| `importer_dedupe_undo_total{decision_type}` | Undo actions taken (manual vs auto). | Prometheus counter. | ❌ Not implemented (TODO: Sprint 6) |
| `importer_dedupe_queue_size` | Gauge of review queue backlog. | API endpoint + Prometheus gauge. | ❌ Not implemented (TODO: Sprint 6) |
| `importer_dedupe_resolution_seconds` | Histogram of time from candidate creation → resolution. | Prometheus histogram. | ❌ Not implemented (TODO: Sprint 6) |
| Dashboard KPIs (auto %, manual %, undo %) | Derived metrics for Ops dashboards. | Looker (or equivalent) fed from Prometheus/exporter. | ⚠️ Partial (auto % available, manual % and undo % need metrics above) |

## 2. Dashboard Requirements

- **Ops Dashboard (primary)**
  - Auto vs manual merge counts (daily + trailing 7 days).
  - Review queue backlog with aging buckets (<24h, 24–48h, >48h).
  - Undo rate with alert threshold (>5%).
  - Top reasons for “Not a duplicate” (from steward notes) once captured.
- **Product/Engineering Dashboard**
  - Candidate volume by match_type.
  - Average fuzzy score for manual merges vs auto merges.
  - Feature drift indicators (top signals contributing to manual rejects).

## 3. Alerting Proposal

| Alert | Condition | Channel | Notes |
|-------|-----------|---------|-------|
| Manual review backlog high | `importer_dedupe_queue_size > 50` for 15 minutes. | Ops Slack + Pager (business hours). | Threshold configurable via Config UI (Sprint 7). |
| Undo rate spike | `undo_total / auto_total > 0.05` over rolling 1h. | Ops Slack + email digest. | Include top 5 merges undone. |
| Candidate generator errors | Failure rate > 5% or latency > 2s. | Engineering Slack. | Provided by candidate generation task instrumentation. |

## 4. Data Flow

1. Prometheus metrics emitted from importer services.
2. Metrics scraped by existing Prometheus server (ensure new time series added to `monitoring-config.yaml`).
3. Grafana/Looker dashboards consume Prometheus or exported CSV (daily job).
4. Alertmanager routes to Slack/email according to table above.

## 5. Action Items

| Task | Owner | Due |
|------|-------|-----|
| Approve metric names/labels with Analytics. | Data Analytics Lead | ☐ |
| Update Prometheus recording rules/alerts. | DevOps | ☐ |
| Build/refresh Grafana dashboard for dedupe KPIs. | Analytics Engineer | ☐ |
| Coordinate with Ops on alert recipients & escalation paths. | Ops Manager | ☐ |
| Document dashboard access in Ops handbook. | Docs | ☐ |

## 6. Open Questions

1. What SLAs apply to manual review queue? (Impacts alert severity.) ⚠️ **To be determined** (default: 1 business day recommended)
2. Should undo alerts page after-hours or queue for next business day? ⚠️ **To be determined** (pending final policy decision)
3. Do stakeholders need aggregate reports emailed weekly (CSV/PDF)? ⚠️ **To be determined** (export functionality not yet implemented - TODO: Sprint 6)
4. Which analytics platform (Looker vs Grafana) hosts the canonical dedupe dashboard? ⚠️ **To be determined** (Analytics team)
5. Who owns regression of metrics post-launch (Analytics vs Ops)? ⚠️ **To be determined** (pending ownership assignment)

**Sprint 5 Completion Status**: ✅ Metrics infrastructure in place; missing metrics (manual merge, undo, queue size, resolution time) need implementation in Sprint 6.

**Action Items for Sprint 6**:
1. Implement missing metrics (`importer_dedupe_manual_total`, `importer_dedupe_undo_total`, `importer_dedupe_queue_size`, `importer_dedupe_resolution_seconds`)
2. Set up queue size alerts (threshold > 50 for 15 minutes)
3. Implement export functionality for dedupe summaries (CSV/JSON)
4. Finalize SLA and notification preferences with stakeholders
5. Set up dashboard ownership and regression testing process

Capture answers inline once decisions are made to keep the plan synchronized.
