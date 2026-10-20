"""
Students who call back about an interview.

A student who calls the Colaberry number reaches the AI receptionist (a GHL Voice AI agent). For a call about an interview the receptionist only takes the
message and says a team member will call back within one business hour; THE AI NEVER CALLS BACK. This module turns that call into work for a person:

  * poll_callbacks   reads the receptionist's newest calls from GHL (read-only), keeps the ones about an interview, finds the student (by the GHL contact's email
                     or either phone number), stores a CallbackRequest and emails the callback_owner ROLE.
  * check_overdue    emails the callback_backup ROLE (escalation_target while nobody holds it) once when a callback is still open after one business hour.
  * The dashboard shows "Callback needed" on the student's interviews until the callback owner clicks "Called back".

Nothing is written to GHL and nothing is sent to the student. Calls from before the feature was switched on are recorded as a baseline and never alerted.
Roles, not people: the addresses come from execution/roles.py.
"""
import os
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import ghl_conversations as gcv

SLA_BUSINESS_MINUTES = 60
BASELINE_KEY = "callbacks_baseline_at"
_INTERVIEW_WORDS = re.compile(r"\binterview|\bnotice\b|\bscreening\b|colaberry interview support", re.I)
_CALLBACK_WORDS = re.compile(r"call(ed|ing)? (me |us )?back|returning|return(ed)? (a |your |the )?call|missed (a )?call|got a call|received a call|"
                             r"you called|someone called|text|email|notice", re.I)
_BOT_PROMISE = re.compile(r"interview support", re.I)
_BOT_CALLBACK = re.compile(r"call (you|them|back)|will call|call you back|call them back", re.I)


def _bot_words(transcript: Any) -> str:
    return " ".join(t for s, t in gcv.call_turns(transcript) if s == "bot")


def is_interview_callback(call_log: Dict[str, Any], min_seconds: int = 5) -> bool:
    """
    True when a receptionist call was a student calling back about an interview. Deterministic, from the transcript:
      * the caller's own words mention an interview (or an interview notice) together with returning/missing a call, a text or an email, OR
      * the receptionist itself used the interview-callback wording its prompt prescribes ("a team member from Interview Support will call you back").
    A call where the caller said nothing, or that was shorter than `min_seconds`, is never a callback.
    """
    transcript = call_log.get("transcript")
    human = gcv.human_words(transcript)
    if not human.strip() or int(call_log.get("duration") or 0) < min_seconds:
        return False
    if _INTERVIEW_WORDS.search(human) and _CALLBACK_WORDS.search(human):
        return True
    bot = _bot_words(transcript)
    return bool(_BOT_PROMISE.search(bot) and _BOT_CALLBACK.search(bot))


def _tail(phone: Optional[str]) -> str:
    return re.sub(r"\D", "", phone or "")[-10:]


def find_student(db, caller_number: str, contact: Optional[Dict[str, Any]]):
    """The student behind a call: the GHL contact's email (personal email or assigned Gmail), else either phone number. None when unsure."""
    import models as M
    emails = {(contact or {}).get("email", "").strip().lower()} - {""}
    tails = {t for t in (_tail(caller_number), _tail((contact or {}).get("phone"))) if len(t) == 10}
    matches = {}
    for student in db.query(M.Student).all():
        mine = {(student.personal_email or "").strip().lower(), (student.assigned_gmail or "").strip().lower()} - {""}
        if emails & mine or (tails and _tail(student.phone_number) in tails):
            matches[student.id] = student
    return next(iter(matches.values())) if len(matches) == 1 else None


def due_at(received_at: datetime, hours=None) -> datetime:
    from business_hours import BusinessHours, add_business_minutes
    return add_business_minutes(received_at, SLA_BUSINESS_MINUTES, hours or BusinessHours.from_env())


def _baseline(db, now: datetime) -> datetime:
    import models as M
    row = db.query(M.SystemConfig).filter(M.SystemConfig.key == BASELINE_KEY).first()
    if row is not None and row.value:
        return datetime.fromisoformat(row.value)
    db.add(M.SystemConfig(key=BASELINE_KEY, value=now.isoformat()))
    db.commit()
    return now


def _fmt(dt: Optional[datetime], hours) -> str:
    from business_hours import _local
    return _local(dt, hours.tz if hours else "America/Chicago").strftime("%a %b %d, %I:%M %p") if dt else "unknown time"


