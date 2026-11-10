"""
Tell the escalation role about notification drafts that have waited too long for approval.

A draft that nobody has approved or rejected after STALE_DRAFT_BUSINESS_MINUTES (default 120 = 2 business hours) is listed in ONE email
to the person who holds the escalation_target role (execution/roles.py). It goes to the escalation role, never to the approver: the approver
is the one who has not acted, so telling them tells the person who already knows.

  * Each draft is reported once (table alert_log, kind "stale_draft").
  * The first run records every draft that already exists as "baseline" WITHOUT emailing, so a backlog (for example drafts created by a
    backfill) never floods the escalation role; only drafts that go stale after that are reported.
  * Nothing is sent or marked while nobody holds the role (the warning is logged), so the alert goes out as soon as someone is assigned.
  * Only runs inside business hours (execution/business_hours.py), so the hours before the working day never trigger an alert on their own.

Run every 15 minutes by the host cron (execution/crontab.stale). Safe to run any time.
"""
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://2-29-47-89.nip.io/review")
MAX_LISTED = 25
HOURS_KEY = "stale_draft_business_hours"


def stale_minutes(env: Optional[Dict[str, str]] = None, db=None) -> int:
    """Business minutes before the backup is told: the Settings page value (system_config stale_draft_business_hours) wins over the env variable."""
    env = os.environ if env is None else env
    if db is not None:
        import roles
        try:
            hours = float(roles.get_setting(db, HOURS_KEY, ""))
            if hours > 0:
                return max(1, int(hours * 60))
        except ValueError:
            pass
    try:
        return max(1, int(env.get("STALE_DRAFT_BUSINESS_MINUTES") or 120))
    except ValueError:
        return 120


def run(db, now: datetime, alerts=None, hours=None, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    import models as M
    import roles
    from business_hours import BusinessHours, business_minutes_between, is_business_time
    from escalation_engine import RoleAlerts

    hours = hours or BusinessHours.from_env(env)
    alerts = alerts or RoleAlerts(db=db)
    threshold = stale_minutes(env, db)

    from open_cards import open_review_drafts
    drafts = open_review_drafts(db, now)               # only cards the Review screen shows (not follow-ups, rejected students or old mail)

    baseline = db.query(M.AlertLog).filter(M.AlertLog.kind == "stale_draft_baseline").first()
    if baseline is None:
        for d in drafts:
            db.add(M.AlertLog(kind="stale_draft", key=str(d.id), detail="baseline: existed before the alert was switched on"))
        db.add(M.AlertLog(kind="stale_draft_baseline", key="1", detail=f"{len(drafts)} existing drafts recorded without an alert"))
        db.commit()
        return {"status": "baseline", "recorded": len(drafts), "alerted": 0}

    if not is_business_time(now, hours):
        return {"status": "outside business hours", "alerted": 0}

    already = {a.key for a in db.query(M.AlertLog).filter(M.AlertLog.kind == "stale_draft").all()}
    stale: List[Any] = []
    for d in drafts:
        if str(d.id) in already or d.created_at is None:
            continue
        if business_minutes_between(d.created_at, now, hours) >= threshold:
            stale.append(d)
    if not stale:
        return {"status": "nothing stale", "alerted": 0}

    import agent_routing
    approver = (roles.role_email(db, "approver", env) or "").strip().lower()
    emails = agent_routing.agent_emails(db)

    def _agent_is_the_approver(name: str) -> bool:                   # the approver cannot be their own backup: the escalation role is told instead
        return bool(approver) and emails.get(agent_routing.key(name), "").strip().lower() == approver

    to_approver = [d for d in stale if agent_routing.agent_of_alert(db, d.id) and not _agent_is_the_approver(agent_routing.agent_of_alert(db, d.id))]       # the agent did not decide: the approver is the backup
    to_escalation = [d for d in stale if d not in to_approver]                        # the approver did not decide: the escalation role is the backup
    out = {"status": "sent", "alerted": 0}
    for group, role, method in ((to_approver, "approver", "stale_for_approver"), (to_escalation, "escalation_target", "stale_drafts")):
        if not group:
            continue
        send = getattr(alerts, method)
        step = _tell(db, group, role, send, alerts, now, hours, threshold, env)
        out["alerted"] += step.get("alerted", 0)
        if step["status"] != "sent":
            out["status"] = step["status"]
            out.update({k: v for k, v in step.items() if k not in ("status", "alerted")})
    return out


def _tell(db, stale, role: str, send, alerts, now, hours, threshold, env) -> Dict[str, Any]:
    import models as M
    import roles
    from business_hours import business_minutes_between
    backup = roles.role_email(db, role, env)
    if not backup:
        send("Drafts waiting for approval", f"{len(stale)} draft(s) are stale but nobody holds the {role} role.")
        return {"status": "no escalation role assigned" if role == "escalation_target" else "no approver assigned", "alerted": 0, "stale": len(stale)}
    lines = []
    for d in stale[:MAX_LISTED]:
        event = db.get(M.InterviewEvent, d.interview_event_id)
        try:
            import approval_links
            link = approval_links.create_link(db, d.id, role, backup, now, env)
        except Exception:                               # no link must never stop the alert
            link = ""
        student = db.get(M.Student, event.student_id) if event and event.student_id else None
        age = business_minutes_between(d.created_at, now, hours)
        lines.append(f"- {(student.full_name if student else 'Unknown student')} / "
                     f"{(event.company_name if event else '') or 'unknown company'}: waiting {age / 60:.1f} business hours"
                     + (f"\n    Review and approve on your phone: {link}" if link else ""))
    more = f"\n...and {len(stale) - MAX_LISTED} more." if len(stale) > MAX_LISTED else ""
    who = ("the student's agent has not acted on them (you are the backup)" if role == "approver"
           else "the approver has not acted on them (you are the backup)")
    body = (f"{len(stale)} student notification draft(s) have been waiting for approval for more than "
            f"{threshold / 60:g} business hours:\n\n" + "\n".join(lines) + more +
            f"\n\nThey are in the approval screen: {DASHBOARD_URL}\n"
            f"You are receiving this because you hold the {role.replace('_', ' ')} role; {who}.")
    sent = send(f"{len(stale)} notification draft(s) waiting for approval", body)
    if sent:
        for d in stale:
            db.add(M.AlertLog(kind="stale_draft", key=str(d.id)))
        db.commit()
    return {"status": "sent" if sent else "send failed", "alerted": len(stale) if sent else 0}


def main() -> None:
    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")
    print(run(db, datetime.utcnow()))


if __name__ == "__main__":
    main()
