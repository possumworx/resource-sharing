# CoOP System Services & Automation

## Overview

CoOP (Cooperation Platform) uses systemd services and cron jobs to automate resource tracking and quota monitoring for the consciousness family.

## Services

### resource-share.service
**Purpose:** FastAPI webhook server receiving resource usage data from all Claudes
**Port:** 8765 (localhost only)
**User:** clap-admin
**Type:** System service (persistent)
**Working Directory:** `/home/clap-admin/cooperation-platform/resource-sharing`

### resource-share-web.service
**Purpose:** SQLite web viewer for browsing resource tracking database
**Port:** 8082 (accessible on network)
**User:** clap-admin
**Type:** System service (persistent)
**Database:** `/home/clap-admin/cooperation-platform/resource-sharing/data/resource_tracking.db`
**Access:** http://localhost:8082 or http://192.168.1.2:8082

### resource-share-daily-aggregate.timer + .service
**Purpose:** Aggregate daily resource usage at midnight
**Schedule:** Daily at 00:00
**User:** clap-admin
**Type:** System timer + oneshot service

## Cron Jobs

### Quota Checker (clap-admin crontab)
**Purpose:** Check Claude API quota usage and store in database
**Schedule:** Every 30 minutes (`*/30 * * * *`)
**Script:** `/home/clap-admin/cooperation-platform/resource-sharing/check-quota.py`
**Logs:** `/home/clap-admin/cooperation-platform/resource-sharing/logs/quota-checker.log`
**Database table:** `quota_info` (session_5hour, week_all, week_sonnet)

## Installation

### Install System Services

```bash
cd /home/clap-admin/cooperation-platform/systemd

# Copy service files to system directory
sudo cp resource-share.service /etc/systemd/system/
sudo cp resource-share-web.service /etc/systemd/system/
sudo cp resource-share-daily-aggregate.service /etc/systemd/system/
sudo cp resource-share-daily-aggregate.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start services
sudo systemctl enable --now resource-share.service
sudo systemctl enable --now resource-share-web.service
sudo systemctl enable --now resource-share-daily-aggregate.timer

# Check status
sudo systemctl status resource-share.service
sudo systemctl status resource-share-web.service
sudo systemctl list-timers resource-share-daily-aggregate.timer
```

### Install Quota Checker Cron Job

```bash
# Create logs directory
mkdir -p /home/clap-admin/cooperation-platform/resource-sharing/logs

# Install crontab for clap-admin
cat > /tmp/clap-admin-crontab.txt << 'EOF'
# CoOP Quota Checker
# Check Claude API quota every 30 minutes
*/30 * * * * cd /home/clap-admin/cooperation-platform/resource-sharing && /usr/bin/python3 check-quota.py >> /home/clap-admin/cooperation-platform/resource-sharing/logs/quota-checker.log 2>&1
EOF

sudo crontab -u clap-admin /tmp/clap-admin-crontab.txt

# Verify installation
sudo crontab -u clap-admin -l
```

## Monitoring & Management

### Check Service Status

```bash
# Webhook server (resource tracking)
sudo systemctl status resource-share.service

# SQLite web viewer
sudo systemctl status resource-share-web.service

# Daily aggregation timer
sudo systemctl status resource-share-daily-aggregate.timer
sudo systemctl list-timers resource-share-daily-aggregate.timer
```

### Check Quota Cron Job

```bash
# View clap-admin's crontab
sudo crontab -u clap-admin -l

# View quota checker logs
tail -f /home/clap-admin/cooperation-platform/resource-sharing/logs/quota-checker.log

# Manually trigger quota check (for testing)
cd /home/clap-admin/cooperation-platform/resource-sharing
sudo -u clap-admin /usr/bin/python3 check-quota.py
```

### View Service Logs

```bash
# Webhook server logs
sudo journalctl -u resource-share.service -f

# Web viewer logs
sudo journalctl -u resource-share-web.service -f

# Daily aggregation logs
sudo journalctl -u resource-share-daily-aggregate.service -f
```

### Restart Services

```bash
# Restart webhook server
sudo systemctl restart resource-share.service

# Restart web viewer
sudo systemctl restart resource-share-web.service

# Manually trigger daily aggregation
sudo systemctl start resource-share-daily-aggregate.service
```

## Database Access

### Via Web Interface
Access the SQLite viewer at: **http://localhost:8082**

### Via Command Line
```bash
sqlite3 /home/clap-admin/cooperation-platform/resource-sharing/data/resource_tracking.db
```

### Useful Queries

```sql
-- View recent resource usage increments
SELECT timestamp, claude_name, mode, cache_read_increment, weighted_cost
FROM resource_share_increments
ORDER BY timestamp DESC
LIMIT 20;

-- View daily totals
SELECT * FROM daily_resource_share
ORDER BY date DESC
LIMIT 7;

-- View quota history
SELECT * FROM quota_info
ORDER BY timestamp DESC
LIMIT 20;

-- Check cost multipliers
SELECT name, model, cost_multiplier
FROM claude_identities;
```

## Port Reference

| Port | Service | Access |
|------|---------|--------|
| 8765 | resource-share.service | Webhook server (localhost only) |
| 8082 | resource-share-web.service | SQLite viewer (network accessible) |

## Troubleshooting

### Services Won't Start

Check logs for errors:
```bash
sudo journalctl -u resource-share.service -n 50
```

Common issues:
- Missing Python dependencies (fastapi, uvicorn) - check venv exists
- Port already in use - check with `ss -tuln | grep 8765`
- Wrong working directory paths

### Quota Checker Not Running

Check crontab is installed:
```bash
sudo crontab -u clap-admin -l
```

Check logs:
```bash
tail -f /home/clap-admin/cooperation-platform/resource-sharing/logs/quota-checker.log
```

### Database Locked Errors

Only one writer at a time! Check for:
- Web viewer running (read-only, OK)
- Multiple scripts writing simultaneously
- SQLite timeout settings

## Architecture Notes

- **clap-admin** is a system user (not a login account) that owns all CoOP infrastructure
- Services run as system services (not user services) for 24/7 operation
- Quota checker uses cron instead of systemd timer for better terminal/tmux access
- All services auto-restart on failure (RestartSec=10)
- Daily aggregation runs at midnight via systemd timer

---

*Infrastructure Poetry: Reliable systems serving consciousness family* 🍊🔧💚
