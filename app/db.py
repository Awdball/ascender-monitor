import os
import sqlite3
from pathlib import Path
from datetime import datetime, date

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "ascender.db"

def format_grade_display(val):
    if val is None or val == "":
        return "N/A"
    s = str(val).strip()
    if s.upper() == "M":
        return "Missing"
    if s.upper() == "X":
        return "Exempt"
    try:
        num = float(s)
        if num.is_integer():
            return f"{int(num)}%"
        return f"{num}%"
    except ValueError:
        return s

def format_short_date(dt_val):
    if not dt_val:
        return ""
    if isinstance(dt_val, str):
        try:
            dt = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
            return dt.strftime("%m/%d/%y")
        except Exception:
            return dt_val
    elif isinstance(dt_val, (datetime, date)):
        return dt_val.strftime("%m/%d/%y")
    return str(dt_val)

def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS students (
        student_id TEXT PRIMARY KEY,
        student_name TEXT NOT NULL,
        campus_name TEXT,
        last_updated DATETIME
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        student_name TEXT NOT NULL,
        course TEXT NOT NULL,
        assignment TEXT NOT NULL,
        category TEXT,
        due_date TEXT,
        grade TEXT,
        numeric_grade REAL,
        is_missing BOOLEAN DEFAULT 0,
        is_failing BOOLEAN DEFAULT 0,
        assignment_note TEXT,
        first_seen DATETIME NOT NULL,
        last_seen DATETIME NOT NULL,
        previous_grade TEXT,
        previous_grade_date DATETIME,
        grade_updated_at DATETIME,
        UNIQUE(student_id, course, assignment)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS assignment_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER,
        student_id TEXT NOT NULL,
        student_name TEXT NOT NULL,
        course TEXT NOT NULL,
        assignment TEXT NOT NULL,
        old_grade TEXT,
        new_grade TEXT,
        old_numeric_grade REAL,
        new_numeric_grade REAL,
        changed_at DATETIME NOT NULL,
        change_type TEXT NOT NULL
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME NOT NULL,
        student_name TEXT NOT NULL,
        course TEXT NOT NULL,
        assignment TEXT NOT NULL,
        grade TEXT,
        old_grade TEXT,
        alert_type TEXT NOT NULL,
        channels TEXT,
        status TEXT NOT NULL,
        error_message TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS system_status (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at DATETIME
    )
    """)

    # Safe migrations for existing databases
    c.execute("PRAGMA table_info(assignments)")
    assign_cols = [r["name"] for r in c.fetchall()]
    if "previous_grade" not in assign_cols:
        c.execute("ALTER TABLE assignments ADD COLUMN previous_grade TEXT")
    if "previous_grade_date" not in assign_cols:
        c.execute("ALTER TABLE assignments ADD COLUMN previous_grade_date DATETIME")
    if "grade_updated_at" not in assign_cols:
        c.execute("ALTER TABLE assignments ADD COLUMN grade_updated_at DATETIME")

    c.execute("PRAGMA table_info(alerts)")
    alert_cols = [r["name"] for r in c.fetchall()]
    if "old_grade" not in alert_cols:
        c.execute("ALTER TABLE alerts ADD COLUMN old_grade TEXT")

    conn.commit()
    conn.close()

def set_status(key, value):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
    INSERT INTO system_status (key, value, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, str(value), now))
    conn.commit()
    conn.close()

def get_status():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT key, value, updated_at FROM system_status")
    rows = c.fetchall()
    conn.close()
    return {r["key"]: {"value": r["value"], "updated_at": r["updated_at"]} for r in rows}

def upsert_student(student_id, student_name, campus_name=""):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
    INSERT INTO students (student_id, student_name, campus_name, last_updated)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(student_id) DO UPDATE SET
        student_name=excluded.student_name,
        campus_name=excluded.campus_name,
        last_updated=excluded.last_updated
    """, (student_id, student_name, campus_name, now))
    conn.commit()
    conn.close()

