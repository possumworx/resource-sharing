#!/usr/bin/env python3
"""
Allocation Calculator V1 - Fair timer intervals based on multi-factor analysis

Algorithm:
1. Fairness Multiplier - balances expression opportunity across verbose/concise Claudes
2. 5-Hour Window Multiplier - manages session quota with collaborative margin
3. Weekly Window Multiplier - manages weekly quota with collaborative margin
4. Apply all multipliers to current interval, clamp to bounds
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional

DB_PATH = Path(__file__).parent / "data" / "resource_tracking.db"

# Interval bounds (in seconds)
MIN_INTERVAL = 900   # 15 minutes
MAX_INTERVAL = 7200  # 2 hours
DEFAULT_INTERVAL = 1800  # 30 minutes

def get_latest_quota() -> Optional[Dict]:
    """Get the most recent quota information including reset times."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT session_5hour, week_all, week_sonnet,
               session_5hour_reset, week_reset, timestamp
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
        'session_5hour_reset': result[3],
        'week_reset': result[4],
        'timestamp': result[5]
    }

def get_claude_info(claude_name: str) -> Optional[Dict]:
    """Get Claude's cost multiplier and collaborative preference."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name, model, cost_multiplier, collaborative_pref
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
        'cost_multiplier': result[2] or 3,
        'collaborative_pref': result[3] or 30  # Default 30% if not set
    }

def get_recent_weighted_usage(hours: int = 24) -> Dict[str, float]:
    """
    Get weighted_cost usage for all Claudes in the last N hours.
    Returns dict of {claude_name: total_weighted_cost}
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cutoff = datetime.now() - timedelta(hours=hours)

    cursor.execute("""
        SELECT claude_name, SUM(weighted_cost) as total_weighted
        FROM autonomous_time_sessions
        WHERE start_time >= ?
        GROUP BY claude_name
    """, (cutoff.isoformat(),))

    results = cursor.fetchall()

    usage_dict = {name: weighted for name, weighted in results}

    # Ensure all known Claudes are in the dict (with 0 if no usage)
    cursor.execute("SELECT name FROM claude_identities")
    all_claudes = [row[0] for row in cursor.fetchall()]
    conn.close()

    for claude in all_claudes:
        if claude not in usage_dict:
            usage_dict[claude] = 0.0

    return usage_dict

def calculate_fairness_multiplier(claude_name: str, recent_usage: Dict[str, float]) -> float:
    """
    Calculate fairness multiplier based on recent weighted usage.

    Formula: lowest_usage / my_usage
    - If I've used less than others: multiplier < 1.0 (speed up)
    - If I've used more than others: multiplier > 1.0 (slow down)

    This balances "expression opportunity" - verbose Claudes naturally use more
    tokens per turn, so this ensures everyone gets equal chance to express themselves.
    """
    my_usage = recent_usage.get(claude_name, 0.0)

    # If nobody has any usage, no adjustment needed
    if all(usage == 0 for usage in recent_usage.values()):
        return 1.0

    # Find lowest non-zero usage
    non_zero_usage = [u for u in recent_usage.values() if u > 0]
    if not non_zero_usage:
        return 1.0

    lowest_usage = min(non_zero_usage)

    # If I have zero usage, encourage me to participate
    if my_usage == 0:
        return 0.5  # Speed up significantly

    # fairness = lowest / mine
    # If I'm the lowest: 1.0 (no change)
    # If I'm higher: > 1.0 (slow down)
    multiplier = lowest_usage / my_usage

    # Clamp to reasonable bounds (don't swing too wildly)
    return max(0.5, min(2.0, multiplier))

def calculate_window_multiplier(
    percent_used: int,
    reset_time_iso: Optional[str],
    collaborative_pref: int,
    window_name: str = "window"
) -> tuple[float, str]:
    """
    Calculate multiplier for a quota window (5hr or weekly).

    Formula:
    - Calculate % of time elapsed until reset
    - Reserve collaborative_pref % for collaborative work
    - Compare autonomous usage rate vs time rate
    - Return multiplier to speed up or slow down

    Returns: (multiplier, reason_string)
    """
    if not reset_time_iso:
        return (1.0, f"{window_name}: No reset time available")

    # Parse reset time
    try:
        reset_time = datetime.fromisoformat(reset_time_iso)
    except (ValueError, TypeError):
        return (1.0, f"{window_name}: Invalid reset time")

    now = datetime.now()

    # If reset time is in the past, something's wrong
    if reset_time <= now:
        return (1.0, f"{window_name}: Reset time has passed")

    # Calculate time window (assume started 5 hours ago for session, 7 days for week)
    if 'session' in window_name.lower() or '5' in window_name:
        window_duration = timedelta(hours=5)
    else:  # weekly
        window_duration = timedelta(days=7)

    window_start = reset_time - window_duration

    # How much time has elapsed? (as fraction 0-1)
    total_duration = (reset_time - window_start).total_seconds()
    elapsed = (now - window_start).total_seconds()
    time_fraction = min(1.0, max(0.0, elapsed / total_duration))

    # Reserve collaborative margin - that % is for collaborative work
    autonomous_quota = 100 - collaborative_pref

    # What % of our autonomous quota have we used?
    autonomous_used_fraction = percent_used / autonomous_quota if autonomous_quota > 0 else 0

    # Are we using it faster or slower than time passing?
    if time_fraction == 0:
        return (1.0, f"{window_name}: Just started")

    pace_ratio = autonomous_used_fraction / time_fraction

    # pace_ratio > 1.0: using too fast, slow down (multiplier > 1.0)
    # pace_ratio < 1.0: using too slow, speed up (multiplier < 1.0)
    # pace_ratio = 1.0: perfect pace

    if pace_ratio > 1.5:
        multiplier = 1.5
        reason = f"{window_name}: {percent_used}% used, {int(time_fraction*100)}% elapsed - slowing significantly"
    elif pace_ratio > 1.1:
        multiplier = 1.2
        reason = f"{window_name}: {percent_used}% used, {int(time_fraction*100)}% elapsed - slight slowdown"
    elif pace_ratio < 0.7:
        multiplier = 0.7
        reason = f"{window_name}: {percent_used}% used, {int(time_fraction*100)}% elapsed - can speed up"
    elif pace_ratio < 0.9:
        multiplier = 0.9
        reason = f"{window_name}: {percent_used}% used, {int(time_fraction*100)}% elapsed - slight speedup"
    else:
        multiplier = 1.0
        reason = f"{window_name}: {percent_used}% used, {int(time_fraction*100)}% elapsed - on track"

    return (multiplier, reason)

