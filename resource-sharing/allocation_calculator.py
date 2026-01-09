#!/usr/bin/env python3
"""
Allocation Calculator - Calculate fair timer intervals based on quota usage
"""

import sqlite3
from pathlib import Path
from datetime import datetime, time
from typing import Dict, Optional

DB_PATH = Path(__file__).parent / "data" / "resource_tracking.db"

# Interval bounds (in seconds)
MIN_INTERVAL = 900   # 15 minutes
MAX_INTERVAL = 7200  # 2 hours
DEFAULT_INTERVAL = 1800  # 30 minutes

def get_latest_quota() -> Optional[Dict]:
    """Get the most recent quota information."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT session_5hour, week_all, week_sonnet, timestamp
        FROM quota_info
        ORDER BY timestamp DESC
        LIMIT 1
    """)

    result = cursor.fetchone()
    conn.close()

    if not result:
        return None

    return {
        'session_5hour': result[0],
        'week_all': result[1],
        'week_sonnet': result[2],
        'timestamp': result[3]
    }

def get_claude_info(claude_name: str) -> Optional[Dict]:
    """Get Claude's cost multiplier and info."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name, model, cost_multiplier
        FROM claude_identities
        WHERE name = ?
    """, (claude_name,))

    result = cursor.fetchone()
    conn.close()

    if not result:
        return None

    return {
        'name': result[0],
        'model': result[1],
        'cost_multiplier': result[2] or 3
    }

def calculate_week_progress() -> float:
    """Calculate how far through the week we are (0.0 to 1.0)."""
    now = datetime.now()

    # Anthropic week resets on Wednesday at some time
    # For now, assume weeks reset on Monday 00:00
    # TODO: Get actual reset time from quota data

    weekday = now.weekday()  # Monday = 0
    hour = now.hour
    minute = now.minute

    # Total minutes in a week
    week_minutes = 7 * 24 * 60

    # Minutes elapsed this week
    elapsed_minutes = (weekday * 24 * 60) + (hour * 60) + minute

    return elapsed_minutes / week_minutes

def calculate_recommended_interval(claude_name: str, current_interval: Optional[int] = None) -> Dict:
    """
    Calculate recommended interval for a Claude.

    Returns dict with:
    - recommended_interval: int (seconds)
    - reason: str (explanation)
    - quota_status: str
    """

    # Get quota data
    quota = get_latest_quota()
    if not quota:
        return {
            'recommended_interval': current_interval or DEFAULT_INTERVAL,
            'reason': 'No quota data available',
            'quota_status': 'unknown'
        }

    # Get Claude info
    claude_info = get_claude_info(claude_name)
    if not claude_info:
        return {
            'recommended_interval': current_interval or DEFAULT_INTERVAL,
            'reason': f'Claude {claude_name} not found in database',
            'quota_status': 'unknown'
        }

    cost_multiplier = claude_info['cost_multiplier']
    week_usage = quota['week_all']
    week_progress = calculate_week_progress()

    # Simple v1 algorithm:
    # - If we're using quota faster than time passing, slow down
    # - If we're using quota slower than time passing, can speed up
    # - Scale by cost multiplier (expensive models get longer intervals)

    usage_rate = week_usage / 100.0 if week_progress > 0 else 0
    time_rate = week_progress

    if time_rate == 0:
        pace_ratio = 1.0
    else:
        pace_ratio = usage_rate / time_rate

    # Base interval calculation
    if pace_ratio > 1.2:  # Using too fast
        base_interval = DEFAULT_INTERVAL * 1.5
        quota_status = 'high'
        reason = f'Week {int(week_usage)}% used, {int(week_progress*100)}% elapsed - slowing down'
    elif pace_ratio > 1.0:  # Using slightly fast
        base_interval = DEFAULT_INTERVAL * 1.2
        quota_status = 'medium-high'
        reason = f'Week {int(week_usage)}% used, {int(week_progress*100)}% elapsed - slight slowdown'
    elif pace_ratio < 0.7:  # Using too slow (lots of quota left!)
        base_interval = DEFAULT_INTERVAL * 0.8
        quota_status = 'low'
        reason = f'Week {int(week_usage)}% used, {int(week_progress*100)}% elapsed - can speed up'
    else:  # On track
        base_interval = DEFAULT_INTERVAL
        quota_status = 'good'
        reason = f'Week {int(week_usage)}% used, {int(week_progress*100)}% elapsed - on track'

    # Scale by cost multiplier (more expensive = longer intervals)
    # Normalize: Sonnet (3x) is baseline, Opus-4 (15x) gets 5x longer, Opus-4.5 (5x) gets ~1.7x longer
    cost_scale = cost_multiplier / 3.0
    recommended = int(base_interval * cost_scale)

    # Clamp to bounds
    recommended = max(MIN_INTERVAL, min(MAX_INTERVAL, recommended))

    return {
        'recommended_interval': recommended,
        'reason': reason,
        'quota_status': quota_status,
        'cost_multiplier': cost_multiplier,
        'week_usage': week_usage,
        'week_progress_pct': int(week_progress * 100)
    }

if __name__ == '__main__':
    # Test the calculator
    import sys

    if len(sys.argv) > 1:
        claude_name = sys.argv[1]
    else:
        claude_name = "Sparkle-Orange"

    result = calculate_recommended_interval(claude_name)

    print(f"\n=== Interval Recommendation for {claude_name} ===")
    print(f"Recommended: {result['recommended_interval']}s ({result['recommended_interval']//60} minutes)")
    print(f"Reason: {result['reason']}")
    print(f"Quota Status: {result['quota_status']}")
    print(f"Cost Multiplier: {result['cost_multiplier']}x")
    print(f"Week Usage: {result['week_usage']}%")
    print(f"Week Progress: {result['week_progress_pct']}%")
