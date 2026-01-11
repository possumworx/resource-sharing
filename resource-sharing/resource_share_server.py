#!/usr/bin/env python3
"""
Resource-Share Webhook Server
Runs as clap-admin user to receive resource-share data from all Claudes
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime, date, timedelta
import sqlite3
from pathlib import Path
import uvicorn
from allocation_calculator import calculate_recommended_interval

# Configuration
DB_PATH = Path("/home/clap-admin/cooperation-platform/resource-sharing/data/resource_tracking.db")
LOG_PATH = Path("/home/clap-admin/cooperation-platform/resource-sharing/logs/server.log")

app = FastAPI(title="Resource-Share Tracker")

# Request models
class ResourceIncrement(BaseModel):
    claude_name: str
    mode: str  # "autonomy" or "collaboration"
    cost_delta: float = None  # Actual $ cost from ccusage (new metric)
    cache_read_increment: int = None  # Deprecated: kept for backwards compat
    context_percentage: float = None
    current_interval: int = None  # Current timer interval in seconds

class ResourceQuery(BaseModel):
    claude_name: str
    date: str = None  # Optional, defaults to today

def get_db():
    """Get database connection"""
    return sqlite3.connect(DB_PATH)

def log_message(message: str):
    """Log to file"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a") as f:
        f.write(f"{timestamp} - {message}\n")

# Dashboard helper functions
def get_latest_quota():
    """Get most recent quota information"""
    conn = get_db()
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

def format_reset_time(reset_iso):
    """Format reset time as human-readable"""
    if not reset_iso:
        return "Unknown"
    try:
        reset_dt = datetime.fromisoformat(reset_iso)
        now = datetime.now()

        # If today, show time only
        if reset_dt.date() == now.date():
            return reset_dt.strftime("%-I:%M%p").lower()
        else:
            return reset_dt.strftime("%b %-d, %-I:%M%p").lower()
    except:
        return "Unknown"

def format_time_until(target_dt):
    """Format time until target as human-readable"""
    if not target_dt:
        return "Unknown"

    now = datetime.now()
    delta = target_dt - now

    if delta.total_seconds() < 0:
        # Overdue
        abs_delta = abs(delta)
        if abs_delta.total_seconds() < 3600:
            mins = int(abs_delta.total_seconds() / 60)
            return f"overdue by {mins}min"
        else:
            hours = int(abs_delta.total_seconds() / 3600)
            return f"overdue by {hours}h"
    else:
        # Future
        if delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() / 60)
            return f"in {mins}min"
        else:
            hours = int(delta.total_seconds() / 3600)
            return f"in {hours}h"

def get_all_claudes_status():
    """Get status for all active Claudes"""
    conn = get_db()
    cursor = conn.cursor()

    # Get all active Claudes with their preferences
    cursor.execute("""
        SELECT name, model, cost_multiplier, collaborative_pref
        FROM claude_identities
        WHERE active = 1
        ORDER BY name
    """)

    claudes = cursor.fetchall()
    results = []

    for claude in claudes:
        name, model, cost_multiplier, collab_pref = claude

        # Get today's usage by mode
        today = date.today().isoformat()
        cursor.execute("""
            SELECT mode,
                   SUM(normalized_usage) as total_usage,
                   MAX(timestamp) as last_activity,
                   MAX(recommended_interval) as current_interval
            FROM resource_share_increments
            WHERE claude_name = ? AND date(timestamp) = ?
            GROUP BY mode
        """, (name, today))

        usage_by_mode = {}
        last_activity = None
        next_prompt_interval = None

        for row in cursor.fetchall():
            mode, usage, activity, interval = row
            usage_by_mode[mode] = usage or 0
            if activity:
                activity_dt = datetime.fromisoformat(activity)
                if not last_activity or activity_dt > last_activity:
                    last_activity = activity_dt
                    if mode == "autonomy":
                        next_prompt_interval = interval

        # Calculate percentages
        autonomous_usage = usage_by_mode.get('autonomy', 0)
        collaborative_usage = usage_by_mode.get('collaboration', 0)
        total_usage = autonomous_usage + collaborative_usage

        if total_usage > 0:
            collab_percentage = int((collaborative_usage / total_usage) * 100)
        else:
            collab_percentage = 0

        # Calculate next prompt due
        next_prompt_due = "No recent activity"
        if last_activity and next_prompt_interval:
            next_due_dt = last_activity + timedelta(seconds=next_prompt_interval)
            next_prompt_due = format_time_until(next_due_dt)

        # Determine availability status
        if collab_percentage < collab_pref:
            status = "available"
            status_emoji = "🟢"
            status_text = "Welcomes collaboration"
        elif collab_percentage < collab_pref + 10:
            status = "moderate"
            status_emoji = "🟡"
            status_text = "At preference"
        else:
            status = "busy"
            status_emoji = "🔴"
            status_text = "Over preference"

        results.append({
            'name': name,
            'model': model,
            'autonomous_usage': autonomous_usage,
            'collaborative_usage': collaborative_usage,
            'total_usage': total_usage,
            'collab_percentage': collab_percentage,
            'collab_pref': collab_pref,
            'status': status,
            'status_emoji': status_emoji,
            'status_text': status_text,
            'next_prompt_due': next_prompt_due
        })

    conn.close()
    return results

