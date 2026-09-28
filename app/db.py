import os
import sqlite3
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "ascender.db"

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
        UNIQUE(student_id, course, assignment)
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
                       alert_on_missing=True, alert_on_grade_drop=True):
    """
    Saves or updates assignment.
    Returns: (is_new, previous_grade, should_alert, alert_type)
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
    SELECT id, grade, numeric_grade, is_missing FROM assignments
    WHERE student_id=? AND course=? AND assignment=?
    """, (student_id, course, assignment))
    row = c.fetchone()

    should_alert = False
    alert_type = None
    is_new = False
    prev_grade = None

    if row is None:
        is_new = True
        c.execute("""
        INSERT INTO assignments (
            student_id, student_name, course, assignment, category, due_date,
            grade, numeric_grade, is_missing, is_failing, assignment_note, first_seen, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (student_id, student_name, course, assignment, category, due_date,
              raw_grade_str, numeric_grade, is_missing, 1 if is_failing else 0, assignment_note, now, now))
        
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

        c.execute("""
        UPDATE assignments SET
            category=?, due_date=?, grade=?, numeric_grade=?,
            is_missing=?, is_failing=?, assignment_note=?, last_seen=?
        WHERE id=?
        """, (category, due_date, raw_grade_str, numeric_grade,
              is_missing, 1 if is_failing else 0, assignment_note, now, row["id"]))

        # Check alert conditions on change
        if not prev_missing and is_missing and alert_on_missing:
            should_alert = True
            alert_type = "MISSING"
        elif numeric_grade is not None and numeric_grade < min_grade_threshold:
            if prev_num is None:
                should_alert = True
                alert_type = "LOW_GRADE"
            elif alert_on_grade_drop and numeric_grade < prev_num:
                should_alert = True
                alert_type = "GRADE_DROP"

    conn.commit()
    conn.close()
    return is_new, prev_grade, should_alert, alert_type

def log_alert(student_name, course, assignment, grade, alert_type, channels, status="SENT", error_message=""):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
    INSERT INTO alerts (timestamp, student_name, course, assignment, grade, alert_type, channels, status, error_message)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now, student_name, course, assignment, grade, alert_type, channels, status, error_message))
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
        SELECT course, assignment, category, due_date, grade, numeric_grade, is_missing, is_failing, assignment_note
        FROM assignments
        WHERE student_id=?
        ORDER BY course, due_date DESC, assignment
        """, (s_id,))
        assignments = [dict(r) for r in c.fetchall()]
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

    conn.close()
    return students

def get_recent_alerts(limit=50):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT id, timestamp, student_name, course, assignment, grade, alert_type, channels, status, error_message
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
