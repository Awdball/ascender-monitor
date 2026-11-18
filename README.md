# 📚 ascender-monitor

**An automated, push-notification grade monitor for the Ascender Parent Portal.**

ascender-monitor sits on top of the [Ascender](https://texas.ascender.com) Student/Parent Portal (Texas school districts), logs in with your Parent Portal credentials, scans every assignment for every student on your account, and sends **instant Pushover / email alerts the moment a grade matters** — a new failing grade, a missing assignment, a grade that drops, or one that improves. A small Flask web app gives you a live dashboard, a settings panel, an alert history, and a JSON API.

```bash
# Runs as a single, stateless container — all state lives in /data
docker run -d --name ascender-monitor \
  -p 8080:8080 -v ascender-data:/data \
  ghcr.io/awdball/ascender-monitor:1.2.0
```

---

## Table of Contents

- [What it does](#what-it-does)
- [What you get notified for](#what-you-get-notified-for)
- [What the notifications look like](#what-the-notifications-look-like)
- [How it works under the hood](#how-it-works-under-the-hood)
- ["Why did I stop getting alerts?" (alert-state semantics)](#why-did-i-stop-getting-alerts-alert-state-semantics)
- [Schedule & quiet hours](#schedule--quiet-hours)
- [Quick start](#quick-start)
- [Configuration reference](#configuration-reference)
- [Web dashboard](#web-dashboard)
- [JSON API](#json-api)
- [Persistence, privacy & security](#persistence-privacy--security)
- [Troubleshooting](#troubleshooting)
- [Limitations & porting notes](#limitations--porting-notes)
- [Project layout](#project-layout)
- [Releasing](#releasing)

---

## What it does

- **Automatic, no-touch grade monitoring.** A background scheduler logs in to the Parent Portal every *N* minutes (default: 60) during school hours on weekdays, and reads every course, every assignment, and every grade for **every student** on your Parent account.
- **Smart alerting, not spam.** The first time an assignment that fails (below your threshold) or is marked missing (`M`) is *seen*, you get a push. When a grade **changes** — turned in, raised, lowered, or turning missing — you get another push. Assignments you already know about do **not** re-alarm on every check (see [alert-state semantics](#why-did-i-stop-getting-alerts-alert-state-semantics)).
- **Push + email, to two people.** Up to two Pushover recipients and two e-mail recipients per alert (e.g., both parents). Delivery status and any provider errors are recorded per alert so you can audit them in the dashboard.
- **Dashboard.** A browser UI with per-student course cards, live averages, the list of flagged/updated assignments, full alert history, a "Check Now" button, a settings panel, and a "Send Test Notification" button.
- **JSON API** for automation (`/api/status`, `/api/data`, `/api/check-now`, …).
- **Zero external dependencies** — no database server, no broker. Configuration in one JSON file, grade/alert history in one SQLite file. Both live on a single volume (`/data`).

It is intentionally boring on purpose: one container, one thread doing the work, one volume.

## What you get notified for

| Alert type | Fires when | Toggle |
|---|---|---|
| ⚠️ **MISSING** | An assignment is new and graded `M`, **or** a previously graded assignment turns missing | "Alert on Missing Assignments" |
| 📉 **LOW_GRADE** | A new assignment is graded below your threshold (default 90%, configurable 0–100) | — (threshold setting) |
| 📉 **GRADE_DROP** | The grade on a known assignment changes to a *lower* number | "Alert if an existing grade drops lower" |
| ✨ **GRADE_IMPROVED** | The grade on a known assignment goes up | "Alert on Grade Updates & Turn-Ins" |
| 📝 **TURNED_IN** | An assignment that was `M` gets a real grade | "Alert on Grade Updates & Turn-Ins" |
| 🔄 **GRADE_UPDATED** | A known assignment's grade changes in a non-numeric way (e.g. letter-grade edits) | "Alert on Grade Updates & Turn-Ins" |

Priority: missing and failing-grade alerts are pushed at Pushover **High** priority; everything else at Normal. Pushes deep-link to your dashboard.

## What the notifications look like

Examples below use the exact message templates the app sends. *(Sample students/grades are fictional.)*

### Pushover

**New failing grade** — title: `📉 Low Grade Alert: Alex Johnson (74%)`

```
📉 LOW GRADE ALERT
Student: Alex Johnson
Course: Algebra I
Assignment: Quadratic Equations Quiz
Grade: 74% (11/05/26)
Due Date: 11/07/26
```

**New missing assignment (High priority)** — title: `⚠️ Missing Assignment: Alex Johnson`

```
⚠️ MISSING ASSIGNMENT
Student: Alex Johnson
Course: Algebra I
Assignment: Project #2 — Cell Analogy
Due Date: 11/20/26
Status: MISSING
```

**Grade drops** — title: `📉 Grade Update (Drop): Alex Johnson (88% ➔ 76%)`

```
🔄 Grade Transition
Student: Alex Johnson
Course: Algebra I
Assignment: Unit 3 Test
Grade: 88% (10/21/26) ➔ 76% (11/04/26)
Due Date: 11/04/26
```

**Grade improves** — title: `✨ Grade Update (Improved): Alex Johnson (70% ➔ 72%)`

```
🔄 Grade Transition
Student: Alex Johnson
Course: Algebra I
Assignment: Unit 3 Test
Grade: 70% (10/28/26) ➔ 72% (11/12/26)
Due Date: 11/12/26
```

**Missing work turned in** — title: `📝 Grade Update (Turned In): Alex Johnson (81%)`

```
🔄 Grade Transition
Student: Alex Johnson
Course: Algebra I
Assignment: Project #2 — Cell Analogy
Grade: M ➔ 81% (11/18/26)
Due Date: 11/18/26
```

Notes:
- If the teacher leaves a comment on the assignment, it appears as a final `Note: …` line.
- Every push includes a deep link (URL action) back to your dashboard.
- If **both** Pushover and e-mail are enabled, both fire per alert, and each recipient (up to 2 per channel) gets their own copy.

### E-mail

The e-mail channel renders the same content as an HTML message with a color-coded status badge (red for LOW GRADE / MISSING, purple for updates), a detail table (Student / Course / Assignment / Grade / Due Date / Status), and a "Open Grade Dashboard" button.

- New low grade → subject: `📉 Low Grade Alert: Alex Johnson (74%) — Algebra I`
- New missing → subject: `⚠️ Missing Assignment: Alex Johnson — Algebra I`, body: *A required assignment is currently missing.*
- Turn-in → subject: `📝 Assignment Turned In: Alex Johnson — Algebra I`, body: *The previously missing "Project #2 — Cell Analogy" was just turned in and graded: 81%.*

## How it works under the hood

```
                         ┌──────────────────────────────────────────────┐
                         │           ascender-monitor pod              │
                         │                                              │
  every N min            │  Scheduler thread ──┐                        │
  (7:00–18:00, Mon–Fri)  │                    ▼                        │
                         │              Portal client ──────────┐       │
  Ascender ParentPortal  │        login → fetch courses →        │      │
  (district portal) ─────┼───── parse assignments + grades       │      │
                         │                    │                  │      │
                         │                    ▼                  │      │
  Pushover / SMTP ◀──────┼── Notifier ◀── Grade diff engine      │      │
  (up to 2 recipients    │   (Pushover +    (SQLite: last-seen   │      │
   per channel)          │    HTML e-mail)  grades, alerts)   ◀──┘      │
                         │                                              │
  browser ───────────────┼── Flask web app (gunicorn, 1 worker)        │
                         │   / (dashboard)  /api/* (JSON)   "Check Now"│
                         └──────────────────────────────────────────────┘
                            │ volume: /data
                 config.json + ascender.db  (SQLite)
```

Component by component:

1. **Scheduler (`app/scheduler.py`)** — daemon thread. First check on startup, then every `check_interval_minutes`. Gated by `school_hours_only` (local 7:00–18:00) and `weekdays_only`. A manual `POST /api/check-now` bypasses the gate.
2. **Portal client (`app/portal.py`)** — logs in with the District ID + username/password, fetches each course's gradebook, and normalizes assignments to `(student, course, assignment, grade, due date)`. Grades come as numbers (`88`, `74`), letter grades (`B-`), or `M` (missing). On login failure it backs off **5 minutes** to stay polite and avoid portal lockout.
3. **Grade diff engine (`app/db.py`)** — SQLite keeps the last-seen grade per `(student, course, assignment)` (`assignments` table). On every check the current portal state is diffed against that store and classified into one of the alert types above, respecting the toggle settings. Every candidate alert is written to the `alerts` table with per-channel dispatch status (`SENT` / `SKIP_NO_RECIPIENTS` / `FAILED` + provider error), so you have a complete, auditable delivery log.
4. **Notifier (`app/notifier.py`)** — sends Pushover (`api.pushover.net`) and/or HTML SMTP, fans out to up to two recipients per channel, records results. A dedicated test path exists for validating credentials without a real grade event.
5. **Web app (`app/main.py`)** — Flask + gunicorn on port 8080. `GET /` serves the dashboard (single-page template, vanilla JS), and the JSON API below powers both it and operators.

There are no queues, workers, or external services: one process, one thread doing the periodic work, one file-backed database.

## Why did I stop getting alerts? (alert-state semantics)

This is the #1 "is it broken?" question — **and usually the answer is: no, it's working.**

The app intentionally avoids re-alerting on every check. Concretely:

- An assignment that fails or is missing **alerts the first time the app sees it in that state**.
- After that, it alerts **again only when the recorded grade value for that assignment changes** — turned in (M → number), raised, lowered, or turning missing.
- A homework assignment that stays at the same failing grade across five consecutive checks will produce **one** notification, not five.

So "no notifications all week" most often means: no new work was assigned, nothing already-seen got turned in, and no grades changed. You can verify in seconds without reading pod logs:

```bash
# what the engine recorded on the last run (status, summary, next check)
curl -s http://ascender-monitor.default.svc:8080/api/status
# e.g. → {"last_check_status": "SUCCESS",
#         "last_check_summary": "Checked 2 student(s), 281 assignments. Alerts sent: 0",
#         "next_check_time": "2026-11-16 2:15 PM"}

# full audit trail of every alert + per-channel delivery outcome + provider errors
curl -s http://ascender-monitor.default.svc:8080/api/data | jq .recent_alerts

# prove the notification pipeline end-to-end right now
curl -s -X POST http://ascender-monitor.default.svc:8080/api/test-notification
# → {"status":"success","detail":"Sent to 2 recipient(s)"}
```

If `recent_alerts` shows `SENT` to your channels but you never saw a push, the problem is on the device/relay side (Pushover app, device online state) — not the monitor.

## Schedule & quiet hours

| Setting | Default | Effect |
|---|---|---|
| `check_interval_minutes` | 60 | Period between automatic checks |
| `school_hours_only` | true | Only check between 07:00 and 18:00 *local time* |
| `weekdays_only` | true | Only check Monday–Friday |

Local time is the container's `TZ` (the default image ships `TZ=America/Chicago`). With the defaults, the app is silent on weekends and outside the school day — which also matches when the portal actually posts grades. `POST /api/check-now` always runs immediately, regardless of settings.

## Quick start

### Docker

```bash
docker run -d --name ascender-monitor \
  -p 8080:8080 \
  -v ascender-data:/data \
  ghcr.io/awdball/ascender-monitor:1.2.0

# then open http://localhost:8080, fill in the settings panel
# (district id + credentials + Pushover tokens) and hit "Save Settings"
```

All credentials are stored in the container (on the `ascender-data` volume) — **no environment variables required at runtime**.

### Kubernetes (Flux/GitOps)

Stateless pod + one PVC + Service + Ingress (in this deployment, fronted by an auth-gating reverse proxy at `grades.*`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ascender-monitor
  labels: { app: ascender-monitor }
spec:
  replicas: 1
  strategy: { type: Recreate }        # single writer to /data
  selector: { matchLabels: { app: ascender-monitor } }
  template:
    metadata: { labels: { app: ascender-monitor } }
    spec:
      containers:
        - name: ascender-monitor
          image: ghcr.io/awdball/ascender-monitor:1.2.0   # digest-pinned in production
          ports: [{ containerPort: 8080, name: http }]
          env: [{ name: TZ, value: America/Chicago }]
          volumeMounts:
            - { name: data, mountPath: /data }
          resources:
            requests: { cpu: 10m, memory: 50Mi }
            limits:   { cpu: 200m, memory: 300Mi }
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: ascender-monitor-data }
```

```yaml
apiVersion: v1
kind: Service
metadata: { name: ascender-monitor }
spec:
  selector: { app: ascender-monitor }
  ports: [{ name: http, port: 8080, targetPort: 8080 }]
```

```yaml
kind: Ingress
metadata:
  name: ascender-monitor
  annotations:
    ingress.traefik.ingress.kubernetes.io/auth-forward: "true"     # put an auth gate in front
spec:
  rules:
    - host: grades.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: ascender-monitor, port: { number: 8080 } } }
```

### First-run checklist

1. Create a **Pushover app** (pushover.net/apps) → copy the Application token.
2. Get your **user key** (pushover.net/user) — one per recipient (up to two).
3. Open the dashboard (`:8080`), set **District ID**, **Username**, **Password** (your Parent Portal login), set the threshold, paste tokens, **Save Settings**.
4. Hit **"Send Test Notification"** → expect a push on each device.
5. Hit **"Check Now"** → watch the status banner, per-student cards, and the alert list populate.

## Configuration reference

Stored at `/data/config.json` (mode `600`). Every field is editable from the settings panel; `GET /api/config` returns a **credential-free** view; `POST /api/save-config` accepts the raw object.

```jsonc
{
  // ── Alert rules ────────────────────────────────────────────
  "min_grade": 90,                    // 0–100; alerts fire on new grades below this
  "alert_on_new_only": true,          // anti-spam: notify when first seen / on grade change
  "alert_on_missing": true,           // alert on grade "M"
  "alert_on_updated": true,           // alert on turn-ins, improvements, updated grades
  "alert_on_grade_drop": true,        // alert when an existing grade gets lower

  // ── Pushover (one app, up to two user keys) ────────────────
  "pushover": {
    "enabled": true,
    "app_token": "ap...",             // Application token (create at pushover.net/apps)
    "user_keys": ["uu...", "uu..."]   // up to 2 user tokens
  },

  // ── E-mail (optional second channel) ───────────────────────
  "email": {
    "enabled": false,
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_username": "you@example.com",
    "smtp_password": "app-password",  // app token / app password
    "use_tls": true,                  // STARTTLS
    "from_address": "you@example.com",
    "to_addresses": ["parent1@example.com", "parent2@example.com"]
  },

  // ── Portal credentials ─────────────────────────────────────
  "ascender": {
    "district_id": "0XXXXXX",         // your school district's portal id
    "username": "parent123",
    "password": "••••••••"
  },

  // ── Scheduling ─────────────────────────────────────────────
  "schedule": {
    "check_interval_minutes": 60,
    "school_hours_only": true,        // Mon–Fri, 07:00–18:00 local
    "weekdays_only": true
  }
}
```

## Web dashboard

- **Status banner** — result of the last check (`SUCCESS` / `ERROR`), the check summary ("N students, M assignments. Alerts sent: K"), last / next check times, and a live dashboard version badge.
- **"Check Now" button** — forces an immediate check (bypasses schedule gates).
- **Per-student cards** — course list with averages; **flagged** assignments (new failures / missing) and recently **updated** assignments are listed under each student.
- **Alert history** — every alert ever fired, with timestamp, type, assignment, grade, and per-channel delivery status (SENT / FAILED with the provider's error message). Individually **confirm** stale alerts or **Clear all confirmed**.
- **Settings panel** — all of the configuration reference above, plus **"Send Test Notification"** to validate Pushover/e-mail credentials on demand.

The page polls `/api/data` automatically (every ~5 s while a check is running, then every ~30 s), so the UI converges on the latest state without manual refresh.

## JSON API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Web dashboard (HTML) |
| `GET` | `/api/config` | Current config — **credentials stripped** |
| `GET` | `/api/data` | Dashboard payload: last check, students/courses/averages, flagged & updated lists, recent alerts w/ delivery status |
| `POST` | `/api/check-now` | Trigger a check now (`{"force": true}` to bypass schedule gates) |
| `POST` | `/api/save-config` | Persist a raw config object (see reference above) |
| `POST` | `/api/test-notification` | Send a real test alert through Pushover/e-mail; returns per-channel status + provider errors |
| `DELETE` | `/api/alerts` | Remove confirmed alert rows (`{"confirmed": [1, 2, 3]}`) |

Example — operator health check from inside the cluster, no `kubectl exec` needed:

```bash
curl -s http://ascender-monitor.default.svc.cluster.local:8080/api/status
```

## Persistence, privacy & security

- **One volume (`/data`), two files**: `config.json` (settings incl. credentials, created `600`) and `ascender.db` (SQLite: `assignments` last-seen grades, `alerts` history, `checked_courses`).
- **No PII leaves the box except to Pushover and your SMTP server**, and only assignment/grade lines triggered by your own rules.
- **Credentials at rest** are plain files in the volume — keep the PVC unencrypted-by-default, or add encryption-at-rest to your storage class. Rotate Portal credentials via the settings panel if they leak; nothing else is needed.
- **The web app has no built-in authentication.** In this deployment it sits behind an auth-gating reverse proxy (`grades.*`). If you expose it beyond a private network, put an auth proxy (Authelia, Traefik forward-auth, Tailscale Funnel auth, …) in front — do not rely on obscurity.
- The app never brute-forces the portal: a failed login pauses for 5 minutes.

## Troubleshooting

| Symptom | Likely cause / action |
|---|---|
| No notifications "for a while" | **Normal** dedup behavior — see [alert-state semantics](#why-did-i-stop-getting-alerts-alert-state-semantics). Confirm with `/api/status` + `/api/data`. |
| `last_check_status: ERROR — Login failed: …` | Portal credentials rotated/locked, or portal outage. Update District ID/username/password in settings. The app backs off 5 min automatically. |
| `Unable to parse course page` / `No assignments found for course …` | Portal markup changed upstream. Check the portal in a browser; re-run "Check Now" after portal fixes. |
| Test notification → `FAILED` with Pushover "Invalid token" / user-key error | Wrong application token, or the *user* key is for a different app. Re-paste both; test again. |
| Test notification → `SKIP_NO_RECIPIENTS` (e-mail) | Channel enabled but `to_addresses` empty. |
| Pushes used to arrive, now don't (delivery shows `SENT`) | Device-side: Pushover app offline, notifications muted, or relay outage. The monitor's log says `SENT` — delivery was accepted by Pushover. |
| Dashboard slow to update | It polls automatically; if a check is running it polls faster (~5 s). Force one with **Check Now**. |
| Wiping `/data` | Factory reset — wipes alert history **and** last-seen grade state (fresh eyes on everything next check). |

## Limitations & porting notes

- **Portal target.** The client is written for the Ascender *Texas* portal instance (`portals11.ascendertx.com`) with the login flow it provides. Porting to a different Ascender instance (or another LMS) means updating the endpoints/selectors in `app/portal.py`.
- **One parent account.** It monitors every student on that account. There's no support for multiple independent parent logins in one instance — run a second container with a second volume if you need that.
- **No built-in auth / rate limiting** on the web app (by design; see security notes).
- **Unofficial integration.** This is a scraping-grade client against a commercial LMS portal. The portal can change at any time; check your district's ToS on third-party access. The app behaves politely (one login per check, 5-minute backoff on failure).
- **Timezone** comes from the `TZ` env var; the default image uses `America/Chicago`.
- **Email requires TLS-capable SMTP** (587 + STARTTLS is the recommended setup).
- No database migrations framework — the SQLite schema is created on first boot and is intentionally small.

## Project layout

```
ascender-monitor/
├── app/
│   ├── main.py           # Flask app, routes, JSON API, wiring
│   ├── scheduler.py      # background grade-check loop (school-hours aware)
│   ├── portal.py         # Ascender Parent Portal client (login, parsing)
│   ├── db.py             # SQLite state: assignments, alerts, checked courses
│   ├── notifier.py       # Pushover + HTML e-mail dispatch
│   ├── config_store.py   # config persistence (JSON) + form parsing
│   ├── models.py         # dataclasses: Student, Course, Assignment, CheckResult
│   ├── __version__.py    # version (badge + releases)
│   ├── requirements.txt  # flask, requests, beautifulsoup4, pytz, gunicorn
│   └── templates/
│       └── index.html    # single-file dashboard (vanilla JS, no CDN deps)
├── scripts/
│   └── release.sh        # bump version, tag, push image
├── Dockerfile            # python:3.11-slim, gunicorn, TZ-aware
└── README.md
```

## Releasing

```bash
./scripts/release.sh 1.2.0
```

Bumps `app/__version__.py`, commits `chore: release v1.2.0`, tags `v1.2.0` — CI then builds and pushes `ghcr.io/awdball/ascender-monitor:1.2.0`, also tagged `1.2` and `latest` (multi-arch amd64/arm64, real semver OCI version label). Bump the tag/digest in your Flux manifest to roll it out. Pushes to `main` only publish a `sha-<commit>` dev tag and never touch `latest`.

---

*Built by a parent who got tired of logging into the portal to see if a quiz came back. Run it, set your threshold to the honest number, and let it nag you instead.*
