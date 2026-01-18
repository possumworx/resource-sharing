#!/usr/bin/env python3
"""
Migration: Add cost_delta tracking columns
- Add cost_delta (actual $ spend) to resource_share_increments
- Add normalized_usage (for fairness calculations) to resource_share_increments
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "resource_tracking.db"

def migrate():
    """Apply migration."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("=== Adding Cost Delta Tracking Columns ===")

    # Add cost_delta to resource_share_increments
    try:
        cursor.execute("""
            ALTER TABLE resource_share_increments
            ADD COLUMN cost_delta REAL
        """)
        print("✓ Added cost_delta column to resource_share_increments")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("⚠ cost_delta column already exists")
        else:
            raise

    # Add normalized_usage to resource_share_increments
    try:
        cursor.execute("""
            ALTER TABLE resource_share_increments
            ADD COLUMN normalized_usage REAL
        """)
        print("✓ Added normalized_usage column to resource_share_increments")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("⚠ normalized_usage column already exists")
        else:
            raise

    conn.commit()
    conn.close()

    print("\n✓ Migration complete!")
    print("\nNote: Old columns (cache_read_increment, weighted_cost) are kept for backwards compatibility")
    print("      New code will use (cost_delta, normalized_usage)")

if __name__ == '__main__':
    migrate()
