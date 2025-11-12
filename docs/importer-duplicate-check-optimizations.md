# Duplicate Check Pipeline Optimizations

This document outlines optimizations for the duplicate detection pipeline and process.

## Implemented Optimizations

### 1. ✅ Name Lookup Caching (load_core.py)
**Problem**: Each candidate in an import run was making individual database queries for name duplicate checks, even when checking the same name multiple times.

**Solution**: Added a per-session cache that stores name lookup results during a single import run.

**Impact**: 
- Reduces database queries for repeated names (common in batch imports)
- Cache is automatically reset at the start of each import run
- Minimal memory overhead (only stores normalized name tuples)

**Code**: `_name_cache` dictionary with session tracking in `load_core.py`

### 2. ✅ Optimized Scan Function (fuzzy_candidates.py)
**Problem**: The `scan_existing_volunteers_for_duplicates` function was O(n²) - loading all volunteers into memory and comparing each against all others.

**Solution**: Implemented a blocking strategy using database queries:
- Only loads volunteer IDs and names initially (lightweight)
- Uses database queries with blocking (same last name + first initial) to find potential matches
- Only loads full volunteer objects with relationships when needed for comparison
- Uses `Volunteer.id > volunteer1_id` to avoid duplicate comparisons

**Impact**:
- Much faster for large datasets (O(n) with blocking vs O(n²))
- Lower memory usage (doesn't load all volunteers at once)
- Better database index utilization
- Scales better as volunteer count grows

**Code**: Refactored `scan_existing_volunteers_for_duplicates` in `fuzzy_candidates.py`

## Recommended Future Optimizations

### 3. Functional Indexes for Lowercase Name Lookups
**Problem**: Using `func.lower()` on indexed columns prevents index usage in some databases.

**Options**:
- **PostgreSQL**: Create functional indexes: `CREATE INDEX idx_volunteer_first_name_lower ON volunteers (LOWER(first_name));`
- **SQLite**: Store normalized names in computed columns or separate indexed columns
- **Alternative**: Pre-compute and store `first_name_normalized` and `last_name_normalized` columns

**Impact**: Could improve name lookup queries by 10-100x depending on dataset size.

**Priority**: Medium (only needed if name lookups become a bottleneck)

### 4. Background Job Support for Long Scans
**Problem**: The scan function can take several minutes for large datasets, blocking the web request.

**Solution**: 
- Move scan to a Celery background task
- Add progress tracking via database or Redis
- Provide real-time progress updates via WebSocket or polling endpoint
- Store scan results incrementally as they're found

**Impact**: 
- Better user experience (non-blocking)
- Can handle very large datasets
- Progress visibility for users

**Priority**: High (for production use with large datasets)

### 5. Batch Name Lookups
**Problem**: Even with caching, we still make individual queries for each unique name.

**Solution**: 
- Collect all unique names from a batch of candidates
- Make a single query with `IN` clause or batch queries
- Map results back to candidates

**Impact**: 
- Reduces database round-trips
- Better query plan optimization by database
- Could improve import speed by 2-5x for large batches

**Priority**: Medium (nice to have, caching already helps significantly)

### 6. Enhanced Blocking Strategies
**Problem**: Current blocking (last name + first initial) might miss some matches or include too many false positives.

**Options**:
- **Soundex/Phonetic Matching**: Block by phonetic similarity for names
- **Multi-blocking**: Use multiple blocking strategies (name, DOB, address) and union results
- **Adaptive Blocking**: Adjust blocking strategy based on name frequency

**Impact**: 
- Better recall (find more true duplicates)
- Better precision (fewer false positives to check)
- More efficient for diverse name patterns

**Priority**: Low (current blocking works well for most cases)

### 7. Incremental Scanning
**Problem**: Full scans re-check all volunteers even if only a few new ones were added.

**Solution**:
- Track last scan timestamp
- Only compare new/updated volunteers against existing ones
- Periodically run full scans (e.g., weekly)

**Impact**: 
- Much faster for incremental updates
- Can run scans more frequently
- Reduces database load

**Priority**: Medium (useful for production with frequent imports)

### 8. Parallel Processing
**Problem**: Duplicate checking is CPU-bound (similarity calculations).

**Solution**:
- Use multiprocessing for similarity calculations
- Parallelize batch processing
- Use async database queries where possible

**Impact**: 
- Faster processing on multi-core systems
- Better resource utilization

**Priority**: Low (complexity vs benefit trade-off)

## Performance Metrics to Monitor

1. **Import Time**: Total time for duplicate checks during imports
2. **Scan Time**: Time for full volunteer scans
3. **Database Query Count**: Number of queries per import/scan
4. **Cache Hit Rate**: Percentage of name lookups served from cache
5. **Memory Usage**: Peak memory during scans

## Configuration Options

Consider adding these configuration flags:

```python
# Cache settings
IMPORTER_NAME_CACHE_ENABLED = True
IMPORTER_NAME_CACHE_SIZE = 1000  # Max cache entries

# Scan settings
IMPORTER_SCAN_BATCH_SIZE = 100  # Volunteers per batch
IMPORTER_SCAN_BLOCKING_STRATEGY = "name_initial"  # or "phonetic", "multi"

# Performance tuning
IMPORTER_FUZZY_MATCH_LIMIT = 50  # Max candidates to check per name
```

## Testing Recommendations

1. **Load Testing**: Test with 10K, 100K, 1M volunteers
2. **Cache Effectiveness**: Measure cache hit rates
3. **Query Performance**: Profile database queries
4. **Memory Profiling**: Monitor memory usage during scans
5. **Concurrent Imports**: Test multiple imports running simultaneously

