#!/usr/bin/env python3
"""
Verify that the Salesforce query returns the expected 12,377 records.

This script:
1. Builds the SOQL query using the actual code
2. Executes it against Salesforce
3. Counts all records returned
4. Verifies it matches the expected count (12,377)

Usage:
    Set environment variables: SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN
    python scripts/verify_salesforce_count.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from flask_app.importer.adapters.salesforce.extractor import (
    build_contacts_soql,
    create_salesforce_client,
    SalesforceExtractor,
)

EXPECTED_COUNT = 12377


def main():
    """Main verification function."""
    
    print("=" * 80)
    print("Salesforce Record Count Verification")
    print("=" * 80)
    print()
    
    # Check credentials
    required_vars = ["SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"❌ ERROR: Missing required environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print()
        print("Please set these variables and try again.")
        return 1
    
    try:
        # Build the query (same as the import uses)
        print("Step 1: Building SOQL query...")
        soql = build_contacts_soql(filter_volunteers=True, last_modstamp=None)
        
        print("✓ Query built successfully")
        print()
        print("Query:")
        print("-" * 80)
        print(soql)
        print("-" * 80)
        print()
        
        # Verify NULL is in the query
        if "Contact_Type__c = null" not in soql:
            print("❌ ERROR: Query does not include NULL check!")
            print("   Expected: Contact_Type__c = null in WHERE clause")
            return 1
        
        print("✓ Query includes NULL check")
        print()
        
        # Connect to Salesforce
        print("Step 2: Connecting to Salesforce...")
        client = create_salesforce_client()
        print("✓ Connected successfully")
        print()
        
        # Create extractor
        print("Step 3: Creating extractor...")
        extractor = SalesforceExtractor(client=client, batch_size=5000)
        print("✓ Extractor created")
        print()
        
        # Execute query and count records
        print("Step 4: Executing query and counting records...")
        print("   This may take a few moments...")
        print()
        
        total_records = 0
        batch_count = 0
        
        for batch in extractor.extract_batches(soql):
            batch_count += 1
            batch_size = len(batch.records)
            total_records += batch_size
            print(f"   Batch {batch_count}: {batch_size:,} records (running total: {total_records:,})")
        
        print()
        print("=" * 80)
        print("RESULTS")
        print("=" * 80)
        print()
        print(f"Total batches processed: {batch_count}")
        print(f"Total records retrieved: {total_records:,}")
        print(f"Expected records:        {EXPECTED_COUNT:,}")
        print()
        
        if total_records == EXPECTED_COUNT:
            print("✅ SUCCESS: Record count matches expected value!")
            print(f"   Retrieved exactly {total_records:,} records")
            return 0
        else:
            difference = total_records - EXPECTED_COUNT
            if difference > 0:
                print(f"⚠️  WARNING: Retrieved {abs(difference):,} MORE records than expected")
            else:
                print(f"❌ ERROR: Retrieved {abs(difference):,} FEWER records than expected")
            print()
            print("Possible causes:")
            print("  - Query filter may not be matching all expected records")
            print("  - Salesforce data may have changed")
            print("  - There may be additional filters or permissions affecting results")
            return 1
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

