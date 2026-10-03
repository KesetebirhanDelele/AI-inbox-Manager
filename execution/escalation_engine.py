"""
Student notification escalation engine.

Starts when Rob approves a draft, then keeps contacting the student until they acknowledge or
Rob closes it. The schedule and quiet-hours rules live in escalation_schedule.py, message
delivery in notify_channels.py, and the reading of free-text replies in reply_analysis.py.
Design and decisions: directives/student-notification-escalation.md.

Rules worth knowing:
  * Telling Rob and stopping are different things. Rob is told when day 1 goes unanswered and
    when the sequence ends; neither of those stops anything. Only an acknowledgement or Rob
    closing it does.
  * A failed attempt is recorded, never silently retried, and never blocks later attempts.
  * Nothing here sends to a student unless the chosen channel is a real one. The default is dry_run.
"""

import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import escalation_schedule as sched
import notify_channels as nc
import reply_analysis as ra

logger = logging.getLogger(__name__)

PHONE_CHANNELS = sched.PHONE_CHANNELS


def _m():
    """The ORM models, imported late so importing this module never opens a database."""
    import models
    return models


# ── starting ─────────────────────────────────────────────────────────────────

def start_sequence(db, draft, student, now: datetime, started_by: Optional[str] = None):
    """
    Create the sequence and every planned attempt for an approved draft. Safe to call twice: a
    draft that already has a sequence returns it unchanged. Attempts the student cannot receive
    (no phone, no email) are recorded as skipped so the gap is visible.
    """
    M = _m()
    existing = db.query(M.NotificationSequence).filter(M.NotificationSequence.draft_id == draft.id).first()
    if existing is not None:
        return existing

    phone = getattr(student, "phone_number", None)
    tz_name, tz_source = sched.timezone_for_phone(phone)
    seq = M.NotificationSequence(
        draft_id=draft.id,
        student_id=getattr(student, "id", None),
        status="active",
        timezone=tz_name,
        timezone_source=tz_source,
        started_at=now,
        started_by=started_by,
        ack_token=secrets.token_urlsafe(24),
    )
    db.add(seq)
    db.flush()

    has_phone = len("".join(ch for ch in (phone or "") if ch.isdigit())) >= 10
    has_email = bool((draft.recipient_email or "").strip())
    for planned in sched.build_plan(now, tz_name):
        attempt = M.NotificationAttempt(
            sequence_id=seq.id,
            channel=planned.channel,
            step=planned.step,
            planned_for=planned.planned_for,
            scheduled_for=sched.scheduled_time(planned, tz_name),
            status="pending",
        )
        if planned.channel in PHONE_CHANNELS and not has_phone:
            attempt.status, attempt.detail = "skipped", "student has no phone number"
        elif planned.channel == "email" and not has_email:
            attempt.status, attempt.detail = "skipped", "draft has no recipient email"
        db.add(attempt)
    db.commit()
    return seq


# ── stopping ─────────────────────────────────────────────────────────────────

def _cancel_pending(seq, reason: str) -> int:
    n = 0
    for a in seq.attempts:
        if a.status == "pending":
            a.status, a.detail = "cancelled", reason
            n += 1
    return n


def acknowledge(db, seq, channel: str, kind: str, now: datetime) -> bool:
    """Record an acknowledgement and stop the sequence. False if it was already stopped."""
    if seq.status != "active":
        return False
    seq.status = "acknowledged"
    seq.ack_at, seq.ack_channel, seq.ack_kind = now, channel, kind
    _cancel_pending(seq, "acknowledged")
    db.commit()
    return True


def close_sequence(db, seq, by: str, now: datetime) -> bool:
    """Rob closes the sequence himself (for example the student told him directly)."""
    if seq.status != "active":
        return False
    seq.status, seq.closed_by, seq.closed_at = "closed", by, now
    _cancel_pending(seq, f"closed by {by}")
    db.commit()
    return True


def acknowledge_by_token(db, token: str, now: datetime) -> str:
    """The email's "I got this" link. Returns acknowledged | already | unknown."""
    M = _m()
    seq = db.query(M.NotificationSequence).filter(M.NotificationSequence.ack_token == (token or "")).first()
    if seq is None:
        return "unknown"
    if seq.status == "active":
        acknowledge(db, seq, "email", "explicit", now)
        return "acknowledged"
    if seq.ack_at is None:                      # closed or ended earlier, but the student did get it
        seq.ack_at, seq.ack_channel, seq.ack_kind = now, "email", "explicit"
        db.commit()
    return "already"


