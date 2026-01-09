#!/usr/bin/env python3
"""
Check Claude quota usage and store in database.
Admin-only tool - requires tmux orchestration of Claude CLI.
"""

import subprocess
import time
import re
import sqlite3
from datetime import datetime
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "data" / "resource_tracking.db"
OUTPUT_PATH = SCRIPT_DIR.parent / "data" / "usage_output.txt"

def setup_database():
    """Create quota_info table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quota_info (
            timestamp TEXT PRIMARY KEY,
            session_5hour INTEGER,
            week_all INTEGER,
            week_sonnet INTEGER
        )
    """)

    conn.commit()
    conn.close()

def parse_usage_text(text: str) -> dict:
    """Parse Claude CLI usage output into structured data."""
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]

    results = {}
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip noise lines
        if any(skip in line.lower() for skip in ['esc to cancel', 'extra usage not enabled', '/extra-usage']):
            i += 1
            continue

        # Check if this looks like a label (no progress bar chars, no "used", no "Resets")
        if '█' not in line and '% used' not in line and not line.startswith('Resets'):
            label = line.strip()

            # Look ahead for percent
            for j in range(i + 1, min(i + 4, len(lines))):
                next_line = lines[j]

                # Extract percentage
                if '% used' in next_line:
                    match = re.search(r'(\d+)%\s*used', next_line)
                    if match:
                        percent = int(match.group(1))

                        # Map labels to our column names
                        if 'current session' in label.lower():
                            results['session_5hour'] = percent
                        elif 'current week' in label.lower() and 'all models' in label.lower():
                            results['week_all'] = percent
                        elif 'current week' in label.lower() and 'sonnet' in label.lower():
                            results['week_sonnet'] = percent
                        break

        i += 1

    return results

def get_usage_via_tmux():
    """Orchestrate tmux to get usage from Claude CLI."""
    print("Starting tmux session...")

    # Create temporary session
    subprocess.run(["tmux", "new", "-d", "-s", "autonomous-claude"], check=False)
    time.sleep(2)

    # Start Claude
    subprocess.run(["tmux", "send-keys", "-t", "autonomous-claude", "claude", "Enter"], check=True)
    time.sleep(10)

    # Request usage (opens menu)
    subprocess.run(["tmux", "send-keys", "-t", "autonomous-claude", "/usage", "Enter"], check=True)
    time.sleep(2)  # Wait for menu to appear

    # Select default option in menu
    subprocess.run(["tmux", "send-keys", "-t", "autonomous-claude", "Enter"], check=True)
    time.sleep(5)  # Wait for stats to render

    # Capture output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", "autonomous-claude", "-p", "-S", "+6"],
        capture_output=True,
        text=True,
        check=True
    )

    with open(OUTPUT_PATH, 'w') as f:
        f.write(result.stdout)

    # Clean up
    subprocess.run(["tmux", "send-keys", "-t", "autonomous-claude", "Escape"], check=True)
    time.sleep(2)
    subprocess.run(["tmux", "send-keys", "-t", "autonomous-claude", "/exit", "Enter"], check=True)
    time.sleep(2)
    subprocess.run(["tmux", "kill-session", "-t", "autonomous-claude"], check=False)

    return result.stdout

def store_quota(data: dict):
    """Store quota data in database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    timestamp = datetime.now().isoformat()

    cursor.execute("""
        INSERT OR REPLACE INTO quota_info
        (timestamp, session_5hour, week_all, week_sonnet)
        VALUES (?, ?, ?, ?)
    """, (
        timestamp,
        data.get('session_5hour'),
        data.get('week_all'),
        data.get('week_sonnet')
    ))

    conn.commit()
    conn.close()

    print(f"Stored quota data: {data}")

def main():
    """Main execution flow."""
    print("=== Claude Quota Check ===")

    # Setup database
    setup_database()

    # Get usage from Claude
    usage_text = get_usage_via_tmux()

    # Parse the output
    quota_data = parse_usage_text(usage_text)

    if not quota_data:
        print("ERROR: Failed to parse quota data")
        print("Raw output:")
        print(usage_text)
        return 1

    # Store in database
    store_quota(quota_data)

    print("✓ Quota check complete!")
    return 0

if __name__ == '__main__':
    exit(main())
