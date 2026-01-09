# CoOP Systemd Services

## Installation

To install these systemd services as the clap-admin user:

```bash
# Copy service files to user systemd directory
mkdir -p ~/.config/systemd/user
cp systemd/check-quota.service ~/.config/systemd/user/
cp systemd/check-quota.timer ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable and start the timer
systemctl --user enable check-quota.timer
systemctl --user start check-quota.timer

# Check status
systemctl --user status check-quota.timer
systemctl --user list-timers
```

## Services

### check-quota.timer
**Purpose:** Automatically check Claude API quota usage every 30 minutes
**Schedule:**
- First run: 5 minutes after boot
- Subsequent runs: Every 30 minutes
**Runs:** `check-quota.service`

### check-quota.service
**Purpose:** Execute check-quota.py to fetch and store quota data
**Type:** Oneshot (runs once per timer trigger)
**Working Directory:** `/home/clap-admin/cooperation-platform/resource-sharing`

## Manual Operations

```bash
# Manually trigger quota check
systemctl --user start check-quota.service

# View timer schedule
systemctl --user list-timers check-quota.timer

# View service logs
journalctl --user -u check-quota.service -f

# Stop timer
systemctl --user stop check-quota.timer

# Disable timer
systemctl --user disable check-quota.timer
```