# ── alerts to Rob ────────────────────────────────────────────────────────────

class RobAlerts:
    """
    Messages to Rob. With ROB_ALERT_EMAIL set they are emailed; without it they are only logged,
    so nothing is lost or silently dropped. Rob's preferred channel is still to be confirmed.
    """

    def __init__(self, to: Optional[str] = None, send_fn=None):
        self.to = to if to is not None else os.getenv("ROB_ALERT_EMAIL", "").strip()
        self._send_fn = send_fn
        self.sent: List[str] = []

    def _notify(self, subject: str, body: str) -> bool:
        self.sent.append(subject)
        if not self.to:
            logger.warning(f"[Rob alert, ROB_ALERT_EMAIL not set] {subject}: {body}")
            return False
        send = self._send_fn
        if send is None:
            from send_notification import send_email
            send = send_email
        result = send(recipient_email=self.to, subject=f"[InboxGenius] {subject}", body=body)
        return result.get("status") == "sent"

    def no_response(self, seq, student_name: str) -> bool:
        return self._notify(
            f"{student_name} has not responded to their interview notice",
            f"{student_name} has not acknowledged the interview notice after the first day's attempts. "
            f"Automated follow-ups continue once a day for up to 3 more days; please follow up personally "
            f"if you can. You can close it in the dashboard when they confirm.")

    def ended(self, seq, student_name: str) -> bool:
        return self._notify(
            f"Follow-ups ended: {student_name} never acknowledged",
            f"The automated sequence for {student_name} has ended with no acknowledgement. Please contact them directly.")

    def student_reply(self, seq, student_name: str, text: str, outcome: str) -> bool:
        return self._notify(
            f"{student_name} replied and may need help ({outcome})",
            f"{student_name} replied: \"{text[:300]}\"\nThe system read this as '{outcome}', so follow-ups "
            f"were not stopped. Please look at it.")

    def opted_out(self, seq, student_name: str) -> bool:
        return self._notify(
            f"{student_name} opted out (STOP)",
            f"{student_name} replied STOP. All automated contact has been stopped. Please reach them another way.")


# ── the tick ─────────────────────────────────────────────────────────────────

@dataclass
class TickReport:
    sent: int = 0
    dry_run: int = 0
    failed: int = 0
    skipped: int = 0
    deferred: int = 0
    rob_no_response: int = 0
    ended: int = 0
    details: List[str] = field(default_factory=list)


def _context(db, seq, attempt, ack_base_url: str, now: datetime) -> nc.SendContext:
    M = _m()
    draft = db.get(M.NotificationDraft, seq.draft_id)
    event = db.get(M.InterviewEvent, draft.interview_event_id) if draft else None
    student = db.get(M.Student, seq.student_id) if seq.student_id else None
    ack_url = f"{ack_base_url.rstrip('/')}/{seq.ack_token}" if ack_base_url else ""
    return nc.SendContext(attempt=attempt, sequence=seq, draft=draft, event=event, student=student,
                          ack_url=ack_url, now=now, db=db)


def _student_name(db, seq) -> str:
    M = _m()
    student = db.get(M.Student, seq.student_id) if seq.student_id else None
    return (getattr(student, "full_name", None) or "A student")


def _phone_tail(student) -> str:
    return "".join(c for c in str(getattr(student, "phone_number", "") or "") if c.isdigit())[-10:]


def record_opt_out(db, seq, channel: str, now: datetime) -> None:
    """Remember that this student asked us to stop on `channel` (sms | call | email). Idempotent."""
    M = _m()
    student = db.get(M.Student, seq.student_id) if seq.student_id else None
    tail = _phone_tail(student)
    if len(tail) != 10 or channel not in ("sms", "call", "email"):
        return
    exists = db.query(M.NotificationOptOut).filter_by(phone_tail=tail, channel=channel).first()
    if not exists:
        db.add(M.NotificationOptOut(phone_tail=tail, channel=channel, source=f"stop_{'text' if channel == 'sms' else channel}",
                                    sequence_id=seq.id, created_at=now))


