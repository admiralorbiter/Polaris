# Importer Definition of Done (DoD)

Confirm every box is checked before closing an importer ticket. Copy/paste into your PR or story checklist.

## Code & Flags
- ✅ Feature flag / configuration guards in place.
- ✅ Migrations (if any) run cleanly on fresh DB and upgrade/downgrade paths are documented.
- ✅ Celery tasks registered appropriately and worker health verified (`flask importer worker ping` or `/importer/worker_health` when applicable).

## Tests
- ✅ Unit tests updated/added for all touched modules.
- ✅ Integration/CLI scenario executed (e.g., importer run against golden dataset sample) when relevant.
- ✅ Regression tests covering edge cases (DQ rules, idempotency, dedupe) run or scheduled.

## Documentation & Communication
- ✅ Tech docs/backlog updated (story reference, feature flag docs, golden dataset README if new scenarios were added).
- ✅ Release notes / changelog entry drafted if user-visible behavior changes.
- ✅ Rollback plan confirmed (disable flag, revert migration, or manual recovery steps).

## Observability
- ✅ Metrics/logs updated and checked (counts in `import_runs.counts_json`, worker logs, DQ stats).
- ✅ Alerts/monitoring thresholds adjusted if behavior changed.

