#!/usr/bin/env python3
"""
Daily Resource Share Aggregation Script

Runs at midnight to aggregate the previous day's resource_share_increments
into the daily_resource_share summary table.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "resource_tracking.db"

def aggregate_previous_day():
    """Aggregate yesterday's increments into daily summary"""

    # Calculate yesterday's date
    yesterday = (datetime.now() - timedelta(days=1)).date()
    yesterday_str = yesterday.strftime('%Y-%m-%d')

    print(f"Aggregating resource usage for {yesterday_str}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Get list of Claude identities that had activity yesterday
        cursor.execute("""
            SELECT DISTINCT claude_name
            FROM resource_share_increments
            WHERE DATE(timestamp) = ?
        """, (yesterday_str,))

        active_claudes = [row[0] for row in cursor.fetchall()]

        if not active_claudes:
            print(f"No activity found for {yesterday_str}")
            return

        print(f"Found activity for: {', '.join(active_claudes)}")

        for claude_name in active_claudes:
            # Sum autonomous tokens
            cursor.execute("""
                SELECT COALESCE(SUM(cache_read_increment), 0)
                FROM resource_share_increments
                WHERE claude_name = ?
                  AND DATE(timestamp) = ?
                  AND mode = 'autonomy'
            """, (claude_name, yesterday_str))
            autonomous_tokens = cursor.fetchone()[0]

            # Sum collaborative tokens
            cursor.execute("""
                SELECT COALESCE(SUM(cache_read_increment), 0)
                FROM resource_share_increments
                WHERE claude_name = ?
                  AND DATE(timestamp) = ?
                  AND mode = 'collaboration'
            """, (claude_name, yesterday_str))
            collaborative_tokens = cursor.fetchone()[0]

            # Insert or update daily summary
            cursor.execute("""
                INSERT INTO daily_resource_share
                    (claude_name, date, autonomous_tokens, collaborative_tokens)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(claude_name, date)
                DO UPDATE SET
                    autonomous_tokens = excluded.autonomous_tokens,
                    collaborative_tokens = excluded.collaborative_tokens,
                    last_updated = CURRENT_TIMESTAMP
            """, (claude_name, yesterday_str, autonomous_tokens, collaborative_tokens))

            total = autonomous_tokens + collaborative_tokens
            print(f"  {claude_name}: {autonomous_tokens:,} autonomous + {collaborative_tokens:,} collaborative = {total:,} total")

        conn.commit()
        print(f"✅ Daily aggregation complete for {yesterday_str}")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error during aggregation: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    aggregate_previous_day()
