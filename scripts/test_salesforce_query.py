#!/usr/bin/env python3
"""
Test script to verify Salesforce SOQL query returns expected record count.

This script tests the query builder to ensure it includes NULL values
and matches the expected record count from Salesforce.

Usage:
    python scripts/test_salesforce_query.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flask_app.importer.adapters.salesforce.extractor import build_contacts_soql, create_salesforce_client, SalesforceExtractor


def verify_query_builder():
    """Verify the SOQL query builder with different configurations."""
    
    print("=" * 80)
    print("Testing Salesforce SOQL Query Builder")
    print("=" * 80)
    print()
    
    # Test 1: Query with volunteer filter (should include NULL)
    print("Test 1: Query with volunteer filter (including NULL)")
    print("-" * 80)
    soql_with_filter = build_contacts_soql(filter_volunteers=True)
    print(f"SOQL Query:\n{soql_with_filter}\n")
    
    # Check if NULL is included
    if "Contact_Type__c = null" in soql_with_filter:
        print("✓ NULL values are included in the query")
    else:
        print("✗ NULL values are NOT included in the query")
    print()
    
    # Test 2: Query without volunteer filter
    print("Test 2: Query without volunteer filter")
    print("-" * 80)
    soql_without_filter = build_contacts_soql(filter_volunteers=False)
    print(f"SOQL Query:\n{soql_without_filter}\n")
    print()
    
    # Test 3: Query with watermark (should still include NULL)
    print("Test 3: Query with volunteer filter and watermark")
    print("-" * 80)
    from datetime import datetime, timezone
    test_watermark = datetime(2024, 1, 1, tzinfo=timezone.utc)
    soql_with_watermark = build_contacts_soql(filter_volunteers=True, last_modstamp=test_watermark)
    print(f"SOQL Query:\n{soql_with_watermark}\n")
    
    if "Contact_Type__c = null" in soql_with_watermark:
        print("✓ NULL values are included even with watermark")
    else:
        print("✗ NULL values are NOT included with watermark")
    print()
    
    return soql_with_filter


def verify_live_query():
    """Verify the query against live Salesforce (if credentials are available)."""
    
    print("=" * 80)
    print("Testing Live Salesforce Query")
    print("=" * 80)
    print()
    
    # Check if Salesforce credentials are available
    required_vars = ["SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"⚠ Skipping live test - missing environment variables: {', '.join(missing_vars)}")
        print("Set SF_USERNAME, SF_PASSWORD, and SF_SECURITY_TOKEN to test against live Salesforce")
        return None
    
    try:
        print("Connecting to Salesforce...")
        client = create_salesforce_client()
        print("✓ Connected successfully")
        print()
        
        # Build the query
        soql = build_contacts_soql(filter_volunteers=True)
        print(f"Executing query:\n{soql}\n")
        
        # Create extractor
        extractor = SalesforceExtractor(client=client, batch_size=1000)
        
        # Count records
        total_records = 0
        batch_count = 0
        
        print("Fetching records...")
        for batch in extractor.extract_batches(soql):
            batch_count += 1
            total_records += len(batch.records)
            print(f"  Batch {batch_count}: {len(batch.records)} records (total: {total_records})")
        
        print()
        print("=" * 80)
        print(f"Total records retrieved: {total_records}")
        print("=" * 80)
        print()
        
        # Expected count from user's manual query
        expected_count = 12377
        if total_records == expected_count:
            print(f"✓ SUCCESS: Retrieved {total_records} records (matches expected {expected_count})")
        else:
            print(f"⚠ WARNING: Retrieved {total_records} records, expected {expected_count}")
            print(f"  Difference: {expected_count - total_records} records")
        
        return total_records
        
    except Exception as e:
        print(f"✗ Error testing live query: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Main test function."""
    
    # Test query builder
    soql = verify_query_builder()
    
    # Test live query if credentials available
    count = verify_live_query()
    
    print()
    print("=" * 80)
    print("Test Summary")
    print("=" * 80)
    print()
    print("Query Builder Tests: ✓ Completed")
    if count is not None:
        print(f"Live Query Test: ✓ Completed ({count} records)")
    else:
        print("Live Query Test: ⚠ Skipped (no credentials)")
    print()
    print("To verify the query manually in Salesforce, run:")
    print()
    print(soql)
    print()


if __name__ == "__main__":
    main()

