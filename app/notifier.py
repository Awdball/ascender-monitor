import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import db

def send_pushover(app_token, user_keys, title, message, url="", priority=0):
    if not app_token or not user_keys:
        return {"success": False, "error": "Missing Pushover app_token or user_keys"}

    results = {}
    endpoint = "https://api.pushover.net/1/messages.json"

    for user_key in user_keys:
        if not user_key or not user_key.strip():
            continue
        user_key = user_key.strip()
        payload = {
            "token": app_token.strip(),
            "user": user_key,
            "title": title,
            "message": message,
            "priority": priority
        }
        if url:
            payload["url"] = url
            payload["url_title"] = "Open Grade Dashboard"
        }
        try:
            resp = requests.post(endpoint, data=payload, timeout=10)
            if resp.status_code == 200:
                results[user_key] = {"success": True, "error": None}
            else:
                err = f"HTTP {resp.status_code}: {resp.text}"
                results[user_key] = {"success": False, "error": err}
        except Exception as e:
            results[user_key] = {"success": False, "error": str(e)}

    all_success = any(r["success"] for r in results.values())
    return {"success": all_success, "details": results}

def send_email(smtp_host, smtp_port, smtp_user, smtp_pass, use_tls, from_addr, recipients, subject, body_html, body_text=""):
    if not smtp_host or not recipients:
        return {"success": False, "error": "Missing SMTP host or recipients"}

    valid_recipients = [r.strip() for r in recipients if r and r.strip()]
    if not valid_recipients:
        return {"success": False, "error": "No valid recipients"}

    from_addr = from_addr or smtp_user

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Ascender Grade Monitor <{from_addr}>"
    msg["To"] = ", ".join(valid_recipients)

    if body_text:
        msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            if use_tls:
                server.starttls()

        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)

        server.sendmail(from_addr, valid_recipients, msg.as_string())
        server.quit()
        return {"success": True, "recipients": valid_recipients}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dispatch_grade_alert(config, student_name, course, assignment, grade, alert_type, due_date="", note=""):
    channels_used = []
    errors = []

    if alert_type == "MISSING":
        title = f"⚠️ Missing Assignment: {student_name}"
        pushover_msg = (
            f"Student: {student_name}\n"
            f"Course: {course}\n"
            f"Assignment: {assignment}\n"
            f"Due Date: {due_date or 'N/A'}\n"
            f"Status: MISSING"
        )
        badge_color = "#dc3545"
        status_text = "MISSING ASSIGNMENT"
    elif alert_type == "GRADE_DROP":
        title = f"📉 Grade Drop: {student_name} ({grade}%)"
        pushover_msg = (
            f"Student: {student_name}\n"
            f"Course: {course}\n"
            f"Assignment: {assignment}\n"
            f"New Grade: {grade}%\n"
            f"Due Date: {due_date or 'N/A'}"
        )
        badge_color = "#fd7e14"
        status_text = f"GRADE DROP: {grade}%"
    else: # LOW_GRADE
        title = f"📉 Low Grade Alert: {student_name} ({grade}%)"
        pushover_msg = (
            f"Student: {student_name}\n"
            f"Course: {course}\n"
            f"Assignment: {assignment}\n"
            f"Grade: {grade}%\n"
            f"Due Date: {due_date or 'N/A'}"
        )
        badge_color = "#fd7e14"
        status_text = f"LOW GRADE: {grade}%"

    if note:
        pushover_msg += f"\nNote: {note}"

    dashboard_url = config.get("general", {}).get("dashboard_url", "").strip()
    button_html = f'<div style="text-align: center;"><a href="{dashboard_url}" class="button">Open Grade Dashboard</a></div>' if dashboard_url else ''

    # HTML Email Template
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            .header {{ background-color: #212529; color: #ffffff; padding: 20px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 20px; font-weight: 600; }}
            .content {{ padding: 25px 20px; }}
            .badge {{ display: inline-block; padding: 6px 14px; border-radius: 50px; color: #ffffff; background-color: {badge_color}; font-weight: 700; font-size: 14px; margin-bottom: 15px; }}
            .detail-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            .detail-table td {{ padding: 10px; border-bottom: 1px solid #edf2f7; font-size: 15px; }}
            .detail-table td.label {{ font-weight: 600; color: #4a5568; width: 120px; }}
            .button {{ display: inline-block; padding: 12px 24px; background-color: #0d6efd; color: #ffffff !important; text-decoration: none; border-radius: 6px; font-weight: 600; margin-top: 25px; }}
            .footer {{ text-align: center; padding: 15px; color: #8898aa; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Ascender Grade Alert</h1>
            </div>
            <div class="content">
                <div class="badge">{status_text}</div>
                <table class="detail-table">
                    <tr><td class="label">Student:</td><td><strong>{student_name}</strong></td></tr>
                    <tr><td class="label">Course:</td><td>{course}</td></tr>
                    <tr><td class="label">Assignment:</td><td>{assignment}</td></tr>
                    <tr><td class="label">Grade:</td><td><strong style="color: {badge_color}; font-size: 18px;">{grade}</strong></td></tr>
                    <tr><td class="label">Due Date:</td><td>{due_date or 'N/A'}</td></tr>
                    {f'<tr><td class="label">Note:</td><td>{note}</td></tr>' if note else ''}
                </table>
                {button_html}
            </div>
            <div class="footer">
                Automated notification from Ascender Grade Monitor
            </div>
        </div>
    </body>
    </html>
    """

    # 1. Pushover dispatch
    po_cfg = config.get("pushover", {})
    if po_cfg.get("enabled"):
        app_token = po_cfg.get("app_token", "")
        user_keys = po_cfg.get("user_keys", [])
        res = send_pushover(app_token, user_keys, title, pushover_msg, url=dashboard_url, priority=1 if alert_type == "MISSING" else 0)
        if res.get("success"):
            succ_count = sum(1 for v in res.get("details", {}).values() if v.get("success"))
            channels_used.append(f"pushover({succ_count})")
        else:
            errors.append(f"Pushover: {res.get('error')}")

    # 2. Email dispatch
    em_cfg = config.get("email", {})
    if em_cfg.get("enabled"):
        res = send_email(
            smtp_host=em_cfg.get("smtp_host"),
            smtp_port=em_cfg.get("smtp_port", 587),
            smtp_user=em_cfg.get("smtp_user"),
            smtp_pass=em_cfg.get("smtp_password"),
            use_tls=em_cfg.get("use_tls", True),
            from_addr=em_cfg.get("from_address"),
            recipients=em_cfg.get("recipients", []),
            subject=title,
            body_html=html_body,
            body_text=pushover_msg
        )
        if res.get("success"):
            channels_used.append(f"email({len(res.get('recipients', []))})")
        else:
            errors.append(f"Email: {res.get('error')}")

    channels_str = ", ".join(channels_used) if channels_used else "none"
    status_str = "SENT" if channels_used else ("FAILED" if errors else "SKIPPED")
    error_str = "; ".join(errors) if errors else ""

    db.log_alert(
        student_name=student_name,
        course=course,
        assignment=assignment,
        grade=str(grade),
        alert_type=alert_type,
        channels=channels_str,
        status=status_str,
        error_message=error_str
    )
    return {"status": status_str, "channels": channels_str, "error": error_str}

def dispatch_test_notification(config):
    summary = {"pushover": None, "email": None}

    # Test Pushover
    po_cfg = config.get("pushover", {})
    if po_cfg.get("enabled"):
        app_token = po_cfg.get("app_token")
        user_keys = po_cfg.get("user_keys", [])
        if app_token and user_keys:
            res = send_pushover(
                app_token,
                user_keys,
                title="✅ Pushover Test: Ascender Monitor",
                message="This is a test notification from your Ascender Grade Monitor. Notifications to all accounts are working properly!"
            )
            summary["pushover"] = res
        else:
            summary["pushover"] = {"success": False, "error": "Pushover enabled but token or user keys missing"}
    else:
        summary["pushover"] = {"success": False, "error": "Pushover is not enabled"}

    # Test Email
    em_cfg = config.get("email", {})
    if em_cfg.get("enabled"):
        res = send_email(
            smtp_host=em_cfg.get("smtp_host"),
            smtp_port=em_cfg.get("smtp_port", 587),
            smtp_user=em_cfg.get("smtp_user"),
            smtp_pass=em_cfg.get("smtp_password"),
            use_tls=em_cfg.get("use_tls", True),
            from_addr=em_cfg.get("from_address"),
            recipients=em_cfg.get("recipients", []),
            subject="✅ Test Notification: Ascender Grade Monitor",
            body_html=f"<h3>Ascender Grade Monitor</h3><p>This is a test email confirming that email delivery to all configured recipients is working properly.</p>{f'<p><a href=\"{config.get(\"general\", {}).get(\"dashboard_url\", \"\")}\">Open Grade Dashboard</a></p>' if config.get('general', {}).get('dashboard_url') else ''}",
            body_text="Ascender Grade Monitor: This is a test email confirming that email delivery is working properly."
        )
        summary["email"] = res
    else:
        summary["email"] = {"success": False, "error": "Email is not enabled"}

    return summary
