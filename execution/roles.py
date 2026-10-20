"""
Who receives what: ROLES that get assigned, never a person written into the code.

  approver            approves student notifications and is told when a student needs a person (no response, a reply that
                      needs help, STOP, cannot be reached)
  callback_owner      takes the calls from students who call back about an interview
  escalation_target   the BACKUP: told when a card has sat undecided too long (so it is NOT the approver)

Assignments live in the database (table role_assignments, edited on the dashboard's Settings page). When the work moves to
recruiters this is a settings change, not a rewrite. An optional `scope` (for example a recruiter) is stored for that day but not used yet.
Fallback when nothing is assigned: the environment variables below, so an alert is never silently lost; with neither, it is only logged.
"""
import os
from typing import Dict, List, Optional

ROLES = ("approver", "callback_owner", "escalation_target")

ROLE_LABELS: Dict[str, str] = {
    "approver": "Approver",
    "callback_owner": "Callback owner",
    "escalation_target": "Backup approver (escalation)",
}
ROLE_HELP: Dict[str, str] = {
    "approver": "Approves student notifications. Emailed when a new card needs review, and when a student has not responded, replied needing help, opted out or cannot be reached.",
    "callback_owner": "Takes interview callbacks from students, within one business hour during working hours.",
    "escalation_target": "Backup for the approver: emailed when a card has waited for a decision longer than the backup time below.",
}
ENV_FALLBACK: Dict[str, str] = {
    "approver": "APPROVER_ALERT_EMAIL",
    "callback_owner": "CALLBACK_OWNER_EMAIL",
    "escalation_target": "ESCALATION_ALERT_EMAIL",
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