def context_lines(db, student, req, hours, max_notices: int = 8) -> List[str]:
    """
    What the person calling the student back needs to know, in plain text: how to reach them, why they rang, their interviews, what we have already
    told them (and what they answered), and any earlier callback. Read-only; every list is capped; reply text is shortened.
    """
    import models as M
    lines: List[str] = []
    if req.said:
        lines.append(f'Why they called (their own words): "{req.said[:300]}"')
    else:
        lines.append("Why they called: the receptionist did not record their words.")
    if student is not None:
        reach = [x for x in (student.phone_number, student.personal_email, student.assigned_gmail) if x]
        lines.append("How to reach them: " + (", ".join(dict.fromkeys(reach)) if reach else "no details on file") + f" (they called from {req.caller_number or 'an unknown number'})")
        events = (db.query(M.InterviewEvent).filter(M.InterviewEvent.student_id == student.id)
                  .order_by(M.InterviewEvent.id.desc()).limit(3).all())
        if events:
            lines.append("Their recent interviews:")
        for ev in events:
            when = " ".join(x for x in (str(ev.interview_date or ""), str(ev.interview_time or ""), ev.interview_timezone or "") if x)
            email = db.get(M.Email, ev.email_id) if ev.email_id else None
            lines.append(f"  - {ev.company_name or 'unknown company'}" + (f", {ev.position_title}" if ev.position_title else "")
                         + f" ({ev.sub_type or 'interview'}" + (f", {when}" if when else ", time not stated")
                         + (f", email received {_fmt(email.received_date, hours)}" if email is not None else "") + ")")
        notices: List[tuple] = []
        for seq in db.query(M.NotificationSequence).filter(M.NotificationSequence.student_id == student.id).all():
            for at in db.query(M.NotificationAttempt).filter(M.NotificationAttempt.sequence_id == seq.id,
                                                             M.NotificationAttempt.sent_at.isnot(None)).all():
                notices.append((at.sent_at, f"we sent a {at.channel} ({at.status})"))
            for msg in db.query(M.NotificationInbound).filter(M.NotificationInbound.sequence_id == seq.id).all():
                who = "they replied" if (msg.direction or "inbound") == "inbound" else "we wrote"
                notices.append((msg.received_at or msg.created_at, f'{who} by {msg.channel}: "{(msg.text or "")[:160]}"'))
            if seq.ack_at:
                notices.append((seq.ack_at, f"they confirmed by {seq.ack_channel or 'a reply'}"))
        notices = sorted((n for n in notices if n[0] is not None), key=lambda n: n[0])[-max_notices:]
        if notices:
            lines.append("What we have already told them, and their answers:")
            lines.extend(f"  - {_fmt(when, hours)}: {what}" for when, what in notices)
        else:
            lines.append("What we have already told them: nothing was sent through the app (any earlier contact was by hand).")
    else:
        lines.append("We could not match this number to a student, so there is no interview or notice history. Ask them who they are.")
    earlier = db.query(M.CallbackRequest).filter(M.CallbackRequest.id != req.id, M.CallbackRequest.caller_number == req.caller_number,
                                                 M.CallbackRequest.caller_number.isnot(None)).count() if req.caller_number else 0
    if earlier:
        lines.append(f"Earlier callbacks from this number: {earlier}.")
    return lines


def _describe(db, student, said: str, received_at: datetime, number: str, hours) -> tuple:
    import models as M
    from business_hours import _local
    who = student.full_name if student else "an unknown caller"
    req = SimpleNamespace(id=0, said=said, caller_number=number)
    deadline = _local(due_at(received_at, hours), (hours.tz if hours else "America/Chicago")) if hours else None
    when = _local(received_at, hours.tz if hours else "America/Chicago").strftime("%a %b %d, %I:%M %p")
    body = (f"{who} called the Colaberry number about an interview ({when} {hours.tz if hours else 'Central'}).\n\n"
            + "\n".join(context_lines(db, student, req, hours)) + "\n\nPlease call them back"
            + (f" by {deadline.strftime('%a %I:%M %p')} (one business hour, working hours)" if deadline else " within one business hour during working hours")
            + ". The AI receptionist only took the message and does not call back.\n"
            "When you have called, click \"Called back\" in the approval screen so this clears.")
    return who, body


