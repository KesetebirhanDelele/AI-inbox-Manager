"""
Who receives what: ROLES that get assigned, never a person written into the code.

  approver            approves student notifications and is told when a student needs a person (no response, a reply that
                      needs help, STOP, cannot be reached)
  callback_owner      takes the calls from students who call back about an interview
  escalation_target   the BACKUP: told when a card has sat undecided too long (so it is NOT the approver)
  callback_backup     the callback owner's backup: told when a student callback is still open after one business hour
                      (falls back to escalation_target while nobody holds this role, which is how overdue callbacks were routed before)
  student_checker     verifies and calls a candidate who is not on the roster sheet or not in GHL (alerted by a button on the card)

Assignments live in the database (table role_assignments, edited on the dashboard's Settings page). When the work moves to
recruiters this is a settings change, not a rewrite. An optional `scope` (for example a recruiter) is stored for that day but not used yet.
Fallback when nothing is assigned: the environment variables below, so an alert is never silently lost; with neither, it is only logged.
"""
import os
from typing import Dict, List, Optional

ROLES = ("approver", "callback_owner", "escalation_target", "callback_backup", "student_checker")

ROLE_LABELS: Dict[str, str] = {
    "approver": "Approver",
    "callback_owner": "Callback owner",
    "escalation_target": "Backup approver (escalation)",
    "callback_backup": "Callback backup",
    "student_checker": "Student checker",
}
ROLE_HELP: Dict[str, str] = {
    "approver": "Approves student notifications. Emailed when a new card needs review, and when a student has not responded, replied needing help, opted out or cannot be reached.",
    "callback_owner": "Takes interview callbacks from students, within one business hour during working hours.",
    "escalation_target": "Backup for the approver: emailed when a card has waited for a decision longer than the backup time below.",
    "callback_backup": "Backup for the callback owner: emailed when a student callback is still open after one business hour.",
    "student_checker": "Verifies and calls a candidate who is not on the roster sheet or not in GHL. Emailed when someone clicks \"Alert\" on that student's card.",
}
ENV_FALLBACK: Dict[str, str] = {
    "approver": "APPROVER_ALERT_EMAIL",
    "callback_owner": "CALLBACK_OWNER_EMAIL",
    "escalation_target": "ESCALATION_ALERT_EMAIL",
    "callback_backup": "CALLBACK_BACKUP_EMAIL",
    "student_checker": "STUDENT_CHECKER_EMAIL",
}


def role_email(db, role: str, env: Optional[Dict[str, str]] = None) -> str:
    """The email assigned to a role ("" when nobody is assigned)."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    env = os.environ if env is None else env
    if db is not None:
        import models
        row = (db.query(models.RoleAssignment)
               .filter(models.RoleAssignment.role == role, models.RoleAssignment.active == True)    # noqa: E712
               .order_by(models.RoleAssignment.id.desc()).first())
        if row is not None and (row.email or "").strip():
            return row.email.strip()
    return (env.get(ENV_FALLBACK[role]) or "").strip()


def notice_copy_emails(db, env: Optional[Dict[str, str]] = None) -> List[str]:
    """Who is copied on an emailed student notification: the escalation role (it replaced the hardcoded copy list)."""
    email = role_email(db, "escalation_target", env)
    return [email] if email else []


def get_setting(db, key: str, default: str) -> str:
    """A runtime setting from system_config (changed on the Settings page, no redeploy)."""
    if db is None:
        return default
    import models
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return row.value if row is not None and row.value not in (None, "") else default


STAFF_ALERTS_KEY = "staff_email_alerts"


def staff_alerts_on(db) -> bool:
    """The master switch on the Settings page: off stops EVERY email to a role holder (approver, backup, callback owner, callback backup)."""
    return get_setting(db, STAFF_ALERTS_KEY, "on").strip().lower() not in ("off", "false", "0", "no")


LIVE_DELIVERY_KEY = "live_delivery"


def live_delivery_on(db) -> bool:
    """The Settings switch for LIVE delivery to students. Default OFF, and any doubt (no database, unreadable setting) means off."""
    if db is None:
        return False
    try:
        return get_setting(db, LIVE_DELIVERY_KEY, "off").strip().lower() in ("on", "true", "1", "yes")
    except Exception:
        return False
