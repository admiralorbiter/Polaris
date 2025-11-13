## Importer Command Reference

### Worker Lifecycle
- `flask importer worker run --loglevel=info --pool=solo`  
  Start the Celery worker locally. `--pool=solo` is required on Windows; add `--queues imports` or `--concurrency N` as needed.
- `flask importer worker ping`  
  Round-trip a heartbeat task to confirm the worker is responsive.
- `flask importer cleanup-uploads --max-age-hours 72`  
  Remove staged uploads older than the specified window. Avoid deleting files for runs you intend to retry.

### Import Operations
- `flask importer run --source csv --file path/to/volunteers.csv`  
  Queue an import run asynchronously and print a JSON payload describing the queued task.
- `flask importer run --source csv --file path/to/volunteers.csv --inline`  
  Run the pipeline inline within the CLI process (useful for debugging and tests).
- `flask importer run --source csv --file path/to/volunteers.csv --inline --summary-json`  
  Emit the full summary payload in JSON (only valid with `--inline`).
- `flask importer run --source csv --file path/to/volunteers.csv --dry-run`  
  Execute the full pipeline but skip core writes. `metrics_json` will contain would-be inserts/updates and the run is labeled DRY RUN in the dashboard.
- `flask importer retry --run-id <id>`  
  Retry a failed or pending run using stored parameters. Requires the original upload file to still exist.
- `flask importer run-salesforce --run-id <id>`  
  Queue the Salesforce ingest task for an existing import run (CLI-friendly helper while the UI trigger is pending).
- `celery -A app.celery call importer.pipeline.ingest_salesforce_contacts --kwargs '{"run_id": 42}'`  
  Queue a Bulk API Salesforce contact ingest for run 42 (adapter must be enabled and optional requirements installed).

### Adapter Diagnostics
- `flask importer adapters list`  
  Display readiness for each configured adapter (dependencies, env vars, current status). Mirrors the Admin → Imports Adapter Availability card.
- `flask importer adapters list --auth-ping`  
  Perform the standard readiness check and attempt a live Salesforce authentication. Emits Prometheus counters (`importer_salesforce_auth_attempts_total`) for success/failure.
- `flask importer mappings show`  
  Print the active Salesforce mapping YAML (respects `IMPORTER_SALESFORCE_MAPPING_PATH`). Useful for reviewing field coverage or exporting the config. Pipe to disk to diff changes (`flask importer mappings show > /tmp/sf_mapping.yaml`). Pair this with the Salesforce mapping guides in `docs/salesforce-mapping-guide.md` and `docs/salesforce-transforms-reference.md` when planning schema updates.

### Housekeeping
- `flask importer cleanup-uploads --max-age-hours <hours>`  
  Prune old uploads from `IMPORTER_UPLOAD_DIR`. Pair with retry awareness by keeping files needed for reruns.
- `flask importer cleanup-uploads --max-age-hours 1`  
  Example invocation for aggressive cleanup in local environments.

## Troubleshooting

### Common CLI Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| Command not found | `flask importer: No such command` | Verify `IMPORTER_ENABLED=true`. Check that importer CLI group is registered in app factory. |
| Worker ping fails | `flask importer worker ping` times out | Ensure worker is running (`flask importer worker run`). Check `CELERY_BROKER_URL` matches worker config. |
| Run fails immediately | `flask importer run` errors before queuing | Verify file exists and is readable. Check CSV header matches canonical format. Review error message for specific issue. |
| Retry fails | `flask importer retry --run-id X` errors | Verify run exists and has `ingest_params_json` populated. Check original file still exists at stored path. |
| Cleanup removes needed files | Files deleted but runs still reference them | Use longer retention window or check `keep_file=True` flag on runs before cleanup. |

### Verification Commands

Quick health checks before starting work:

```bash
# Verify importer is enabled
flask importer

# Check worker connectivity
flask importer worker ping

# Inspect adapter readiness
flask importer adapters list

# Test CSV adapter with golden data
flask importer run --source csv --file ops/testdata/importer_golden_dataset_v0/volunteers_valid.csv --inline

# View run summary in JSON (for automation)
flask importer run --source csv --file <path> --inline --summary-json
```

### Test Execution

- `python -m pytest …`  
  Runs pytest directly. Useful for tight loops against specific files or tests (e.g. `pytest tests/importer/test_idempotency_regression.py`). Keeps output focused on the selected scope and skips optional tooling.
- `python run_tests.py <mode>`  
  Wrapper that orchestrates linting, security checks, coverage runs, and artifact export. Notable modes:  
  - `python run_tests.py all` — equivalent to `pytest tests/ -v`.  
  - `python run_tests.py ci` — runs lint (unless `--no-lint`), Bandit, full pytest with coverage, then copies generated `idempotency_summary.json` files into `ci_artifacts/idempotency/` for dashboards.  
  - Other modes (`unit`, `integration`, `fast`, `parallel`, etc.) map to curated pytest command lines; run with `--help` for the full list.
- Environment toggles:  
  - `IMPORTER_METRICS_ENV` (defaults to `sandbox`) and `IMPORTER_METRICS_SANDBOX_ENABLED` gate the synthetic metrics the regression suite emits.  
  - `IMPORTER_ARTIFACT_DIR` controls where `idempotency_summary.json` artifacts land (defaults to `instance/import_artifacts/`).

### Debugging Tips

1. **Use `--inline` flag**: For local debugging, use `--inline` to run synchronously and see immediate output/logs.
2. **Check run status**: Query `import_runs` table directly or use admin UI to inspect run details and `counts_json`.
3. **Review worker logs**: If using async mode, check Celery worker logs for task execution details.
4. **Validate CSV format**: Use golden dataset files as reference for canonical CSV format.
5. **Test with dry-run**: Use `--dry-run` flag to validate pipeline without writing to core tables.

### Admin UI Tips

- **Dry-run toggle**: On `/admin/imports/`, select "Dry run (no writes to database)" to enqueue with `dry_run=true`. Successful runs show a yellow "DRY RUN" badge and detail banner clarifying no core writes occurred.
- **Salesforce import button**: When the Salesforce adapter is enabled and ready, the Imports page exposes a "Start a Salesforce Import" panel. Use the dry-run toggle for validation-only runs and expand "Advanced options" to set a record limit, reset the Salesforce watermark (with confirmation), or add operator notes. The UI queues the same Celery task as `flask importer run-salesforce` and is rate-limited to one trigger per minute per user—use the CLI for scripted or bulk testing.
- **Runs dashboard filters**: `/admin/imports/runs/dashboard` now includes an "Include dry runs" checkbox. Disable it to hide simulations from aggregate stats.
- **Remediation stats**: DQ inbox fetches remediation outcomes from `GET /admin/imports/remediation/stats?days=<N>`; useful for tracking steward effectiveness.
- **Runs stats API**: `GET /importer/runs/stats?include_dry_runs=0` surfaces aggregate counts for monitoring dashboards.
- **Data Quality Dashboard**: Access at `/admin/data-quality` to monitor field-level completeness across all entities. Features include overall health score, entity-level metrics, field-level completeness tables, organization filtering, and CSV/JSON export. Metrics are cached for 5 minutes; click "Refresh" to reload. See `docs/data-quality-dashboard.md` for detailed documentation.

### Performance Considerations

- **Large files**: For files >10MB, prefer async mode (default) to avoid CLI timeout.
- **Worker concurrency**: Adjust `--concurrency` flag on worker startup for higher throughput.
- **SQLite transport**: Default SQLite broker is fine for local dev; use Redis/Postgres for production scale.

> For additional flags, run `flask importer --help` or append `--help` to any subcommand.
