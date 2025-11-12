# Sprint 4 Retrospective & Lessons Learned

**Sprint**: Sprint 4 — Salesforce Adapter (Optional)  
**Date**: Post-Sprint 4 completion (November 2025)  
**Status**: ✅ Complete

## What Went Well

### Salesforce adapter integration is production-ready
- **Optional dependencies**: Python extras (`[importer-salesforce]`) and `requirements-optional.txt` with hashes enable clean installs without Salesforce dependencies for non-Salesforce customers.
- **Adapter bootstrapping**: Runtime readiness checks (`check_salesforce_adapter_readiness`) validate dependencies, credentials, and optional live auth, surfacing actionable error messages in CLI and admin UI.
- **Incremental ingestion**: Bulk API 2.0 integration with watermark tracking (`importer_watermarks`) enables efficient incremental syncs, respecting `SystemModstamp` cursors and handling rate limits gracefully.
- **End-to-end pipeline**: Complete flow from Salesforce extraction → staging → DQ validation → clean promotion → core loading works seamlessly with 16,500+ records successfully imported in testing.

### Mapping system provides flexibility
- **YAML-driven mapping**: Declarative `salesforce_contact_v1.yaml` serves as single source of truth, with versioning and checksum tracking for auditability.
- **Field-level transforms**: Phone normalization, date parsing, and nested structure handling (email/phone dicts) enable complex Salesforce field mappings.
- **Unmapped field detection**: Run metrics surface unmapped fields with samples, helping identify schema drift and missing mappings proactively.

### Data quality improvements
- **DQ payload extraction**: Fixed nested dict handling in `_compose_payload` to correctly extract email/phone values from Salesforce mapping outputs, preventing false quarantines.
- **Clean promotion**: Updated `_normalize_email` and `_normalize_phone` to handle nested structures, ensuring validated records promote correctly to `clean_volunteers`.
- **Core loading**: `SalesforceContactLoader` now creates actual Volunteer records (not just ExternalIdMap entries), with proper email/phone extraction and validation.

### Developer experience
- **CLI tooling**: New commands (`flask importer adapters list`, `flask importer create-salesforce-run`, `flask importer debug-staging`, `flask importer stats`, `flask importer load-clean`) provide comprehensive debugging and operational capabilities.
- **Admin UI integration**: Adapter Availability card on Admin → Imports page shows status, mapping version, and download links, making Salesforce setup transparent.
- **Metrics & observability**: Prometheus metrics (`importer_salesforce_*`) and structured logs provide visibility into adapter health, batch processing, and reconciliation actions.

## Challenges & Learnings

1. **Nested data structure handling**  
   - *Challenge*: Salesforce mapping creates nested dict structures (`email.primary`, `phone.mobile`) that weren't being correctly extracted for DQ validation, causing all records to be quarantined.  
   - *Learning*: Payload composition must handle both raw Salesforce fields and normalized nested structures. Extraction logic needs to check raw fields first, then fall back to nested dicts, with proper handling of empty dicts vs. missing values.  
   - *Fix*: Updated `_compose_payload` in `dq.py` to prioritize raw Salesforce fields (`Email`, `Phone`) before checking normalized dicts, and added extraction helpers in `clean.py` and `salesforce_loader.py`.

2. **Core loader was incomplete**  
   - *Challenge*: `SalesforceContactLoader` was only creating `ExternalIdMap` entries with placeholder IDs, not actual Volunteer records. This meant validated records weren't appearing in the core database.  
   - *Learning*: Loader implementations must create actual core entities, not just tracking records. Two-phase commit ensures watermark advancement only happens after successful core updates.  
   - *Fix*: Rewrote `_handle_create` and `_handle_update` to create/update Volunteer records with email/phone, handle duplicates, and properly link ExternalIdMap entries.

3. **Email/phone extraction from existing clean records**  
   - *Challenge*: Existing `clean_volunteers` records had dict structures stored as strings in the database, requiring parsing before extraction.  
   - *Learning*: Migration scenarios require handling both new normalized data and legacy formats. Extraction functions must handle dicts, JSON strings, and Python literal strings.  
   - *Fix*: Added `_extract_email` and `_extract_phone` helpers that handle dicts, JSON strings, and Python literal eval for maximum compatibility.

