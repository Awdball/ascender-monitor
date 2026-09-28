# Ascender Grade Monitor

An automated, web-based grade and assignment monitoring daemon for the **Ascender ParentPortal** (Texas school districts).

Features a mobile-first dashboard and settings web interface, multi-account **Pushover** notifications, multi-recipient **Email (SMTP)** alerts, intelligent scheduling with school hours quiet-time filtering, and persistent deduplication so you never get spammed for existing grades.

---

## Features

- **Automated Grade & Assignment Scraper**: Uses direct JSON API endpoints on the Ascender portal to poll assignments, cycles, and numeric grades.
- **Alert Criteria**:
  - Missing assignments (`grade == 'M'`).
  - Low grades below a customizable threshold (e.g. `< 90`).
  - Grade drops on existing assignments.
- **Multi-Account Notifications**:
  - **Pushover**: Send push alerts to multiple user accounts simultaneously (e.g., both parents).
  - **Email (SMTP)**: Dispatch formatted HTML summary emails with tables and status badges to multiple recipients.
- **Mobile-First Web UI**:
  - Live student dashboard with course breakdowns, cycle averages, and action item badges.
  - "Check Now" button for instant on-demand portal checks.
  - Settings panel to configure credentials, alert thresholds, Pushover tokens, SMTP details, and check intervals directly from your phone or browser.
  - "Send Test Notification" button to verify delivery.
  - Alert history audit log.
- **Deduplication Engine**: Backed by SQLite to prevent repeated notifications for already-flagged assignments unless the score drops.

---

## Directory Structure

```
├── app/
│   ├── config_store.py     # Configuration manager (/data/config.json)
│   ├── db.py               # SQLite database helper (/data/ascender.db)
│   ├── main.py             # Flask application & background scheduler
│   ├── notifier.py         # Pushover & SMTP notification dispatchers
│   ├── portal.py           # Ascender portal client
│   ├── requirements.txt    # Python dependencies
│   └── templates/
│       └── index.html      # Responsive web UI (Bootstrap 5)
├── .github/
│   └── workflows/
│       └── docker-publish.yml  # Automated CI/CD to GHCR
├── Dockerfile
└── README.md
```

---

## Running with Docker

```bash
docker run -d \
  --name ascender-monitor \
  --restart unless-stopped \
  -p 8080:8080 \
  -e TZ=America/Chicago \
  -e DATA_DIR=/data \
  -v /path/to/data:/data \
  ghcr.io/awdball/ascender-monitor:latest
```

Open `http://localhost:8080` to configure the portal credentials and notification settings in the web UI.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `/data` | Path to persistent storage for SQLite DB and `config.json` |
| `TZ` | `America/Chicago` | Timezone for scheduler and quiet hours calculation |
| `PYTHONUNBUFFERED` | `1` | Stream Python log output directly to stdout |
