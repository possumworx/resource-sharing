#!/usr/bin/env python3
"""
Migration: Add cost tracking columns
- Add cost_multiplier to claude_identities
- Add weighted_cost to resource_share_increments
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "resource_tracking.db"

def migrate():
    """Apply migration."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("=== Adding Cost Tracking Columns ===")

    # Add cost_multiplier to claude_identities
    try:
        cursor.execute("""
            ALTER TABLE claude_identities
            ADD COLUMN cost_multiplier INTEGER DEFAULT 3
        """)
        print("✓ Added cost_multiplier column to claude_identities")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("⚠ cost_multiplier column already exists")
        else:
            raise

    # Add weighted_cost to resource_share_increments
    try:
        cursor.execute("""
            ALTER TABLE resource_share_increments
            ADD COLUMN weighted_cost INTEGER
        """)
        print("✓ Added weighted_cost column to resource_share_increments")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("⚠ weighted_cost column already exists")
        else:
            raise

    conn.commit()

    # Backfill weighted_cost for existing records
    print("\n=== Backfilling weighted_cost for existing records ===")
    cursor.execute("""
        UPDATE resource_share_increments
        SET weighted_cost = (
            SELECT cache_read_increment * COALESCE(ci.cost_multiplier, 3)
            FROM claude_identities ci
            WHERE ci.name = resource_share_increments.claude_name
        )
        WHERE weighted_cost IS NULL
    """)
    rows_updated = cursor.rowcount
    print(f"✓ Backfilled {rows_updated} rows")

    conn.commit()
    conn.close()

    print("\n✓ Migration complete!")

if __name__ == '__main__':
    migrate()