def _held_attempt_collides(attempt, siblings) -> bool:
    """A quiet-hours-held call/text is skipped if the same channel goes out within 3 hours anyway."""
    others = []
    for s in siblings:
        if s.id == attempt.id or s.channel != attempt.channel:
            continue
        if s.status in ("sent", "dry_run") and s.sent_at:
            others.append(s.sent_at)
        elif s.status == "pending":
            others.append(s.scheduled_for)
    return sched.collides_with_neighbour(attempt.scheduled_for, others)


def tick(db, now: datetime, channels: Dict[str, Any], alerts: Optional[RobAlerts] = None,
         ack_base_url: str = "") -> TickReport:
    """Send every attempt that is due, send Rob's alerts, and end sequences that have run out."""
    M = _m()
    alerts = alerts or RobAlerts()
    report = TickReport()
    sequences = db.query(M.NotificationSequence).filter(M.NotificationSequence.status == "active").all()
    for seq in sequences:
        due = sorted((a for a in seq.attempts if a.status == "pending" and a.scheduled_for <= now),
                     key=lambda a: a.scheduled_for)
        for attempt in due:
            held = attempt.scheduled_for != attempt.planned_for
            if held and attempt.channel in PHONE_CHANNELS and _held_attempt_collides(attempt, seq.attempts):
                attempt.status, attempt.detail = "skipped", "held by quiet hours; same channel is due within 3 hours"
                db.commit()
                report.skipped += 1
                continue
            try:
                result = channels[attempt.channel].send(_context(db, seq, attempt, ack_base_url, now))
            except Exception as exc:                # one bad attempt must never stop the rest
                logger.error(f"Attempt {attempt.id} ({attempt.channel}) crashed: {exc}")
                result = nc.ChannelResult(nc.FAILED, detail=f"crashed: {exc}"[:300])
            if result.status == nc.DEFERRED:
                # Not now (for example the daily text budget is used): stay pending and move to the
                # retry time, kept outside quiet hours. It is not a failure and not a send.
                retry = result.retry_at or (now + timedelta(hours=1))
                attempt.scheduled_for = sched.release_time(retry, seq.timezone, attempt.channel)
                attempt.detail = result.detail
                db.commit()
                report.deferred += 1
                continue
            attempt.status = result.status
            attempt.detail = result.detail
            attempt.provider_id = result.provider_id
            attempt.segments = result.segments
            if result.status in (nc.SENT, nc.DRY_RUN):
                attempt.sent_at = now
            if result.status == nc.SENT and attempt.channel == "email":
                draft = db.get(M.NotificationDraft, seq.draft_id)
                if draft is not None and draft.email_status != "sent":
                    draft.email_status, draft.sent_at = "sent", now      # keep the dashboard honest
            db.commit()
            if result.status == nc.SENT:
                report.sent += 1
            elif result.status == nc.DRY_RUN:
                report.dry_run += 1
            elif result.status == nc.SKIPPED:
                report.skipped += 1
                report.details.append(f"seq {seq.id} {attempt.channel}/{attempt.step}: skipped, {result.detail}")
            else:
                report.failed += 1
                report.details.append(f"seq {seq.id} {attempt.channel}/{attempt.step}: {result.detail}")

        if seq.rob_day1_alert_at is None and now >= sched.rob_no_response_due(seq.started_at):
            alerts.no_response(seq, _student_name(db, seq))
            seq.rob_day1_alert_at = now
            db.commit()
            report.rob_no_response += 1

        still_pending = any(a.status == "pending" for a in seq.attempts)
        last = max((a.scheduled_for for a in seq.attempts), default=seq.started_at)
        if not still_pending and now >= last + sched.ENDED_ALERT_AFTER_LAST_ATTEMPT:
            seq.status = "exhausted"
            seq.rob_ended_alert_at = now
            alerts.ended(seq, _student_name(db, seq))
            db.commit()
            report.ended += 1
    return report


# ── inbound replies ──────────────────────────────────────────────────────────

def _digits(phone: Optional[str]) -> str:
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else d


def _active_sequences_for_phone(db, phone: str):
    M = _m()
    wanted = _digits(phone)
    if not wanted:
        return []
    students = [s for s in db.query(M.Student).all() if _digits(s.phone_number) == wanted]
    ids = [s.id for s in students]
    if not ids:
        return []
    return (db.query(M.NotificationSequence)
            .filter(M.NotificationSequence.student_id.in_(ids), M.NotificationSequence.status == "active")
            .order_by(M.NotificationSequence.started_at.desc()).all())