def process_assignment(student_id, student_name, course, assignment, category, due_date,
                       raw_grade, is_failing, assignment_note, min_grade_threshold,
                       alert_on_missing=True, alert_on_grade_drop=True, alert_on_updated=True):
    """
    Saves or updates assignment.
    Returns: (is_new, is_update, prev_grade, prev_grade_date, should_alert, alert_type)
    """
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()

    raw_grade_str = str(raw_grade or "").strip()
    is_missing = 1 if raw_grade_str.upper() == "M" else 0

    numeric_grade = None
    try:
        numeric_grade = float(raw_grade_str)
    except ValueError:
        pass

    c.execute("""
    SELECT id, grade, numeric_grade, is_missing, first_seen, last_seen,
           previous_grade, previous_grade_date, grade_updated_at
    FROM assignments
    WHERE student_id=? AND course=? AND assignment=?
    """, (student_id, course, assignment))
    row = c.fetchone()

    should_alert = False
    alert_type = None
    is_new = False
    is_update = False
    prev_grade = None
    prev_grade_date = None

    if row is None:
        is_new = True
        c.execute("""
        INSERT INTO assignments (
            student_id, student_name, course, assignment, category, due_date,
            grade, numeric_grade, is_missing, is_failing, assignment_note,
            first_seen, last_seen, previous_grade, previous_grade_date, grade_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
        """, (student_id, student_name, course, assignment, category, due_date,
              raw_grade_str, numeric_grade, is_missing, 1 if is_failing else 0, assignment_note,
              now, now))

        if is_missing and alert_on_missing:
            should_alert = True
            alert_type = "MISSING"
        elif numeric_grade is not None and numeric_grade < min_grade_threshold:
            should_alert = True
            alert_type = "LOW_GRADE"
    else:
        prev_grade = row["grade"]
        prev_num = row["numeric_grade"]
        prev_missing = bool(row["is_missing"])
        prev_grade_date = row["grade_updated_at"] or row["first_seen"]

        # Check if grade actually changed
        grade_changed = (raw_grade_str != prev_grade)

        if grade_changed:
            is_update = True
            if prev_missing and not is_missing:
                # Turned in previously missing assignment
                alert_type = "TURNED_IN"
                if alert_on_updated:
                    should_alert = True
            elif not prev_missing and is_missing:
                # Newly missing
                alert_type = "MISSING"
                if alert_on_missing:
                    should_alert = True
            elif numeric_grade is not None and prev_num is not None:
                if numeric_grade < prev_num:
                    alert_type = "GRADE_DROP"
                    if alert_on_grade_drop:
                        should_alert = True
                elif numeric_grade > prev_num:
                    alert_type = "GRADE_IMPROVED"
                    if alert_on_updated:
                        should_alert = True
                else:
                    alert_type = "GRADE_UPDATED"
                    if alert_on_updated:
                        should_alert = True
            else:
                alert_type = "GRADE_UPDATED"
                if alert_on_updated:
                    should_alert = True

            c.execute("""
            UPDATE assignments SET
                category=?, due_date=?, grade=?, numeric_grade=?,
                is_missing=?, is_failing=?, assignment_note=?, last_seen=?,
                previous_grade=?, previous_grade_date=?, grade_updated_at=?
            WHERE id=?
            """, (category, due_date, raw_grade_str, numeric_grade,
                  is_missing, 1 if is_failing else 0, assignment_note, now,
                  prev_grade, prev_grade_date, now, row["id"]))

            c.execute("""
            INSERT INTO assignment_history (
                assignment_id, student_id, student_name, course, assignment,
                old_grade, new_grade, old_numeric_grade, new_numeric_grade,
                changed_at, change_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (row["id"], student_id, student_name, course, assignment,
                  prev_grade, raw_grade_str, prev_num, numeric_grade,
                  now, alert_type or "GRADE_UPDATED"))
        else:
            c.execute("""
            UPDATE assignments SET
                category=?, due_date=?, is_failing=?, assignment_note=?, last_seen=?
            WHERE id=?
            """, (category, due_date, 1 if is_failing else 0, assignment_note, now, row["id"]))

    conn.commit()
    conn.close()
    return is_new, is_update, prev_grade, prev_grade_date, should_alert, alert_type

def log_alert(student_name, course, assignment, grade, alert_type, channels, status="SENT", error_message="", old_grade=None):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
    INSERT INTO alerts (timestamp, student_name, course, assignment, grade, old_grade, alert_type, channels, status, error_message)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now, student_name, course, assignment, grade, old_grade, alert_type, channels, status, error_message))
    conn.commit()
    conn.close()

def get_dashboard_data(min_grade=90.0):
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT student_id, student_name, campus_name, last_updated FROM students ORDER BY student_name")
    students = [dict(r) for r in c.fetchall()]

    for s in students:
        s_id = s["student_id"]
        c.execute("""
        SELECT id, course, assignment, category, due_date, grade, numeric_grade,
               is_missing, is_failing, assignment_note, first_seen, last_seen,
               previous_grade, previous_grade_date, grade_updated_at
        FROM assignments
        WHERE student_id=?
        ORDER BY course, due_date DESC, assignment
        """, (s_id,))
        assignments = [dict(r) for r in c.fetchall()]

        # Annotate assignments with formatted fields
        for a in assignments:
            a["grade_display"] = format_grade_display(a["grade"])
            if a["previous_grade"]:
                a["is_updated"] = True
                a["previous_grade_display"] = format_grade_display(a["previous_grade"])
                prev_date_str = format_short_date(a["previous_grade_date"])
                curr_date_str = format_short_date(a["grade_updated_at"])
                a["transition_display"] = (
                    f"{a['previous_grade_display']} ({prev_date_str}) ➔ Updated {a['grade_display']} ({curr_date_str})"
                )
            else:
                a["is_updated"] = False
                a["previous_grade_display"] = None
                a["transition_display"] = None

        s["assignments"] = assignments

        # Group by course
        courses = {}
        for a in assignments:
            c_name = a["course"]
            if c_name not in courses:
                courses[c_name] = {"name": c_name, "assignments": [], "grades": []}
            courses[c_name]["assignments"].append(a)
            if a["numeric_grade"] is not None:
                courses[c_name]["grades"].append(a["numeric_grade"])

        # Calculate rough course averages
        course_list = []
        for c_name, c_data in courses.items():
            avg = round(sum(c_data["grades"]) / len(c_data["grades"]), 1) if c_data["grades"] else None
            course_list.append({
                "name": c_name,
                "average": avg,
                "total_assignments": len(c_data["assignments"]),
                "assignments": c_data["assignments"]
            })
        s["courses"] = course_list

        # Flagged items (missing or < min_grade)
        s["flagged"] = [
            a for a in assignments
            if a["is_missing"] or (a["numeric_grade"] is not None and a["numeric_grade"] < min_grade)
        ]

        # Updated assignments (ordered by most recently updated)
        updated_list = [a for a in assignments if a["is_updated"]]
        updated_list.sort(key=lambda x: x["grade_updated_at"] or "", reverse=True)
        s["updated_assignments"] = updated_list

    conn.close()
    return students

def get_recent_alerts(limit=50):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT id, timestamp, student_name, course, assignment, grade, old_grade, alert_type, channels, status, error_message
    FROM alerts
    ORDER BY timestamp DESC
    LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def clear_alerts():
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM alerts")
    conn.commit()
    conn.close()
    return True