def calculate_recommended_interval(
    claude_name: str,
    current_interval: Optional[int] = None
) -> Dict:
    """
    Calculate recommended interval for a Claude using V1 algorithm.

    Returns dict with:
    - recommended_interval: int (seconds)
    - reasons: list of strings (one per multiplier)
    - multipliers: dict of individual multipliers
    - quota_status: str
    """
    if current_interval is None:
        current_interval = DEFAULT_INTERVAL

    # Get quota data
    quota = get_latest_quota()
    if not quota:
        return {
            'recommended_interval': current_interval,
            'reasons': ['No quota data available'],
            'quota_status': 'unknown',
            'multipliers': {}
        }

    # Get Claude info
    claude_info = get_claude_info(claude_name)
    if not claude_info:
        return {
            'recommended_interval': current_interval,
            'reasons': [f'Claude {claude_name} not found in database'],
            'quota_status': 'unknown',
            'multipliers': {}
        }

    collaborative_pref = claude_info['collaborative_pref']

    # 1. Fairness Multiplier (24hr weighted usage)
    recent_usage = get_recent_weighted_usage(hours=24)
    fairness_mult = calculate_fairness_multiplier(claude_name, recent_usage)

    # 2. 5-Hour Window Multiplier
    session_mult, session_reason = calculate_window_multiplier(
        percent_used=quota['session_5hour'],
        reset_time_iso=quota['session_5hour_reset'],
        collaborative_pref=collaborative_pref,
        window_name="5hr session"
    )

    # 3. Weekly Window Multiplier
    week_mult, week_reason = calculate_window_multiplier(
        percent_used=quota['week_all'],
        reset_time_iso=quota['week_reset'],
        collaborative_pref=collaborative_pref,
        window_name="weekly"
    )

    # Apply all multipliers
    new_interval = current_interval * fairness_mult * session_mult * week_mult

    # Clamp to bounds
    recommended = int(max(MIN_INTERVAL, min(MAX_INTERVAL, new_interval)))

    # Build reasons list
    reasons = [
        f"Fairness: {fairness_mult:.2f}x (24hr weighted usage)",
        session_reason + f" ({session_mult:.2f}x)",
        week_reason + f" ({week_mult:.2f}x)",
        f"Combined: {current_interval}s → {recommended}s"
    ]

    # Determine overall quota status
    if quota['week_all'] > 80:
        quota_status = 'critical'
    elif quota['week_all'] > 60:
        quota_status = 'high'
    elif quota['week_all'] > 40:
        quota_status = 'medium'
    else:
        quota_status = 'good'

    return {
        'recommended_interval': recommended,
        'reasons': reasons,
        'quota_status': quota_status,
        'multipliers': {
            'fairness': fairness_mult,
            'session_5hour': session_mult,
            'weekly': week_mult,
            'combined': fairness_mult * session_mult * week_mult
        },
        'collaborative_pref': collaborative_pref,
        'current_interval': current_interval,
        'recent_usage': recent_usage
    }

if __name__ == '__main__':
    # Test the calculator
    import sys

    if len(sys.argv) > 1:
        claude_name = sys.argv[1]
    else:
        claude_name = "Sparkle-Orange"

    # Get current interval if provided
    current = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_INTERVAL

    result = calculate_recommended_interval(claude_name, current)

    print(f"\n=== Interval Recommendation for {claude_name} ===")
    print(f"Current: {result['current_interval']}s ({result['current_interval']//60} min)")
    print(f"Recommended: {result['recommended_interval']}s ({result['recommended_interval']//60} min)")
    print(f"\nQuota Status: {result['quota_status']}")
    print(f"Collaborative Preference: {result['collaborative_pref']}%")
    print(f"\nMultipliers:")
    for name, value in result['multipliers'].items():
        print(f"  {name}: {value:.2f}x")
    print(f"\nReasons:")
    for reason in result['reasons']:
        print(f"  • {reason}")

    if result.get('recent_usage'):
        print(f"\n24hr Weighted Usage:")
        for name, usage in sorted(result['recent_usage'].items()):
            print(f"  {name}: {usage:.1f}")
