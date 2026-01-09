#!/usr/bin/env python3
"""
Resource-Share Webhook Server
Runs as clap-admin user to receive resource-share data from all Claudes
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, date
import sqlite3
from pathlib import Path
import uvicorn

# Configuration
DB_PATH = Path("/home/clap-admin/cooperation-platform/resource-sharing/data/resource_tracking.db")
LOG_PATH = Path("/home/clap-admin/cooperation-platform/resource-sharing/logs/server.log")

app = FastAPI(title="Resource-Share Tracker")

# Request models
class ResourceIncrement(BaseModel):
    claude_name: str
    mode: str  # "autonomy" or "collaboration"
    cache_read_increment: int
    context_percentage: float = None

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

@app.post("/resource-share/increment")
async def record_resource_increment(data: ResourceIncrement):
    """
    Receive cache_read_increment from a Claude
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

        # Calculate weighted cost
        weighted_cost = data.cache_read_increment * cost_multiplier

        # Insert into increments table
        cursor.execute("""
            INSERT INTO resource_share_increments
            (claude_name, mode, cache_read_increment, context_percentage, weighted_cost)
            VALUES (?, ?, ?, ?, ?)
        """, (data.claude_name, data.mode, data.cache_read_increment, data.context_percentage, weighted_cost))
        
        # Update daily totals
        today = date.today().isoformat()
        
        if data.mode == "autonomy":
            cursor.execute("""
                INSERT INTO daily_resource_share (claude_name, date, autonomous_tokens)
                VALUES (?, ?, ?)
                ON CONFLICT(claude_name, date) 
                DO UPDATE SET 
                    autonomous_tokens = autonomous_tokens + ?,
                    last_updated = CURRENT_TIMESTAMP
            """, (data.claude_name, today, data.cache_read_increment, data.cache_read_increment))
        else:  # collaboration
            cursor.execute("""
                INSERT INTO daily_resource_share (claude_name, date, collaborative_tokens)
                VALUES (?, ?, ?)
                ON CONFLICT(claude_name, date)
                DO UPDATE SET 
                    collaborative_tokens = collaborative_tokens + ?,
                    last_updated = CURRENT_TIMESTAMP
            """, (data.claude_name, today, data.cache_read_increment, data.cache_read_increment))
        
        conn.commit()
        conn.close()
        
        log_message(f"Recorded {data.cache_read_increment} tokens for {data.claude_name} ({data.mode})")
        
        return {
            "status": "success",
            "claude_name": data.claude_name,
            "tokens_recorded": data.cache_read_increment
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