def _interview_summary(db, seq) -> str:
    M = _m()
    draft = db.get(M.NotificationDraft, seq.draft_id)
    event = db.get(M.InterviewEvent, draft.interview_event_id) if draft else None
    if event is None:
        return "an interview"
    parts = [getattr(event, "company_name", None), getattr(event, "position_title", None),
             getattr(event, "interview_date", None)]
    return ", ".join(str(p) for p in parts if p) or "an interview"


def handle_inbound_reply(db, phone: str, text: str, channel: str, now: datetime,
                         alerts: Optional[RobAlerts] = None, completion_fn=None,
                         env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    A student replied by text (or a call transcript was posted back). Plain rules first (YES, STOP),
    then the AI reading. Returns what happened, for the caller to log.
    """
    M = _m()
    alerts = alerts or RobAlerts()
    sequences = _active_sequences_for_phone(db, phone)
    if not sequences:
        return {"handled": False, "reason": "no active notification for this number"}

    return handle_reply_for_sequences(db, sequences, text, channel, now, alerts, completion_fn, env)


def handle_reply_for_sequences(db, sequences, text: str, channel: str, now: datetime,
                               alerts: Optional[RobAlerts] = None, completion_fn=None,
                               env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Decide what one student reply means for these (active) sequences: plain rules first (YES, STOP),
    then the AI reading, which only ever stops a sequence in live mode. Shared by the webhook and the poller.
    """
    M = _m()
    alerts = alerts or RobAlerts()
    rule = ra.classify_by_rule(text)
    if rule == "stop":
        for seq in sequences:
            seq.status, seq.closed_by, seq.closed_at = "opted_out", "student", now
            _cancel_pending(seq, "student replied STOP")
            record_opt_out(db, seq, channel, now)
            alerts.opted_out(seq, _student_name(db, seq))
        db.commit()
        return {"handled": True, "action": "opted_out", "sequences": len(sequences)}
    if rule == "yes":
        for seq in sequences:
            acknowledge(db, seq, channel, "explicit", now)
        return {"handled": True, "action": "acknowledged", "kind": "explicit", "sequences": len(sequences)}

    seq = sequences[0]                                # the most recent open notice
    analysis = ra.analyze_reply(text, _interview_summary(db, seq), completion_fn=completion_fn)
    mode = ra.analysis_mode(now, env)
    stops = ra.may_stop_sequence(analysis, mode)
    db.add(M.ReplyAnalysis(sequence_id=seq.id, channel=channel, message_text=text[:2000],
                           outcome=analysis.outcome, confidence=analysis.confidence,
                           reason=analysis.reason, shadow=(mode == "shadow"), acted=stops))
    db.commit()
    if stops:
        acknowledge(db, seq, "ai", "ai_inferred", now)
        return {"handled": True, "action": "acknowledged", "kind": "ai_inferred", "mode": mode}
    if analysis.outcome != "understood":
        alerts.student_reply(seq, _student_name(db, seq), text, analysis.outcome)
    return {"handled": True, "action": "recorded", "outcome": analysis.outcome, "mode": mode}


# ── reading replies from the student's GHL Conversations ─────────────────────

@dataclass
class PollReport:
    sequences: int = 0
    new_messages: int = 0
    stopped: int = 0
    errors: int = 0
    details: List[str] = field(default_factory=list)


def _contact_id_for(seq) -> Optional[str]:
    """The GHL contact id our last real send used (the ghl channel stores it as the attempt's provider id)."""
    sent = [a for a in seq.attempts if a.status == "sent" and a.provider_id]
    sent.sort(key=lambda a: a.sent_at or datetime.min, reverse=True)
    return sent[0].provider_id if sent else None


def _record_inbound(db, seq, message, handled_as: str, text: Optional[str] = None) -> None:
    M = _m()
    db.add(M.NotificationInbound(sequence_id=seq.id, ghl_message_id=message.id, channel=message.channel,
                                 direction=message.direction, text=(text if text is not None else message.text)[:2000],
                                 received_at=message.received_at, handled_as=handled_as))
    db.commit()


def _handled_as(result: Dict[str, Any]) -> str:
    action = result.get("action")
    if action == "opted_out":
        return "stop_rule"
    if action == "acknowledged":
        return "yes_rule" if result.get("kind") == "explicit" else "ai"
    return "ai"


def poll_replies(db, now: datetime, client, alerts: Optional[RobAlerts] = None, completion_fn=None,
                 env: Optional[Dict[str, str]] = None) -> PollReport:
    """
    Read each active sequence's GHL Conversations (texts, emails) and Voice AI call logs for the student's
    replies, and act on them exactly as a webhook reply would. Each GHL message or call is handled once
    (notification_inbound).

    Calls: only the student's side ("human:" lines) of the call-log transcript is analysed, and only when the
    call lasted long enough and the student actually spoke (NOTIFY_CALL_MIN_SECONDS, default 10).
    GHL_VOICE_AGENT_ID restricts this to the outbound agent's calls.
    """
    import ghl_client
    import ghl_conversations as gcv

    M = _m()
    env = os.environ if env is None else env
    agent_id = (env.get("GHL_VOICE_AGENT_ID") or "").strip() or None
    try:
        call_min_seconds = int(env.get("NOTIFY_CALL_MIN_SECONDS") or gcv.DEFAULT_MIN_CALL_SECONDS)
    except ValueError:
        call_min_seconds = gcv.DEFAULT_MIN_CALL_SECONDS
    alerts = alerts or RobAlerts()
    report = PollReport()

    # One student can have several open notices (two interviews). Their conversation is the same, so group the
    # open sequences by GHL contact and handle each message ONCE for the whole group.
    groups: Dict[str, List[Any]] = {}
    for seq in db.query(M.NotificationSequence).filter(M.NotificationSequence.status == "active").all():
        contact_id = _contact_id_for(seq)
        if contact_id:                                 # no id = nothing real has been sent to this student yet
            groups.setdefault(contact_id, []).append(seq)

    for contact_id, group in groups.items():
        group.sort(key=lambda q: q.started_at, reverse=True)           # newest notice first
        report.sequences += len(group)
        ids = [q.id for q in group]
        since = min(q.started_at for q in group)
        seen = {r.ghl_message_id for r in db.query(M.NotificationInbound.ghl_message_id)
                .filter(M.NotificationInbound.sequence_id.in_(ids)).all()}
        subjects = [getattr(db.get(M.NotificationDraft, q.draft_id), "email_subject", None) for q in group]
        markers = [q.ack_token for q in group] + subjects

        try:
            messages = gcv.fetch_new_messages(client, contact_id, since, seen, markers)
        except ghl_client.GhlError as exc:
            report.errors += 1
            report.details.append(f"contact {contact_id}: could not read conversations: {exc}")
            messages = []
        try:
            calls = gcv.fetch_new_calls(client, contact_id, since, seen, agent_id)
        except ghl_client.GhlError as exc:
            report.errors += 1
            report.details.append(f"contact {contact_id}: could not read call logs: {exc}")
            calls = []

        for message in messages:
            active = [q for q in group if q.status == "active"]
            if not active:
                break                                  # an earlier message already stopped everything
            primary = active[0]                        # the newest open notice carries the record
            report.new_messages += 1
            if not message.text:
                _record_inbound(db, primary, message, "echo")
                continue
            result = handle_reply_for_sequences(db, active, message.text, message.channel, now, alerts,
                                                completion_fn, env)
            _record_inbound(db, primary, message, _handled_as(result))
            if result.get("action") in ("acknowledged", "opted_out"):
                report.stopped += 1

        for call in calls:
            active = [q for q in group if q.status == "active"]
            if not active:
                break
            primary = active[0]
            report.new_messages += 1
            record = _CallRecord(call)
            if not gcv.reached_a_person(call, call_min_seconds):
                _record_inbound(db, primary, record, "call_recorded", text="")      # no conversation to read
                continue
            # a clear spoken "don't call me again" or a plain yes to the agent's confirmation question is decided by
            # rule (same as a STOP / YES text); anything else goes to the normal reading with the student's words
            rule_text = {"stop": "stop", "confirmed": "yes"}.get(call.outcome) or call.human_words
            result = handle_reply_for_sequences(db, active, rule_text, "call", now, alerts, completion_fn, env)
            _record_inbound(db, primary, record, _handled_as(result), text=call.human_words)
            if result.get("action") in ("acknowledged", "opted_out"):
                report.stopped += 1
    return report


class _CallRecord:
    """Adapts a Voice AI call to the shape _record_inbound writes."""
    channel, direction, text = "call", "outbound", ""

    def __init__(self, call):
        self.id, self.received_at = call.record_id, call.created_at