4. **Email validation edge cases**  
   - *Challenge*: Some Salesforce emails failed validation due to format issues or deliverability checks, causing loader failures.  
   - *Learning*: Email validation should be defensive—validate before creating ContactEmail, skip invalid emails gracefully, and log warnings for operator review.  
   - *Fix*: Added pre-validation in loader with try/catch around ContactEmail creation, logging warnings for invalid emails but continuing with volunteer creation.

5. **Timezone handling**  
   - *Challenge*: Datetime comparisons between timezone-aware and timezone-naive values caused errors in watermark advancement and run duration calculations.  
   - *Learning*: All datetime operations must explicitly use timezone-aware UTC timestamps. Watermark comparisons, run durations, and source timestamp tracking all require consistent timezone handling.  
   - *Fix*: Ensured all datetime objects are explicitly converted to `timezone.utc` before comparisons or arithmetic operations.

## Process Improvements

1. **Testing strategy**: Add integration tests that exercise the full pipeline (extract → stage → DQ → clean → core) with realistic Salesforce payloads, including nested structures and edge cases.
2. **Migration testing**: When adding new extraction logic, test against both fresh imports and existing clean records to catch legacy format issues early.
3. **Validation layering**: Implement validation at multiple stages (mapping transform, DQ rules, core loader) with clear error messages at each layer.
4. **Debug tooling**: Continue investing in CLI debug commands (`debug-staging`, `stats`) to help operators diagnose issues quickly without database access.
5. **Documentation**: Maintain the new Salesforce mapping guides (`docs/salesforce-mapping-guide.md`, `docs/salesforce-transforms-reference.md`, `docs/salesforce-mapping-examples.md`) as living documents when schemas evolve.

## Metrics & Observability

- ✅ Adapter readiness metrics: `importer_salesforce_adapter_enabled_total` gauge, auth attempt counters
- ✅ Batch processing: `importer_salesforce_batches_total{status}`, `importer_salesforce_batch_duration_seconds` histogram
- ✅ Reconciliation: `importer_salesforce_rows_total{action}` counters (created/updated/unchanged/deleted)
- ✅ Mapping: `importer_salesforce_mapping_unmapped_total{field}` counter for unmapped field detection
- ✅ Watermark tracking: `importer_salesforce_watermark_seconds` gauge
- ✅ Structured logs include batch sequences, record counts, job IDs, and action breakdowns
- ⚠️ Missing: Alerting thresholds for batch failures, rate limit exhaustion, or unmapped field spikes

## Recommendations for Sprint 5

1. **Operational runbooks**: Document Salesforce credential rotation, watermark reset procedures, and troubleshooting steps for common issues (rate limits, auth failures, mapping errors).
2. **Alerting**: Set up Prometheus alert rules for adapter failures, batch processing errors, and unmapped field spikes before production rollout.
3. **Performance optimization**: Consider batch size tuning and parallel batch processing for large orgs (180k+ records took ~9 minutes; may need optimization for larger datasets).
4. **Customer enablement**: Create setup guide for Salesforce connected app provisioning and credential configuration, with clear troubleshooting steps.
5. **Mapping evolution**: Plan for customer-specific mapping overrides (Sprint 7) while maintaining backward compatibility with v1 mapping.

## Open Questions

1. Should we add retry logic for transient Salesforce API failures (rate limits, timeouts)?
2. How should we handle Salesforce schema changes that break existing mappings—auto-detect and warn, or require manual mapping updates?
3. Do we need a "replay from watermark" feature to reprocess records since a specific timestamp?
4. Should unmapped field detection trigger automatic mapping suggestions or require manual review?

## Success Metrics

- ✅ 16,501 volunteers successfully imported from Salesforce (180,570 staged, 16,507 validated, 164,063 quarantined)
- ✅ Adapter availability checks working correctly with clear error messages
- ✅ Mapping YAML downloadable from admin UI with version/checksum tracking
- ✅ Reconciliation counters accurate (created/updated/unchanged/deleted)
- ✅ Watermark advancement working correctly with two-phase commit
- ✅ End-to-end pipeline tested with production-scale data (180k+ records)
- ✅ Salesforce mapping expansion playbooks documented for future fields/objects
- ⚠️ Some records skipped due to invalid emails (logged for review); consider DQ rule tuning

## Next Steps

- Plan Sprint 5 kickoff around fuzzy dedupe and merge UI while closing any Salesforce polish items.
- Add support enablement session covering Salesforce setup, credential management, and troubleshooting.
- Coordinate with analytics to add Salesforce-specific dashboards and alerting before GA.
- Document Salesforce adapter deployment procedures and rollback steps for production readiness.

