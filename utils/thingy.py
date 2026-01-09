import re
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

@dataclass
class UsageEntry:
    label: str
    percent_used: int
    reset_timestamp: Optional[datetime]

def parse_usage_text(text: str) -> list[dict]:
    """Parse Claude CLI usage output into structured data."""
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    
    results = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Skip noise lines
        if any(skip in line.lower() for skip in ['esc to cancel', 'extra usage not enabled', '/extra-usage']):
            i += 1
            continue
        
        # Check if this looks like a label (no progress bar chars, no "used", no "Resets")
        if '█' not in line and '% used' not in line and not line.startswith('Resets'):
            label = line
            percent_used = None
            reset_timestamp = None
            
            # Look ahead for percent and reset time
            for j in range(i + 1, min(i + 4, len(lines))):
                next_line = lines[j]
                
                # Extract percentage
                if '% used' in next_line:
                    match = re.search(r'(\d+)%\s*used', next_line)
                    if match:
                        percent_used = int(match.group(1))
                
                # Extract reset time
                elif next_line.startswith('Resets'):
                    reset_timestamp = parse_reset_time(next_line)
            
            if percent_used is not None:
                results.append({
                    'label': label,
                    'values': {
                        'percent_used': percent_used,
                        'reset_timestamp': reset_timestamp
                    }
                })
        
        i += 1
    
    return results

def parse_reset_time(reset_line: str) -> Optional[datetime]:
    """Parse reset time string into datetime."""
    # Extract the time part, ignoring timezone label
    match = re.search(r'Resets\s+(.+?)\s*\([^)]+\)', reset_line)
    if not match:
        return None
    
    time_str = match.group(1).strip()
    now = datetime.now()
    
    # Handle "10:59pm" format (today)
    time_only = re.match(r'^(\d{1,2}):(\d{2})(am|pm)$', time_str, re.IGNORECASE)
    if time_only:
        hour, minute, ampm = time_only.groups()
        hour = int(hour)
        minute = int(minute)
        if ampm.lower() == 'pm' and hour != 12:
            hour += 12
        elif ampm.lower() == 'am' and hour == 12:
            hour = 0
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # Handle "Jan 8, 7:59am" format
    date_time = re.match(r'^(\w+)\s+(\d{1,2}),?\s+(\d{1,2}):(\d{2})(am|pm)$', time_str, re.IGNORECASE)
    if date_time:
        month_str, day, hour, minute, ampm = date_time.groups()
        month_map = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                     'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
        month = month_map.get(month_str.lower()[:3], 1)
        day = int(day)
        hour = int(hour)
        minute = int(minute)
        if ampm.lower() == 'pm' and hour != 12:
            hour += 12
        elif ampm.lower() == 'am' and hour == 12:
            hour = 0
        year = now.year
        # Handle year rollover
        if month < now.month:
            year += 1
        return datetime(year, month, day, hour, minute)
    
    return None


if __name__ == '__main__':
    sample = """
 Current session
 ████▌                                              9% used
 Resets 10:59pm (Europe/London)
 Current week (all models)
 █████████████████████████████████████████████████▌ 99% used
 Resets Jan 8, 7:59am (Europe/London)
 Current week (Sonnet only)
 ████████████████████████████▌                      57% used
 Resets Jan 8, 7:59am (Europe/London)
 Extra usage
 Extra usage not enabled • /extra-usage to enable
 Esc to cancel
"""
    
    results = parse_usage_text(sample)
    for entry in results:
        print(entry)