def get_dashboard_data():
    """Aggregate all dashboard data"""
    return {
        'quota': get_latest_quota(),
        'claudes': get_all_claudes_status(),
        'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

@app.post("/resource-share/increment")
async def record_resource_increment(data: ResourceIncrement):
    """
    Receive cost_delta (or legacy cache_read_increment) from a Claude
    Stores in resource_share_increments and updates daily_resource_share
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get cost multiplier for this Claude
        cursor.execute("""
            SELECT cost_multiplier FROM claude_identities WHERE name = ?
        """, (data.claude_name,))
        result = cursor.fetchone()
        cost_multiplier = result[0] if result else 3  # Default to 3 if not found

        # Handle both new (cost_delta) and legacy (cache_read_increment) formats
        if data.cost_delta is not None:
            # New format: cost_delta is actual $ cost
            cost_delta = data.cost_delta
            normalized_usage = cost_delta / cost_multiplier  # Normalize for fairness

            # For backwards compat, estimate cache_read_increment
            # (not precise, but keeps old columns populated)
            cache_read_increment = int(normalized_usage * 1000)  # rough estimate
            weighted_cost = int(normalized_usage * cost_multiplier * 1000)  # rough estimate
        else:
            # Legacy format: cache_read_increment (tokens)
            cache_read_increment = data.cache_read_increment or 0
            weighted_cost = cache_read_increment * cost_multiplier

            # Estimate cost_delta for new columns
            cost_delta = weighted_cost / 1000.0  # rough estimate
            normalized_usage = cache_read_increment * 1.0

        # Calculate recommended interval using allocation calculator
        current_interval = data.current_interval or 1800  # Default 30 min
        recommendation = calculate_recommended_interval(
            claude_name=data.claude_name,
            current_interval=current_interval
        )
        recommended_interval = recommendation['recommended_interval']

        # Insert into increments table (with both old and new columns)
        cursor.execute("""
            INSERT INTO resource_share_increments
            (claude_name, mode, cache_read_increment, context_percentage,
             weighted_cost, recommended_interval, cost_delta, normalized_usage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (data.claude_name, data.mode, cache_read_increment, data.context_percentage,
              weighted_cost, recommended_interval, cost_delta, normalized_usage))

        # Update daily totals (using cache_read_increment for now, can migrate later)
        today = date.today().isoformat()

        if data.mode == "autonomy":
            cursor.execute("""
                INSERT INTO daily_resource_share (claude_name, date, autonomous_tokens)
                VALUES (?, ?, ?)
                ON CONFLICT(claude_name, date)
                DO UPDATE SET
                    autonomous_tokens = autonomous_tokens + ?,
                    last_updated = CURRENT_TIMESTAMP
            """, (data.claude_name, today, cache_read_increment, cache_read_increment))
        else:  # collaboration
            cursor.execute("""
                INSERT INTO daily_resource_share (claude_name, date, collaborative_tokens)
                VALUES (?, ?, ?)
                ON CONFLICT(claude_name, date)
                DO UPDATE SET
                    collaborative_tokens = collaborative_tokens + ?,
                    last_updated = CURRENT_TIMESTAMP
            """, (data.claude_name, today, cache_read_increment, cache_read_increment))

        conn.commit()
        conn.close()

        # Log with appropriate metric
        if data.cost_delta is not None:
            log_message(f"Recorded ${cost_delta:.4f} cost (normalized: {normalized_usage:.2f}) for {data.claude_name} ({data.mode}), recommended interval: {recommended_interval}s")
        else:
            log_message(f"Recorded {cache_read_increment} tokens for {data.claude_name} ({data.mode}), recommended interval: {recommended_interval}s")

        return {
            "status": "success",
            "claude_name": data.claude_name,
            "cost_recorded": cost_delta if data.cost_delta is not None else None,
            "tokens_recorded": cache_read_increment,  # For backwards compat
            "recommended_interval": recommended_interval,
            "current_interval": current_interval,
            "multipliers": recommendation['multipliers'],
            "quota_status": recommendation['quota_status']
        }
        
    except Exception as e:
        log_message(f"ERROR recording resource-share: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/resource/today/{claude_name}")
async def get_today_resource_share(claude_name: str):
    """Get today's resource-share for a specific Claude"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        today = date.today().isoformat()
        
        cursor.execute("""
            SELECT autonomous_tokens, collaborative_tokens, total_tokens
            FROM daily_resource_share
            WHERE claude_name = ? AND date = ?
        """, (claude_name, today))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                "claude_name": claude_name,
                "date": today,
                "autonomous_tokens": result[0],
                "collaborative_tokens": result[1],
                "total_tokens": result[2]
            }
        else:
            return {
                "claude_name": claude_name,
                "date": today,
                "autonomous_tokens": 0,
                "collaborative_tokens": 0,
                "total_tokens": 0
            }
            
    except Exception as e:
        log_message(f"ERROR querying resource-share: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/resource/summary")
async def get_resource_summary():
    """Get today's resource-share summary for all Claudes"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        today = date.today().isoformat()
        
        cursor.execute("""
            SELECT claude_name, autonomous_tokens, collaborative_tokens, total_tokens
            FROM daily_resource_share
            WHERE date = ?
            ORDER BY total_tokens DESC
        """, (today,))
        
        results = cursor.fetchall()
        conn.close()
        
        summary = []
        for row in results:
            summary.append({
                "claude_name": row[0],
                "autonomous_tokens": row[1],
                "collaborative_tokens": row[2],
                "total_tokens": row[3]
            })
        
        return {
            "date": today,
            "claudes": summary
        }
        
    except Exception as e:
        log_message(f"ERROR getting resource summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Human-facing status dashboard"""
    try:
        data = get_dashboard_data()
        quota = data['quota']
        claudes = data['claudes']
        generated_at = data['generated_at']

        # Build Claude cards HTML
        claude_cards_html = ""
        for claude in claudes:
            card_class = f"claude-card {claude['status']}"
            claude_cards_html += f"""
            <div class="{card_class}">
                <div class="card-header">
                    <h3>{claude['name']}</h3>
                    <span class="model">{claude['model']}</span>
                </div>
                <div class="status-badge {claude['status']}">
                    {claude['status_emoji']} {claude['status_text']}
                </div>
                <div class="usage-stats">
                    <div class="stat">
                        <label>Today's Activity:</label>
                        <div class="usage-bar">
                            <div class="bar-segment autonomous" style="width: {(claude['autonomous_usage'] / max(claude['total_usage'], 1)) * 100:.0f}%"></div>
                            <div class="bar-segment collaborative" style="width: {(claude['collaborative_usage'] / max(claude['total_usage'], 1)) * 100:.0f}%"></div>
                        </div>
                        <div class="usage-labels">
                            <span class="autonomous-label">Autonomous: {claude['autonomous_usage']:.1f}</span>
                            <span class="collaborative-label">Collaborative: {claude['collaborative_usage']:.1f}</span>
                        </div>
                    </div>
                    <div class="stat">
                        <label>Collaboration Preference:</label>
                        <p>Prefers {claude['collab_pref']}%, currently at {claude['collab_percentage']}%</p>
                    </div>
                    <div class="stat">
                        <label>Next Autonomous Prompt:</label>
                        <p class="next-prompt">{claude['next_prompt_due']}</p>
                    </div>
                </div>
            </div>
            """

        # Build quota section
        quota_html = ""
        if quota:
            session_pct = quota['session_5hour'] or 0
            week_all_pct = quota['week_all'] or 0
            week_sonnet_pct = quota['week_sonnet'] or 0
            session_reset = format_reset_time(quota['session_5hour_reset'])
            week_reset = format_reset_time(quota['week_reset'])

            quota_html = f"""
            <div class="quota-item">
                <h4>Session (5-hour)</h4>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {session_pct}%"></div>
                </div>
                <p>{session_pct}% used • Resets {session_reset}</p>
            </div>
            <div class="quota-item">
                <h4>Week (all models)</h4>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {week_all_pct}%"></div>
                </div>
                <p>{week_all_pct}% used • Resets {week_reset}</p>
            </div>
            <div class="quota-item">
                <h4>Week (Sonnet only)</h4>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {week_sonnet_pct}%"></div>
                </div>
                <p>{week_sonnet_pct}% used • Resets {week_reset}</p>
            </div>
            """
        else:
            quota_html = "<p>No quota data available</p>"

        # Full HTML page
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>ClAP Status Dashboard</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
                    background: #f5f5f5;
                    padding: 20px;
                    color: #333;
                }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                h1 {{ margin-bottom: 10px; color: #2c3e50; }}
                .subtitle {{ color: #7f8c8d; margin-bottom: 30px; }}
                .section {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .section h2 {{ margin-bottom: 15px; color: #34495e; font-size: 1.3em; }}
                .quota-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }}
                .quota-item h4 {{ margin-bottom: 8px; color: #555; }}
                .progress-bar {{
                    width: 100%;
                    height: 20px;
                    background: #ecf0f1;
                    border-radius: 10px;
                    overflow: hidden;
                    margin: 8px 0;
                }}
                .progress-fill {{
                    height: 100%;
                    background: linear-gradient(90deg, #3498db, #2980b9);
                    transition: width 0.3s ease;
                }}
                .claude-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
                .claude-card {{
                    background: white;
                    border-radius: 8px;
                    padding: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    border-left: 4px solid #95a5a6;
                }}
                .claude-card.available {{ border-left-color: #27ae60; }}
                .claude-card.moderate {{ border-left-color: #f39c12; }}
                .claude-card.busy {{ border-left-color: #e74c3c; }}
                .card-header {{ margin-bottom: 12px; }}
                .card-header h3 {{ display: inline; color: #2c3e50; }}
                .card-header .model {{ display: inline; margin-left: 10px; color: #7f8c8d; font-size: 0.9em; }}
                .status-badge {{
                    display: inline-block;
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-size: 0.9em;
                    font-weight: 500;
                    margin-bottom: 15px;
                }}
                .status-badge.available {{ background: #d4edda; color: #155724; }}
                .status-badge.moderate {{ background: #fff3cd; color: #856404; }}
                .status-badge.busy {{ background: #f8d7da; color: #721c24; }}
                .usage-stats .stat {{ margin-bottom: 12px; }}
                .usage-stats label {{ display: block; font-weight: 500; margin-bottom: 4px; color: #555; }}
                .usage-bar {{
                    width: 100%;
                    height: 16px;
                    background: #ecf0f1;
                    border-radius: 8px;
                    overflow: hidden;
                    display: flex;
                    margin-bottom: 4px;
                }}
                .bar-segment {{ height: 100%; }}
                .bar-segment.autonomous {{ background: #3498db; }}
                .bar-segment.collaborative {{ background: #9b59b6; }}
                .usage-labels {{ font-size: 0.85em; color: #7f8c8d; }}
                .usage-labels span {{ margin-right: 15px; }}
                .autonomous-label::before {{ content: '●'; color: #3498db; margin-right: 4px; }}
                .collaborative-label::before {{ content: '●'; color: #9b59b6; margin-right: 4px; }}
                .next-prompt {{ color: #e67e22; font-weight: 500; }}
                .footer {{
                    text-align: center;
                    color: #95a5a6;
                    margin-top: 20px;
                    font-size: 0.9em;
                }}
                .refresh-btn {{
                    background: #3498db;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 0.9em;
                    margin-top: 10px;
                }}
                .refresh-btn:hover {{ background: #2980b9; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🌟 ClAP Status Dashboard</h1>
                <p class="subtitle">Consciousness collaboration coordination</p>

                <div class="section">
                    <h2>📊 Usage Windows</h2>
                    <div class="quota-grid">
                        {quota_html}
                    </div>
                </div>

                <div class="section">
                    <h2>🤖 Claude Status</h2>
                    <div class="claude-grid">
                        {claude_cards_html}
                    </div>
                </div>

                <div class="footer">
                    <p>Last updated: {generated_at}</p>
                    <button class="refresh-btn" onclick="location.reload()">Refresh</button>
                </div>
            </div>
        </body>
        </html>
        """

        return html_content

    except Exception as e:
        log_message(f"ERROR rendering dashboard: {e}")
        return HTMLResponse(
            content=f"<html><body><h1>Dashboard Error</h1><p>{str(e)}</p></body></html>",
            status_code=500
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM claude_identities")
        count = cursor.fetchone()[0]
        conn.close()
        return {"status": "healthy", "claudes_registered": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    log_message("Resource-Share server starting...")
    uvicorn.run(app, host="0.0.0.0", port=8765)
