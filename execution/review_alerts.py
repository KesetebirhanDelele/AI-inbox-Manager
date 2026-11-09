"""
Tell whoever must decide when a new notification card is waiting: the student's AGENT (execution/agent_routing.py), or the APPROVER for cards that need a person first or have no agent.

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


def _line(db, draft, link: str = "") -> str:
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
    if link:
        text += f"\n    Review and approve on your phone: {link}"
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
    import agent_routing
    routes = agent_routing.route_cards(db, new)                 # no agent email set up = every card goes to the approver, as before
    approver_cards = [d for d in new if routes[d.id].to == "approver"]
    by_agent: Dict[str, List[Any]] = {}
    for d in new:
        if routes[d.id].to == "agent":
            by_agent.setdefault(routes[d.id].email, []).append(d)

    result: Dict[str, Any] = {"status": "nothing new", "alerted": 0}
    for email, cards_for in by_agent.items():                    # the student's agent first
        agent_name = routes[cards_for[0].id].agent
        body = _body(db, cards_for, email, "agent", now, env,
                     "Nothing is sent to a student until you approve. If you do not decide within the backup time, the approver is told.")
        if alerts.agent_review(email, f"{len(cards_for)} new notification card(s) for your students", body):
            for d in cards_for:
                db.add(M.AlertLog(kind="review_needed", key=str(d.id), detail=f"agent:{agent_name}"))
            db.commit()
            result["agent_alerted"] = result.get("agent_alerted", 0) + len(cards_for)

    if approver_cards:
        approver = roles.role_email(db, "approver", env)
        if not approver:
            alerts.review_needed("New cards waiting for review", f"{len(approver_cards)} new card(s) but nobody holds the approver role.")
            result.update(status="no approver assigned", new=len(approver_cards))
            return result
        body = _body(db, approver_cards, approver, "approver", now, env,
                     "Nothing is sent to a student until you approve. If nobody decides within the backup time, the backup person is told.", routes)
        if alerts.review_needed(f"{len(approver_cards)} new notification card(s) to review", body):
            for d in approver_cards:
                db.add(M.AlertLog(kind="review_needed", key=str(d.id)))
            db.commit()
            result["alerted"] = len(approver_cards)
        else:
            result["status"] = "send failed"
            return result
    result["status"] = "sent" if (result["alerted"] or result.get("agent_alerted")) else "send failed"
    return result


def _body(db, cards, recipient: str, role: str, now, env, closing: str, routes=None) -> str:
    """One email: every card with its facts and a protected approve link made for `recipient`."""
    lines: List[str] = []
    for d in cards[:MAX_LISTED]:
        try:
            import approval_links
            link = approval_links.create_link(db, d.id, role, recipient, now, env)
        except Exception as exc:                        # no link must never stop the alert; the app still works
            logger.warning(f"approval link not created for card {d.id}: {exc}")
            link = ""
        line = _line(db, d, link)
        reason = routes[d.id].reason if routes else ""
        if reason:
            import agent_routing
            line += f"\n    Needs a person first: {agent_routing.APPROVER_REASON_TEXT[reason]}."
        lines.append(line)
    more = f"\n...and {len(cards) - MAX_LISTED} more." if len(cards) > MAX_LISTED else ""
    return (f"{len(cards)} new student notification card(s) are waiting for your decision (approve, edit or reject):\n\n" + "\n".join(lines) + more +
            f"\n\nReview them here: {DASHBOARD_URL}\n"
            "Each link first emails a 6-digit code to this address, so only you can open it; then it shows the card and asks you to confirm. It works once and expires in 24 hours. "
            + closing)


def main() -> None:
    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")
    print(run(db))


if __name__ == "__main__":
    main()
