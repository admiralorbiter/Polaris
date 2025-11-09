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

> For additional flags, run `flask importer --help` or append `--help` to any subcommand.

