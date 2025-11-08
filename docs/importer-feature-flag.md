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
- Optional dependencies: install adapter extras with `pip install ".[importer]"` when enabling adapters that require third-party libraries.

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
- The nav bar shows an **Importer** dropdown (super admins only) when the flag is on and adapters are registered.

## CLI Usage
- Base command: `flask importer`
  - When enabled with adapters, prints the configured adapter list.
  - When disabled, raises a clear `Importer is disabled via IMPORTER_ENABLED=false` message.
- All CLI commands are light-weight: optional dependencies are not imported unless the feature is enabled.

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

## Related Docs
- `docs/data-integration-platform-overview.md` (§10 Optionality & Packaging) references flags and packaging guidance.
- `docs/data-integration-platform-tech-doc.md` (IMP-1 story) notes the environment defaults and docs requirement.

