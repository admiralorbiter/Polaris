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
- `flask importer retry --run-id <id>`  
  Retry a failed or pending run using stored parameters. Requires the original upload file to still exist.

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

# Test CSV adapter with golden data
flask importer run --source csv --file ops/testdata/importer_golden_dataset_v0/volunteers_valid.csv --inline

# View run summary in JSON (for automation)
flask importer run --source csv --file <path> --inline --summary-json
```

### Debugging Tips

1. **Use `--inline` flag**: For local debugging, use `--inline` to run synchronously and see immediate output/logs.
2. **Check run status**: Query `import_runs` table directly or use admin UI to inspect run details and `counts_json`.
3. **Review worker logs**: If using async mode, check Celery worker logs for task execution details.
4. **Validate CSV format**: Use golden dataset files as reference for canonical CSV format.
5. **Test with dry-run**: Use `--dry-run` flag to validate pipeline without writing to core tables.

### Performance Considerations

- **Large files**: For files >10MB, prefer async mode (default) to avoid CLI timeout.
- **Worker concurrency**: Adjust `--concurrency` flag on worker startup for higher throughput.
- **SQLite transport**: Default SQLite broker is fine for local dev; use Redis/Postgres for production scale.

> For additional flags, run `flask importer --help` or append `--help` to any subcommand.

