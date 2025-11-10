# Importer Definition of Ready (DoR)

Every importer ticket should satisfy these checks before it enters development. Copy this list into the story description and tick each item as you go.

## Story Clarity
- ✅ User story and acceptance criteria describe observable outcomes (counts, DQ behavior, UI state, etc.).
- ✅ Dependencies are listed (feature flags, schema migrations, Celery tasks, external credentials, upstream stories).

## Data & Environment
- ✅ Required input artifacts identified (which golden dataset file or new sample CSV/JSON).
- ✅ New env vars or flags noted in the story (including defaults).
- ✅ Rollback + risk mitigation captured (e.g., “can disable flag,” “migration reversible”).
- ✅ Survivorship profile needs captured (field groups, any overrides, `IMPORTER_SURVIVORSHIP_PROFILE_PATH` expectations).

## Testing & Observability Plan
- ✅ Tests you intend to add are named (unit, integration, CLI/manual run, regression).
- ✅ Metrics/logs you expect to see are called out (e.g., new counters in `/importer/worker_health`).
- ✅ Survivorship success metrics (manual wins vs incoming overrides) and warning paths documented.

## Acceptance Checklist
Use the companion Definition of Done (DoD) doc for release sign‑off.

