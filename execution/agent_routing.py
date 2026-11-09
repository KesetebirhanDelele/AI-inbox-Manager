"""
Who is told first about a new notification card: the student's AGENT, or the approver.

Kes's rule (2026-11-09): the student's primary agent (the roster sheet's Agent column) gets the approve/reject email first; the approver is the
backup when the agent has not decided within the backup time (stale_draft_alerts). A card goes to the APPROVER straight away when a person must sort
something out first, so an agent is never asked to approve a card the app is unsure about:

  no_student        the email has no student attached
  unverified        the student was created from a delivery address and is not verified
  not_on_roster     the roster sheet has no email match (unlisted, or listed by name only)
  roster_unknown    the roster sheet could not be read, so nothing can be trusted
  not_in_ghl        GHL has no contact for the student (or the lookup is ambiguous / unreachable)
  low_confidence    the email classification confidence is under CLASSIFICATION_FLOOR
  no_agent          the roster row has no agent
  agent_no_email    nobody has entered an email for that agent on the Settings page

Agent emails live in role_assignments (role "agent", scope = agent name as on the sheet), edited on the Settings page; no person is written into code.
While NO agent has an email, every card goes to the approver exactly as before, so nothing changes until agents are set up.
"""
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "execution", _ROOT / "services" / "dashboard" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

logger = logging.getLogger(__name__)

AGENT_ROLE = "agent"
CLASSIFICATION_FLOOR = 0.70          # the classifier's own "needs a person" line (classify_email.py)
APPROVER_REASON_TEXT = {
    "no_student": "no student is attached to the email",
    "unverified": "the student is not verified yet",
    "not_on_roster": "the student is not (fully) matched on the roster sheet",
    "roster_unknown": "the roster sheet could not be read",
    "not_in_ghl": "the student could not be confirmed in GHL",
    "low_confidence": "the email classification is uncertain",
    "no_agent": "the roster has no agent for this student",
    "agent_no_email": "the student's agent has no email set in Settings",
}


class Route(NamedTuple):
    to: str                 # "agent" | "approver"
    reason: str             # "" for an agent; one of APPROVER_REASON_TEXT for the approver
    agent: str = ""
    email: str = ""


def key(name: Optional[str]) -> str:
    import student_roster as sr
    return sr.norm_name(name)


def agent_emails(db) -> Dict[str, str]:
    """{normalised agent name: email} for every active agent row (the newest row per agent wins)."""
    import models as M
    out: Dict[str, str] = {}
    rows = (db.query(M.RoleAssignment).filter(M.RoleAssignment.role == AGENT_ROLE, M.RoleAssignment.active == True)   # noqa: E712
            .order_by(M.RoleAssignment.id).all())
    for r in rows:
        if (r.scope or "").strip() and (r.email or "").strip():
            out[key(r.scope)] = r.email.strip()
    return out


def agent_names(db) -> Dict[str, str]:
    """{normalised agent name: the name as typed on Settings} for every active agent row."""
    import models as M
    rows = db.query(M.RoleAssignment).filter(M.RoleAssignment.role == AGENT_ROLE, M.RoleAssignment.active == True).order_by(M.RoleAssignment.id).all()   # noqa: E712
    return {key(r.scope): r.scope.strip() for r in rows if (r.scope or "").strip() and (r.email or "").strip()}


def set_agent_email(db, agent: str, email: str, who: str = "") -> None:
    """Store (or clear, with an empty email) the address for an agent name."""
    import models as M
    k = key(agent)
    if not k:
        raise ValueError("Agent name is empty.")
    for r in db.query(M.RoleAssignment).filter(M.RoleAssignment.role == AGENT_ROLE).all():
        if key(r.scope) == k:
            r.active = False
    if (email or "").strip():
        db.add(M.RoleAssignment(role=AGENT_ROLE, scope=agent.strip(), display_name=agent.strip(), email=email.strip(), active=True, updated_by=who))
    db.commit()


def route_for_draft(db, draft, roster, emails: Dict[str, str], ghl_status: Callable[[Any], str]) -> Route:
    """Pure routing for one card. `roster` is the parsed sheet (or None), `ghl_status(student)` returns found | not_found | check | unknown."""
    import models as M
    import student_roster as sr
    event = db.get(M.InterviewEvent, draft.interview_event_id)
    student = db.get(M.Student, event.student_id) if event is not None and event.student_id else None
    if student is None:
        return Route("approver", "no_student")
    verification = db.query(M.StudentVerification).filter(M.StudentVerification.student_id == student.id).first()
    if verification is not None and verification.status != "verified":
        return Route("approver", "unverified")
    if not roster:
        return Route("approver", "roster_unknown")
    sdict = {"id": student.id, "full_name": student.full_name, "username": student.username,
             "personal_email": student.personal_email, "assigned_gmail": student.assigned_gmail}
    match = sr.match_student(sdict, roster)
    if match.how != "email":
        return Route("approver", "not_on_roster")
    try:
        ghl = ghl_status(student)
    except Exception as exc:                       # a lookup failure is a doubt, never a reason to skip the approver
        logger.warning(f"GHL status failed for routing: {exc}")
        ghl = "unknown"
    if ghl != "found":
        return Route("approver", "not_in_ghl")
    if event.confidence is not None and event.confidence < CLASSIFICATION_FLOOR:
        return Route("approver", "low_confidence")
    agent = (match.row.agent if match.row is not None else "").strip()
    if not agent:
        return Route("approver", "no_agent")
    email = emails.get(key(agent), "")
    if not email:
        return Route("approver", "agent_no_email", agent=agent)
    return Route("agent", "", agent=agent, email=email)


def route_cards(db, drafts: List[Any], roster=None, ghl_status: Optional[Callable[[Any], str]] = None) -> Dict[int, Route]:
    """{draft id: Route}. With no agent email configured at all every card is the approver's (the pre-agent behaviour), without reading the roster."""
    emails = agent_emails(db)
    if not emails:
        return {d.id: Route("approver", "") for d in drafts}
    import student_flags
    if roster is None:
        import student_roster as sr
        student_flags._load_env()                  # the roster sheet id lives in .env, which the processes read the same way the Review screen does
        roster = sr.cached_roster()
    if ghl_status is None:
        ghl_status = student_flags.ghl_status
    return {d.id: route_for_draft(db, d, roster, emails, ghl_status) for d in drafts}


def agent_of_alert(db, draft_id: int) -> str:
    """The agent a card was first sent to ("" when it went to the approver): read from the review alert's log row."""
    import models as M
    row = db.query(M.AlertLog).filter(M.AlertLog.kind == "review_needed", M.AlertLog.key == str(draft_id)).order_by(M.AlertLog.id.desc()).first()
    detail = (row.detail or "") if row is not None else ""
    return detail[len("agent:"):] if detail.startswith("agent:") else ""
