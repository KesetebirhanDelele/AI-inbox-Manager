"""
An agent confirms, from the emailed link, that a student who is NOT in GHL is a candidate they are actively applying for.

That emails the GHL contact owner (role `ghl_contact_owner`, Settings page) asking her to put the student's email in GHL. The agent is copied and replies go
to the agent, so once she answers the agent updates the Google Sheet and GHL by hand (nothing here edits the sheet or GHL). Confirming twice sends nothing
the second time (alert_log kind `candidate_confirmed`, key = draft id). Nobody is written into the code.
"""
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "execution", _ROOT / "services" / "dashboard" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

KIND = "candidate_confirmed"


class NoOwner(Exception):
    """Nobody holds the ghl_contact_owner role."""


class SendFailed(Exception):
    pass


def confirmed(db, draft_id: int):
    import models as M
    return db.query(M.AlertLog).filter(M.AlertLog.kind == KIND, M.AlertLog.key == str(draft_id)).first()


def request_text(db, draft, agent_name: str, agent_email: str, roster=None) -> Dict[str, str]:
    """Subject and body of the email to the GHL contact owner."""
    import models as M
    import student_roster as sr
    event = db.get(M.InterviewEvent, draft.interview_event_id)
    student = db.get(M.Student, event.student_id) if event is not None and event.student_id else None
    name = (student.full_name if student else None) or "this student"
    roster_emails = ""
    if student is not None and roster:
        m = sr.match_student({"id": student.id, "full_name": student.full_name, "username": student.username,
                              "personal_email": student.personal_email, "assigned_gmail": student.assigned_gmail}, roster)
        if m.row is not None and m.row.emails:
            roster_emails = ", ".join(m.row.emails)
    when = " ".join(x for x in (event.interview_date, event.interview_time, event.interview_timezone) if x) if event else ""
    who = agent_name or "The student's agent"
    lines = [
        f"{who} has confirmed that {name} is a candidate they are actively applying for, but there is no matching contact in GHL.",
        "",
        "Please provide the student's email in GHL (add the contact, or fix the one that is wrong).",
        "",
        f"Student: {name}",
        f"Phone on file: {(student.phone_number if student else None) or 'none'}",
        f"Personal email on file: {(student.personal_email if student else None) or 'none'}",
        f"Application / Gmail address: {(student.assigned_gmail if student else None) or 'none'}",
        f"Emails on the roster sheet: {roster_emails or 'none'}",
    ]
    if event is not None:
        lines += ["", f"Why now: {event.sub_type or 'Interview'} with {event.company_name or 'an unnamed company'}" + (f" ({when})" if when else "")]
    lines += ["", f"Reply to this email: it goes to {agent_name or 'the agent'} ({agent_email}), who will then update the Google Sheet and GHL."]
    return {"subject": f"Please add an email in GHL for {name}", "body": "\n".join(lines)}


def confirm(db, draft, agent_name: str, agent_email: str, alerts=None, roster=None, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Email the GHL contact owner. Returns {"state": "sent" | "already", "to": ...}; raises NoOwner / SendFailed."""
    import models as M
    import roles
    from escalation_engine import RoleAlerts
    if confirmed(db, draft.id) is not None:
        return {"state": "already"}
    owner = roles.role_email(db, "ghl_contact_owner", env)
    if not owner:
        raise NoOwner()
    if roster is None:
        try:
            import student_flags
            import student_roster as sr
            student_flags._load_env()
            roster = sr.cached_roster()
        except Exception:                               # the roster only adds detail to the email
            roster = None
    text = request_text(db, draft, agent_name, agent_email, roster)
    alerts = alerts or RoleAlerts(db=db)
    if not alerts.ghl_contact_request(text["subject"], text["body"], cc=agent_email, reply_to=agent_email):
        raise SendFailed()
    db.add(M.AlertLog(kind=KIND, key=str(draft.id), detail=f"{agent_email}|{owner}"))
    db.commit()
    return {"state": "sent", "to": owner}