def poll_callbacks(db, client, now: datetime, alerts, agent_id: str, hours=None, env: Optional[Dict[str, str]] = None) -> Dict[str, int]:
    """Read the receptionist's newest calls, store the interview callbacks, email the callback owner. Idempotent: a call is handled once."""
    import models as M
    from business_hours import BusinessHours
    hours = hours or BusinessHours.from_env(env)
    baseline = _baseline(db, now)
    result = {"read": 0, "callbacks": 0, "alerted": 0, "before_baseline": 0}
    seen = {r.ghl_call_id for r in db.query(M.CallbackRequest.ghl_call_id).all()}
    for raw in client.voice_ai_agent_calls(agent_id):
        call = gcv.parse_call_log(raw)
        if call is None or call.id in seen or call.created_at is None:
            continue
        result["read"] += 1
        if call.created_at <= baseline:
            result["before_baseline"] += 1
            continue
        if not is_interview_callback(raw):
            continue
        contact = None
        if raw.get("contactId"):
            try:
                contact = client.get_contact(raw["contactId"])
            except Exception:                         # a failed lookup must not lose the callback
                contact = None
        number = raw.get("fromNumber") or ""
        student = find_student(db, number, contact)
        req = M.CallbackRequest(ghl_call_id=call.id, contact_id=raw.get("contactId"), student_id=student.id if student else None,
                                caller_number=number, received_at=call.created_at, duration_seconds=call.duration,
                                said=call.human_words[:1000], status="open")
        db.add(req)
        db.commit()
        result["callbacks"] += 1

    # alert for every open callback that has not been announced yet (also retries one stored while nobody held the callback_owner role)
    for req in db.query(M.CallbackRequest).filter(M.CallbackRequest.status == "open", M.CallbackRequest.alerted_at.is_(None)).all():
        student = db.get(M.Student, req.student_id) if req.student_id else None
        who, body = _describe(db, student, req.said or "", req.received_at, req.caller_number or "", hours)
        if alerts.callback_needed(f"Callback needed: {who}", body):
            req.alerted_at = now
            db.commit()
            result["alerted"] += 1
    return result


def check_overdue(db, now: datetime, alerts, hours=None, env: Optional[Dict[str, str]] = None) -> int:
    """Email the callback backup (else the escalation role) once for each callback still open after one business hour. Returns how many were reported."""
    import models as M
    from business_hours import BusinessHours, business_minutes_between
    hours = hours or BusinessHours.from_env(env)
    late = [r for r in db.query(M.CallbackRequest).filter(M.CallbackRequest.status == "open", M.CallbackRequest.sla_alerted_at.is_(None)).all()
            if business_minutes_between(r.received_at, now, hours) >= SLA_BUSINESS_MINUTES]
    if not late:
        return 0
    blocks = []
    for n, r in enumerate(late, 1):
        student = db.get(M.Student, r.student_id) if r.student_id else None
        waited = business_minutes_between(r.received_at, now, hours) / 60
        blocks.append(f"{n}) {student.full_name if student else 'Unknown caller'} ({r.caller_number or 'no number'}), called {_fmt(r.received_at, hours)} "
                      f"({waited:.1f} business hours ago)\n" + "\n".join("   " + l for l in context_lines(db, student, r, hours)))
    body = ("These students called back about an interview and have not been called back within one business hour. "
            "Below is why each one called and what we have already told them, so you can call with the full picture.\n\n"
            + "\n\n".join(blocks) +
            "\n\nPlease call them yourself today, then reply \"called back\" so it can be closed. The callback owner has already been told. "
            "You receive this because you are the callback backup.")
    if alerts.callback_overdue(f"{len(late)} interview callback(s) overdue", body):
        for r in late:
            r.sla_alerted_at = now
        db.commit()
        return len(late)
    return 0


def main() -> None:
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for p in (root / "execution", root / "services" / "dashboard" / "api"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from process_inbox_auto import get_db_session
    import ghl_client
    from escalation_engine import RoleAlerts

    agent = (os.getenv("GHL_RECEPTIONIST_AGENT_ID") or "").strip()
    cfg = ghl_client.GhlConfig.from_env()
    if not agent or not cfg.can_read:
        print("callbacks: not configured (GHL_RECEPTIONIST_AGENT_ID, GHL_API_KEY, GHL_LOCATION_ID)")
        return
    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")
    now = datetime.utcnow()
    alerts = RoleAlerts(db=db)
    out = poll_callbacks(db, ghl_client.GhlClient(cfg), now, alerts, agent)
    out["overdue_reported"] = check_overdue(db, now, alerts)
    print(out)


if __name__ == "__main__":
    main()
