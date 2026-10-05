import os
import time
import threading
from datetime import datetime, timedelta
import pytz
from flask import Flask, render_template, jsonify, request

import config_store
import db
import notifier
from portal import AscenderPortalClient
from __version__ import __version__

app = Flask(__name__)
check_trigger = threading.Event()
is_checking = False
check_lock = threading.Lock()

TIMEZONE = pytz.timezone(os.environ.get("TZ", "America/Chicago"))

def run_grade_check():
    global is_checking
    with check_lock:
        if is_checking:
            return False, "Check already in progress"
        is_checking = True

    try:
        db.set_status("is_checking", "true")
        db.set_status("last_check_start", datetime.now(TIMEZONE).isoformat())

        config = config_store.get_config()
        asc_cfg = config.get("ascender", {})
        username = asc_cfg.get("username")
        password = asc_cfg.get("password")
        dist_id = asc_cfg.get("district_id", "061907")

        if not username or not password:
            err = "Ascender username or password not configured."
            db.set_status("last_check_status", f"ERROR: {err}")
            return False, err

        client = AscenderPortalClient(district_id=dist_id, username=username, password=password)
        ok, err = client.login()
        if not ok:
            db.set_status("last_check_status", f"LOGIN FAILED: {err}")
            return False, f"Login failed: {err}"

        students = client.get_students()
        if not students:
            db.set_status("last_check_status", "WARNING: No students found on account")
            return False, "No students found"

        rules = config.get("alert_rules", {})
        min_grade = float(rules.get("min_grade", 90.0))
        alert_on_missing = bool(rules.get("alert_on_missing", True))
        alert_on_grade_drop = bool(rules.get("alert_on_grade_drop", True))
        alert_on_updated = bool(rules.get("alert_on_updated", True))
        alert_on_new_only = bool(rules.get("alert_on_new_only", True))

        total_assignments = 0
        new_alerts = 0

        for s in students:
            s_id = s["student_id"]
            s_name = s["student_name"]
            db.upsert_student(s_id, s_name)

            assignments = client.get_assignments(s_id)
            total_assignments += len(assignments)

            for a in assignments:
                is_new, is_update, prev_grade, prev_grade_date, should_alert, alert_type = db.process_assignment(
                    student_id=s_id,
                    student_name=s_name,
                    course=a["course"],
                    assignment=a["assignment"],
                    category=a["category"],
                    due_date=a["due_date"],
                    raw_grade=a["grade"],
                    is_failing=a["failing_grade"],
                    assignment_note=a["assignment_note"],
                    min_grade_threshold=min_grade,
                    alert_on_missing=alert_on_missing,
                    alert_on_grade_drop=alert_on_grade_drop,
                    alert_on_updated=alert_on_updated
                )

                if should_alert:
                    # Alert if new, updated, or if repeat alerts are enabled
                    if is_new or is_update or (not alert_on_new_only) or alert_type == "MISSING":
                        notifier.dispatch_grade_alert(
                            config=config,
                            student_name=s_name,
                            course=a["course"],
                            assignment=a["assignment"],
                            grade=a["grade"],
                            alert_type=alert_type,
                            due_date=a["due_date"],
                            note=a["assignment_note"],
                            is_update=is_update,
                            prev_grade=prev_grade,
                            prev_grade_date=prev_grade_date
                        )
                        new_alerts += 1

        summary = f"Checked {len(students)} student(s), {total_assignments} assignments. Alerts sent: {new_alerts}"
        now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d %I:%M %p")
        db.set_status("last_check_status", "SUCCESS")
        db.set_status("last_check_time", now_str)
        db.set_status("last_check_summary", summary)
        return True, summary

    except Exception as e:
        err_msg = str(e)
        db.set_status("last_check_status", f"ERROR: {err_msg}")
        return False, err_msg
    finally:
        with check_lock:
            is_checking = False
        db.set_status("is_checking", "false")

def background_monitor():
    """Background polling daemon with quiet hours / school hours filter."""
    print("[*] Starting Ascender background monitoring loop...")
    while True:
        config = config_store.get_config()
        sched = config.get("schedule", {})
        interval = max(5, int(sched.get("interval_minutes", 30)))
        school_hours = bool(sched.get("school_hours_only", True))
        start_hour = int(sched.get("start_hour", 7))
        end_hour = int(sched.get("end_hour", 18))
        weekdays_only = bool(sched.get("weekdays_only", True))

        now = datetime.now(TIMEZONE)
        should_run = True

        if school_hours:
            if weekdays_only and now.weekday() >= 5: # Sat or Sun
                should_run = False
            elif not (start_hour <= now.hour < end_hour):
                should_run = False

        if should_run:
            print(f"[*] Running scheduled grade check at {now.strftime('%I:%M %p')}...")
            run_grade_check()
        else:
            print(f"[*] Outside school hours ({now.strftime('%I:%M %p')}), skipping automatic check.")

        # Calculate next check time
        next_run = datetime.now(TIMEZONE) + timedelta(minutes=interval)
        db.set_status("next_check_time", next_run.strftime("%Y-%m-%d %I:%M %p"))

        # Wait for either interval or manual trigger event
        triggered = check_trigger.wait(timeout=interval * 60)
        if triggered:
            check_trigger.clear()
            print("[*] Manual check triggered via UI!")
            run_grade_check()

# Flask API Routes

@app.route("/")
def index():
    return render_template("index.html", version=__version__)

@app.route("/api/status")
def api_status():
    status = db.get_status()
    cfg = config_store.get_config()
    return jsonify({
        "status": status,
        "version": __version__,
        "is_checking": is_checking,
        "interval_minutes": cfg.get("schedule", {}).get("interval_minutes", 30),
        "alert_threshold": cfg.get("alert_rules", {}).get("min_grade", 90.0)
    })

@app.route("/api/data")
def api_data():
    cfg = config_store.get_config()
    min_grade = float(cfg.get("alert_rules", {}).get("min_grade", 90.0))
    students = db.get_dashboard_data(min_grade=min_grade)
    recent_alerts = db.get_recent_alerts(limit=50)
    return jsonify({
        "students": students,
        "recent_alerts": recent_alerts
    })

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        data = request.json or {}
        updated = config_store.update_config_from_form(data)
        return jsonify({"success": True, "config": config_store.get_safe_config()})
    return jsonify(config_store.get_safe_config())

@app.route("/api/check-now", methods=["POST"])
def api_check_now():
    if is_checking:
        return jsonify({"success": False, "message": "A check is already in progress."}), 409
    
    # Run in thread or trigger
    def run_async():
        run_grade_check()
    t = threading.Thread(target=run_async, daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Grade check started in background."})

@app.route("/api/test-notification", methods=["POST"])
def api_test_notification():
    cfg = config_store.get_config()
    results = notifier.dispatch_test_notification(cfg)
    return jsonify(results)

@app.route("/api/clear-alerts", methods=["POST"])
def api_clear_alerts():
    db.clear_alerts()
    return jsonify({"success": True})

def startup():
    db.init_db()
    # Start background scheduler thread
    bg_thread = threading.Thread(target=background_monitor, daemon=True)
    bg_thread.start()

# Initialize when loaded
startup()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
