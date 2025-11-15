# Importer Feature Flag Overview

This note summarizes the IMP-1 work that makes the importer package optional and outlines how to enable, configure, and verify it locally.

## Configuration
- `IMPORTER_ENABLED`: defaults to `false`. Set to `true` to mount the importer blueprint, CLI, and menus.
- `IMPORTER_ADAPTERS`: comma-separated adapter list (case-insensitive). The config parser normalizes casing, removes duplicates, and validates that each adapter exists in the registry.
- Safety check: the app raises a `ValueError` at startup if `IMPORTER_ENABLED=true` but `IMPORTER_ADAPTERS` is empty or contains unknown adapters.
- Example env snippet (see `env.example`):
  ```
  IMPORTER_ENABLED=false
  IMPORTER_ADAPTERS=csv,salesforce,google_sheets
  ```
- Optional dependencies: install adapter extras with `pip install ".[importer-salesforce]"` (or consume `requirements-optional.txt`) when enabling adapters that require third-party libraries. The extras keep the base image slim while allowing opt-in installs.
- `IMPORTER_SALESFORCE_DOC_URL` / `IMPORTER_CSV_DOC_URL`: optional URLs surfaced in the admin Adapter Availability card so operators can jump to setup guides. Defaults point to Polaris internal docs.
- `IMPORTER_SALESFORCE_OBJECTS`: comma-separated Salesforce object list we expose (currently supports `contacts`, `organizations`, `affiliations`, and `events`; defaults accordingly).
- `IMPORTER_SALESFORCE_BATCH_SIZE`: Bulk API 2.0 query batch size; defaults to `5000` (minimum enforced at `1000`).
- `IMPORTER_SALESFORCE_MAPPING_PATH`: path to the active Salesforce→Volunteer mapping YAML (defaults to `config/mappings/salesforce_contact_v1.yaml`).
- `IMPORTER_UPLOAD_DIR`: optional path where uploaded files are staged for the worker (defaults to `instance/import_uploads`); accepts absolute or instance-relative values.
- `IMPORTER_MAX_UPLOAD_MB`: max CSV upload size exposed in the admin UI (defaults to `25`).
- `IMPORTER_SHOW_RECENT_RUNS`: toggle the recent-runs table on the admin importer page (defaults to `true`).

## Adapter Registry
- Defined in `flask_app/importer/registry.py`.
- Ships with placeholder descriptors for `csv`, `salesforce`, and `google_sheets`.
- Each descriptor includes a user-facing title, summary, and optional dependency hints.
- Future adapters should register here so validation works before implementation.

## Application Integration
- `init_importer(app)` (imported inside `flask_app/routes/__init__.py`) handles:
  - Conditional blueprint registration (`/importer/health` route).
  - CLI group mounting.
  - Template context processor exposing `importer_enabled` and `importer_menu_items`.
  - Startup log message indicating whether the importer was enabled and which adapters loaded.
  - Prometheus instrumentation for Salesforce readiness (`importer_salesforce_adapter_enabled_total`, `importer_salesforce_auth_attempts_total`).
- The nav bar shows an **Importer** dropdown (super admins only) when the flag is on and adapters are registered.

## CLI Usage
- Base command: `flask importer`
  - When enabled with adapters, prints the configured adapter list.
  - When disabled, raises a clear `Importer is disabled via IMPORTER_ENABLED=false` message.
- All CLI commands are light-weight: optional dependencies are not imported unless the feature is enabled.
    - `flask importer run --source csv --file …` queues a run by default and prints machine-readable JSON (`--inline` retains the synchronous behaviour for local debugging).
    - `flask importer retry --run-id <id>` retries a failed or pending import run using stored parameters. Requires the original file to still exist and the run to have been created with retry support (stores `ingest_params_json`).
    - `flask importer cleanup-uploads --max-age-hours 72` removes staged upload files older than the specified window—handy for on-prem installs storing files on disk. Note: admin uploads retain files for retry capability (`keep_file=True`), so consider run associations when pruning.
    - `flask importer run-salesforce --run-id <id>` queues the Salesforce ingest Celery task for an existing run (helpful until the UI trigger ships).
    - `flask importer adapters list [--auth-ping]` surfaces adapter readiness (deps/env/auth). Use `--auth-ping` to attempt a live Salesforce auth check and record Prometheus counters.
    - `flask importer mappings show` prints the active Salesforce mapping YAML so operators can diff or download the source of truth.
