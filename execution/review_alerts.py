"""
Tell the APPROVER when a new notification card is waiting for their decision.

Runs at the end of every processing run (so the email goes out as soon as the cards exist, day or night). ONE email per run lists every new open card:
student, company, position, interview time, and the app's suggested action, with a link to the Review screen. The 2-hour BACKUP alert for cards nobody
decided is `stale_draft_alerts.py` (escalation role); this one always goes to the approver role (execution/roles.py), so changing the person is a Settings change.

  * Each card is announced once (table alert_log, kind "review_needed").
  * The first run records every card that already exists WITHOUT emailing, so switching it on never floods the approver with a backlog.
  * Only cards the Review screen shows count (execution/open_cards.py): follow-ups, rejected students and old mail are skipped.
  * Switch off on the Settings page (system_config key review_alert_enabled) without a redeploy.
  * With nobody holding the role nothing is marked, the warning is logged, and the alert goes out once someone is assigned.
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger(__name__)

ENABLED_KEY = "review_alert_enabled"
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://2-29-47-89.nip.io/review")
MAX_LISTED = 25


def enabled(db) -> bool:
    import roles
    return roles.get_setting(db, ENABLED_KEY, "on").strip().lower() not in ("off", "false", "0", "no")


def _line(db, draft) -> str:
    import models as M
    event = db.get(M.InterviewEvent, draft.interview_event_id)
    student = db.get(M.Student, event.student_id) if event and event.student_id else None
    when = " ".join(x for x in (event.interview_date, event.interview_time, event.interview_timezone) if x) if event else ""
    parts = [student.full_name if student else "Unknown student", (event.company_name if event else None) or "unnamed company"]
    if event and event.position_title:
        parts.append(event.position_title)
    text = f"- {event.sub_type if event else 'Interview'}: " + " / ".join(parts) + (f" ({when})" if when else " (no time stated)")
    try:
        from interview_followup import suggested_action
        hint = suggested_action(db, event, draft) if event else None
        if hint:
            text += f"\n    Suggested: {hint['action'].capitalize()}. {hint['text']}"
    except Exception:                                   # a hint must never stop the alert
        pass
    return text


def run(db, now: Optional[datetime] = None, alerts=None, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    import models as M
    import roles
    from escalation_engine import RoleAlerts
    from open_cards import open_review_drafts

    now = now or datetime.utcnow()
    if not enabled(db):
        return {"status": "off", "alerted": 0}
    cards = open_review_drafts(db, now)

    if db.query(M.AlertLog).filter(M.AlertLog.kind == "review_needed_baseline").first() is None:
        for d in cards:
            db.add(M.AlertLog(kind="review_needed", key=str(d.id), detail="baseline: existed before the alert was switched on"))
        db.add(M.AlertLog(kind="review_needed_baseline", key="1", detail=f"{len(cards)} existing cards recorded without an alert"))
        db.commit()
        return {"status": "baseline", "recorded": len(cards), "alerted": 0}

    already = {a.key for a in db.query(M.AlertLog).filter(M.AlertLog.kind == "review_needed").all()}
    new = [d for d in cards if str(d.id) not in already]
    if not new:
        return {"status": "nothing new", "alerted": 0}

    alerts = alerts or RoleAlerts(db=db)
    if not roles.role_email(db, "approver", env):
        alerts.review_needed("New cards waiting for review", f"{len(new)} new card(s) but nobody holds the approver role.")
        return {"status": "no approver assigned", "alerted": 0, "new": len(new)}

    lines: List[str] = [_line(db, d) for d in new[:MAX_LISTED]]
    more = f"\n...and {len(new) - MAX_LISTED} more." if len(new) > MAX_LISTED else ""
    body = (f"{len(new)} new student notification card(s) are waiting for your decision (approve, edit or reject):\n\n" + "\n".join(lines) + more +
            f"\n\nReview them here: {DASHBOARD_URL}\n"
            "Nothing is sent to a student until you approve. If nobody decides within the backup time, the backup person is told.")
    sent = alerts.review_needed(f"{len(new)} new notification card(s) to review", body)
    if sent:
        for d in new:
            db.add(M.AlertLog(kind="review_needed", key=str(d.id)))
        db.commit()
    return {"status": "sent" if sent else "send failed", "alerted": len(new) if sent else 0}


def main() -> None:
    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")
    print(run(db))


if __name__ == "__main__":
    main()
