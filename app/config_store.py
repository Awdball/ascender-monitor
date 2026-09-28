import os
import json
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "general": {
        "dashboard_url": ""
    },
    "ascender": {
        "district_id": "",
        "username": "",
        "password": ""
    },
    "alert_rules": {
        "min_grade": 90.0,
        "alert_on_missing": True,
        "alert_on_grade_drop": True,
        "alert_on_new_only": True
    },
    "pushover": {
        "enabled": False,
        "app_token": "",
        "user_keys": ["", ""]
    },
    "email": {
        "enabled": False,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "use_tls": True,
        "from_address": "",
        "recipients": ["", ""]
    },
    "schedule": {
        "interval_minutes": 30,
        "school_hours_only": True,
        "start_hour": 7,
        "end_hour": 18,
        "weekdays_only": True
    }
}

def load_seed_env():
    """Try to read .secrets/ascender.env or system env vars to seed initial credentials."""
    env_paths = [
        Path(os.environ.get("ENV_FILE", "")) if os.environ.get("ENV_FILE") else None,
        Path("/app/.secrets/ascender.env"),
        Path(".secrets/ascender.env"),
        Path("/app/.env"),
        Path(".env")
    ]
    env_data = {}
    for p in env_paths:
        if p and p.exists():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_data[k.strip()] = v.strip()
            break

    user = os.environ.get("ASCENDER_USERNAME") or env_data.get("ASCENDER_USERNAME", "")
    pwd = os.environ.get("ASCENDER_PASSWORD") or env_data.get("ASCENDER_PASSWORD", "")
    dist = os.environ.get("ASCENDER_DISTRICT_ID") or env_data.get("ASCENDER_DISTRICT_ID", "")
    return user, pwd, dist

def get_config():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        user, pwd, dist = load_seed_env()
        if user:
            cfg["ascender"]["username"] = user
        if pwd:
            cfg["ascender"]["password"] = pwd
        if dist:
            cfg["ascender"]["district_id"] = dist
        save_config(cfg)
        return cfg

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # Ensure any new keys in default are merged
            merged = json.loads(json.dumps(DEFAULT_CONFIG))
            for section, values in cfg.items():
                if section in merged and isinstance(values, dict):
                    merged[section].update(values)
                else:
                    merged[section] = values
            return merged
    except Exception as e:
        print(f"Error reading config file {CONFIG_FILE}: {e}")
        return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = CONFIG_FILE.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    temp_file.replace(CONFIG_FILE)
    return True

def get_safe_config():
    """Return config with passwords masked for the web UI."""
    cfg = get_config()
    safe = json.loads(json.dumps(cfg))
    if safe.get("ascender", {}).get("password"):
        safe["ascender"]["has_password"] = True
        safe["ascender"]["password"] = "••••••••"
    else:
        safe["ascender"]["has_password"] = False
        safe["ascender"]["password"] = ""

    if safe.get("email", {}).get("smtp_password"):
        safe["email"]["has_smtp_password"] = True
        safe["email"]["smtp_password"] = "••••••••"
    else:
        safe["email"]["has_smtp_password"] = False
        safe["email"]["smtp_password"] = ""

    return safe

def update_config_from_form(form_data):
    """Update config from web UI form submission, preserving existing passwords if masked."""
    current = get_config()

    # General
    current.setdefault("general", {})["dashboard_url"] = form_data.get("dashboard_url", "").strip()

    # Ascender
    current["ascender"]["district_id"] = form_data.get("district_id", "").strip()
    current["ascender"]["username"] = form_data.get("username", "").strip()
    new_pwd = form_data.get("password", "").strip()
    if new_pwd and new_pwd != "••••••••":
        current["ascender"]["password"] = new_pwd

    # Alert Rules
    try:
        current["alert_rules"]["min_grade"] = float(form_data.get("min_grade", 90.0))
    except (ValueError, TypeError):
        current["alert_rules"]["min_grade"] = 90.0
    current["alert_rules"]["alert_on_missing"] = bool(form_data.get("alert_on_missing"))
    current["alert_rules"]["alert_on_grade_drop"] = bool(form_data.get("alert_on_grade_drop"))
    current["alert_rules"]["alert_on_new_only"] = bool(form_data.get("alert_on_new_only", True))

    # Pushover
    current["pushover"]["enabled"] = bool(form_data.get("pushover_enabled"))
    current["pushover"]["app_token"] = form_data.get("pushover_app_token", "").strip()
    user_keys = []
    for k in [form_data.get("pushover_user_1", ""), form_data.get("pushover_user_2", "")]:
        if k and k.strip():
            user_keys.append(k.strip())
    # Support comma-separated extra keys
    extra_keys = form_data.get("pushover_user_keys", "")
    if isinstance(extra_keys, list):
        user_keys.extend([x.strip() for x in extra_keys if x.strip()])
    elif isinstance(extra_keys, str) and extra_keys.strip():
        user_keys.extend([x.strip() for x in extra_keys.split(",") if x.strip()])
    current["pushover"]["user_keys"] = list(dict.fromkeys(user_keys))

    # Email
    current["email"]["enabled"] = bool(form_data.get("email_enabled"))
    current["email"]["smtp_host"] = form_data.get("smtp_host", "").strip()
    try:
        current["email"]["smtp_port"] = int(form_data.get("smtp_port", 587))
    except (ValueError, TypeError):
        current["email"]["smtp_port"] = 587
    current["email"]["smtp_user"] = form_data.get("smtp_user", "").strip()
    new_smtp_pwd = form_data.get("smtp_password", "").strip()
    if new_smtp_pwd and new_smtp_pwd != "••••••••":
        current["email"]["smtp_password"] = new_smtp_pwd
    current["email"]["use_tls"] = bool(form_data.get("use_tls", True))
    current["email"]["from_address"] = form_data.get("from_address", "").strip() or current["email"]["smtp_user"]

    recipients = []
    for r in [form_data.get("email_recipient_1", ""), form_data.get("email_recipient_2", "")]:
        if r and r.strip():
            recipients.append(r.strip())
    extra_recipients = form_data.get("email_recipients", "")
    if isinstance(extra_recipients, list):
        recipients.extend([x.strip() for x in extra_recipients if x.strip()])
    elif isinstance(extra_recipients, str) and extra_recipients.strip():
        recipients.extend([x.strip() for x in extra_recipients.split(",") if x.strip()])
    current["email"]["recipients"] = list(dict.fromkeys(recipients))

    # Schedule
    try:
        current["schedule"]["interval_minutes"] = max(5, int(form_data.get("interval_minutes", 30)))
    except (ValueError, TypeError):
        current["schedule"]["interval_minutes"] = 30
    current["schedule"]["school_hours_only"] = bool(form_data.get("school_hours_only"))
    try:
        current["schedule"]["start_hour"] = int(form_data.get("start_hour", 7))
        current["schedule"]["end_hour"] = int(form_data.get("end_hour", 18))
    except (ValueError, TypeError):
        current["schedule"]["start_hour"] = 7
        current["schedule"]["end_hour"] = 18
    current["schedule"]["weekdays_only"] = bool(form_data.get("weekdays_only", True))

    save_config(current)
    return current