- Salesforce ingest task (run via Celery): queue `importer.pipeline.ingest_salesforce_contacts` with `run_id=<id>` after enabling the adapter and installing optional requirements.
- On Windows, start the worker with `flask importer worker run --pool=solo` because the default prefork pool is not supported.

## Health Endpoint
- `GET /importer/health` returns JSON:
  ```json
  {
    "status": "ok",
    "enabled": true,
    "adapters": [
      {"name": "csv", "title": "CSV Flat File", ...}
    ]
  }
  ```
- Useful for smoke tests validating conditional mounting.

## Testing
- `tests/test_importer_feature_flag.py` covers:
  - Disabled state: no blueprint, stub CLI group, template context shows disabled.
  - Enabled state: blueprint + CLI present, adapter data returned, menu context populated.
  - Adapter validation: unknown adapters raise `ValueError`.
- Suggested follow-up: extend tests as adapters gain functionality (e.g., registry-driven loading, CLI subcommands).

## Troubleshooting

### Common Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| Importer not appearing in UI | No "Importer" menu in nav bar | Verify `IMPORTER_ENABLED=true` and `IMPORTER_ADAPTERS` is non-empty. Check app logs for startup errors. |
| Unknown adapter error | `ValueError: Unknown adapter 'xyz'` | Check adapter name spelling in `IMPORTER_ADAPTERS`. Valid names: `csv`, `salesforce`, `google_sheets` (case-insensitive). |
| Worker not starting | `flask importer worker run` fails | On Windows, add `--pool=solo`. Verify `IMPORTER_WORKER_ENABLED=true` if using conditional worker startup. |
| Health endpoint 404 | `GET /importer/health` returns 404 | Ensure importer is enabled (`IMPORTER_ENABLED=true`) and blueprint registered. Check `flask routes` for `/importer/health`. |
| CLI command not found | `flask importer` raises "No such command" | Verify importer is enabled. Check that `init_importer(app)` is called in app factory. |
| Adapter not loading | Adapter missing from health response | Verify adapter name in `IMPORTER_ADAPTERS` matches registry entry. Run `flask importer adapters list` for detailed readiness (deps/env/auth). |
| Salesforce adapter ready status = missing-deps | CLI/admin UI shows "Missing dependencies" | Install extras: `pip install ".[importer-salesforce]"` or `pip install -r requirements-optional.txt`. Rebuild optional Docker layer if using a baked image. |
| Salesforce ingest stalled | Run stays in `running` | Check worker logs for Bulk API job state; verify `importer_watermarks` entry updated and credentials allow Bulk API access. |
| Mapping YAML download fails | `/admin/imports/mappings/salesforce.yaml` returns 500 | Verify `IMPORTER_SALESFORCE_MAPPING_PATH` points to a readable YAML file and the app process has permissions. |

### Quick Verification Checklist

Before starting Sprint 2 work, verify Sprint 1 completion:

- [ ] `IMPORTER_ENABLED=true` in `.env` or environment
- [ ] `IMPORTER_ADAPTERS=csv` (or comma-separated list)
- [ ] App starts without errors (check logs for importer initialization message)
- [ ] `flask importer` command works (prints adapter list)
- [ ] `flask importer worker ping` succeeds (worker running)
- [ ] `GET /importer/health` returns JSON with `enabled: true`
- [ ] Admin UI shows "Importer" menu (super admin only)
- [ ] Admin → Imports page renders Adapter Availability card (CSV ready, Salesforce disabled by default)
- [ ] Can upload CSV via admin UI or CLI (`flask importer run --source csv --file <path>`)
- [ ] Test run completes and creates records in `import_runs` table
- [ ] Golden dataset files exist in `ops/testdata/importer_golden_dataset_v0/`

### Debugging Tips

1. **Check app logs**: Look for importer initialization messages on startup. Errors will indicate missing config or adapter issues.
2. **Verify blueprint registration**: Run `flask routes | grep importer` to confirm routes are mounted.
3. **Test worker connectivity**: Use `flask importer worker ping` to verify Celery worker is reachable.
4. **Inspect database**: Query `import_runs` table to verify runs are being created.
5. **Check file permissions**: Ensure `IMPORTER_UPLOAD_DIR` is writable if using file-based uploads.

## Related Docs
- `docs/reference/architecture/data-integration-platform-overview.md` (§10 Optionality & Packaging) references flags and packaging guidance.
- `docs/reference/architecture/data-integration-platform-tech-doc.md` (IMP-1 story) notes the environment defaults and docs requirement.
- `docs/operations/commands.md` provides CLI command reference and usage examples.
