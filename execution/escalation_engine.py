"""
Student notification escalation engine.

Starts when the approver approves a draft, then keeps contacting the student until they acknowledge or
the approver closes it. The schedule and quiet-hours rules live in escalation_schedule.py, message
delivery in notify_channels.py, and the reading of free-text replies in reply_analysis.py.
Design and decisions: directives/student-notification-escalation.md.

Rules worth knowing:
  * Telling the approver and stopping are different things. the approver is told when day 1 goes unanswered and
    when the sequence ends; neither of those stops anything. Only an acknowledgement or the approver
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
    interview_utc, time_known = _interview_utc(db, draft, tz_name)
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
    # Our record may lack a phone while the student's GHL contact has one (the contact is found by email), so a
    # student with ANY way to be found (phone, personal email or assigned Gmail) keeps their call and text attempts.
    can_be_found = has_phone or bool((getattr(student, "personal_email", None) or "").strip())         or bool((getattr(student, "assigned_gmail", None) or "").strip())
    has_email = bool((draft.recipient_email or "").strip()) or can_be_found
    plan = sched.build_plan(now, tz_name, interview_utc, time_known)
    if interview_utc is not None and not plan:
        seq.status = "interview_passed"                  # the interview is already over: nothing is planned
    for planned in plan:
        if interview_utc is not None and sched.scheduled_time(planned, tz_name) >= interview_utc:
            continue                                     # a quiet-hours hold must never push an attempt past the interview
        attempt = M.NotificationAttempt(
            sequence_id=seq.id,
            channel=planned.channel,
            step=planned.step,
            planned_for=planned.planned_for,
            scheduled_for=sched.scheduled_time(planned, tz_name),
            status="pending",
        )
        if planned.channel in PHONE_CHANNELS and not can_be_found:
            attempt.status, attempt.detail = "skipped", "student has no phone number, email or Gmail on file"
        elif planned.channel == "email" and not has_email:
            attempt.status, attempt.detail = "skipped", "student has no email address on file (the draft has no recipient email)"
        db.add(attempt)
    db.commit()
    return seq


# ── stopping ─────────────────────────────────────────────────────────────────

def _interview_utc(db, draft, tz_name: str):
    """(naive UTC interview time, whether the time of day is known) for a draft's interview, or (None, False) when no usable date is stored."""
    M = _m()
    event = db.get(M.InterviewEvent, draft.interview_event_id) if getattr(draft, "interview_event_id", None) else None
    if event is None:
        return None, False
    return sched.interview_when(getattr(event, "interview_date", None), getattr(event, "interview_time", None),
                                getattr(event, "interview_timezone", None), tz_name)


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
    """the approver closes the sequence (for example the student told them directly)."""
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


# ── alerts to whoever holds a role (execution/roles.py) ──────────────────────

class RoleAlerts:
    """
    Messages to the person who holds a ROLE (approver for follow-ups on a student, callback_owner, escalation_target for stale drafts).
    The address comes from the role assignment in the database (Settings page) at send time, so no person is written into the code.
    With nobody assigned the alert is only logged, never silently dropped. `to` forces one address for every role (tests).
    """

    def __init__(self, to: Optional[str] = None, send_fn=None, db=None):
        self.to = to
        self.db = db
        self._send_fn = send_fn
        self.sent: List[str] = []

    def address_for(self, role: str) -> str:
        if self.to is not None:
            return self.to
        import roles
        return roles.role_email(self.db, role)

    def _notify(self, subject: str, body: str, role: str = "approver", to: Optional[str] = None, cc: str = "", reply_to: str = "") -> bool:
        self.sent.append(subject)
        import roles
        if self.to is None and not roles.staff_alerts_on(self.db):
            logger.info(f"[staff email alerts are OFF in Settings] not sent: {subject}")
            return False
        to = self.to if self.to is not None else (to or self.address_for(role))
        if not to:
            logger.warning(f"[alert for role {role}, nobody assigned] {subject}: {body}")
            return False
        send = self._send_fn
        if send is None:
            from send_notification import send_email
            send = send_email
        # bcc="": these are internal alerts to the person holding a role, not student mail, so they are NOT copied to the interviews mailbox
        extra = {k: v for k, v in (("cc", cc), ("reply_to", reply_to)) if v}          # only when used, so plain alerts are sent exactly as before
        result = send(recipient_email=to, subject=f"[InboxGenius] {subject}", body=body, bcc="", **extra)
        return result.get("status") == "sent"

    def review_needed(self, subject: str, body: str) -> bool:
        return self._notify(subject, body, role="approver")

    def ghl_contact_request(self, subject: str, body: str, cc: str, reply_to: str) -> bool:
        """To the GHL contact owner, the student's agent copied and replies going to the agent: please put this student's email in GHL."""
        return self._notify(subject, body, role="ghl_contact_owner", cc=cc, reply_to=reply_to)

    def agent_review(self, to: str, subject: str, body: str) -> bool:
        """To one student's AGENT (address from the Settings page agent list): a new card for their student."""
        return self._notify(subject, body, role="agent", to=to)

    def stale_for_approver(self, subject: str, body: str) -> bool:
        """The agent did not decide within the backup time: the approver is told (a card the approver got first goes to stale_drafts, the escalation role)."""
        return self._notify(subject, body, role="approver")

    def stale_drafts(self, subject: str, body: str) -> bool:
        return self._notify(subject, body, role="escalation_target")

    def callback_overdue(self, subject: str, body: str) -> bool:
        """To the callback backup; while nobody holds that role, to the escalation role (where overdue callbacks always went)."""
        return self._notify(subject, body, role="callback_backup" if self.address_for("callback_backup") else "escalation_target")

    def callback_needed(self, subject: str, body: str) -> bool:
        return self._notify(subject, body, role="callback_owner")

    def student_check(self, subject: str, body: str) -> bool:
        """To the student checker: a candidate who is not on the roster sheet or not in GHL needs verifying and a call."""
        return self._notify(subject, body, role="student_checker")

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

    def cannot_reach(self, seq, student_name: str, reason: str) -> bool:
        return self._notify(
            f"Cannot reach {student_name}: their contact details need fixing",
            f"The interview notice for {student_name} could not be delivered: {reason}. "
            f"A student may have changed their email or phone number, so please check the student record and their "
            f"GHL contact and fix whichever is out of date. The student is now listed under Review > Verify students, "
            f"where you can correct their details. Until then nothing reaches them automatically, so please "
            f"contact them yourself.")

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
    spaced: int = 0          # attempts held back because another student was contacted less than the spacing ago
    no_response_alerts: int = 0
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


# Contact with one student (a call, a text and an email together count as ONE contact) is kept this far from contact with the NEXT student,
# so a burst of notices never stacks calls and texts on the shared phone line (Twilio limits). Kes 2026-10-12. 0 switches it off.
LEAD_SPACING_DEFAULT_MINUTES = 3


def lead_spacing() -> timedelta:
    import os
    raw = os.getenv("NOTIFY_LEAD_SPACING_MINUTES")
    try:
        minutes = LEAD_SPACING_DEFAULT_MINUTES if raw in (None, "") else max(0.0, float(raw))
    except ValueError:
        minutes = LEAD_SPACING_DEFAULT_MINUTES
    return timedelta(minutes=minutes)


def _another_student_contacted_recently(db, seq_id: int, now: datetime, spacing: timedelta) -> bool:
    """True when any OTHER sequence made a contact (sent, or logged in shadow mode) less than `spacing` before `now`."""
    if spacing <= timedelta(0):
        return False
    M = _m()
    return db.query(M.NotificationAttempt).filter(
        M.NotificationAttempt.sequence_id != seq_id,
        M.NotificationAttempt.sent_at != None,          # noqa: E711
        M.NotificationAttempt.sent_at > now - spacing,
    ).first() is not None


def _flag_for_verification(db, seq, reason: str) -> None:
    """A student GHL cannot find has details that need checking, whatever way they entered the system (the roster is not always right).
    Listing them under Review > Verify students gives the approver the form to correct them. Never downgrades a student who already has a record."""
    if "no GHL contact matches" not in reason:
        return
    M = _m()
    student = db.get(M.Student, seq.student_id) if seq.student_id else None
    if student is None:
        return
    try:
        from log_interview import mark_unverified
        mark_unverified(db, student.id, "no_ghl_contact", student.full_name or "", reason[:500])
    except Exception as exc:                       # never let a flagging problem stop the follow-ups
        logger.warning(f"Could not flag student {student.id} for verification: {exc}")


def tick(db, now: datetime, channels: Dict[str, Any], alerts: Optional[RoleAlerts] = None,
         ack_base_url: str = "") -> TickReport:
    """Send every attempt that is due, send the approver's alerts, and end sequences that have run out."""
    M = _m()
    alerts = alerts or RoleAlerts(db=db)
    report = TickReport()
    sequences = db.query(M.NotificationSequence).filter(M.NotificationSequence.status == "active").all()
    spacing = lead_spacing()

    def _waiting_since(sq):                       # the student who has waited longest goes first, so nobody is starved
        times = [a.scheduled_for for a in sq.attempts if a.status == "pending" and a.scheduled_for <= now]
        return min(times) if times else datetime.max
    sequences.sort(key=_waiting_since)
    for seq in sequences:
        draft_for_seq = db.get(M.NotificationDraft, seq.draft_id)
        interview_utc, _known = _interview_utc(db, draft_for_seq, seq.timezone) if draft_for_seq is not None else (None, False)
        if interview_utc is not None and now >= interview_utc:
            seq.status = "interview_passed"              # the interview time has come: nothing more is sent, nobody is chased
            _cancel_pending(seq, "the interview time has passed")
            db.commit()
            continue
        due = sorted((a for a in seq.attempts if a.status == "pending" and a.scheduled_for <= now),
                     key=lambda a: a.scheduled_for)
        if due and _another_student_contacted_recently(db, seq.id, now, spacing):
            # Another student was contacted less than the spacing ago: wait. Nothing is changed, so the next tick sends these.
            report.spaced += len(due)
            logger.info(f"seq {seq.id}: {len(due)} due attempt(s) held, another student was contacted less than {int(spacing.total_seconds() // 60)} min ago")
            due = []
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
                if (result.detail or "").startswith(nc.UNREACHABLE):
                    _flag_for_verification(db, seq, result.detail[len(nc.UNREACHABLE):])
                if (result.detail or "").startswith(nc.UNREACHABLE) and not any(
                        o is not attempt and (o.detail or "").startswith(nc.UNREACHABLE) for o in seq.attempts):
                    alerts.cannot_reach(seq, _student_name(db, seq), result.detail[len(nc.UNREACHABLE):])

        if seq.rob_day1_alert_at is None and seq.attempts and all(
                a.status == "skipped" and (a.detail or "").startswith("student has no") for a in seq.attempts):
            # nothing can ever be sent: tell the approver now (once), do not wait days for the "ended" alert
            alerts.cannot_reach(seq, _student_name(db, seq), "there is no email, phone number or Gmail on file")
            seq.rob_day1_alert_at = now
            db.commit()
            report.no_response_alerts += 1

        if seq.rob_day1_alert_at is None and now >= sched.no_response_due(seq.started_at, interview_utc):
            alerts.no_response(seq, _student_name(db, seq))
            seq.rob_day1_alert_at = now
            db.commit()
            report.no_response_alerts += 1

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
                         alerts: Optional[RoleAlerts] = None, completion_fn=None,
                         env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    A student replied by text (or a call transcript was posted back). Plain rules first (YES, STOP),
    then the AI reading. Returns what happened, for the caller to log.
    """
    M = _m()
    alerts = alerts or RoleAlerts(db=db)
    sequences = _active_sequences_for_phone(db, phone)
    if not sequences:
        return {"handled": False, "reason": "no active notification for this number"}

    return handle_reply_for_sequences(db, sequences, text, channel, now, alerts, completion_fn, env)


def pick_target(sequences, channel: str, at: Optional[datetime]):
    """
    Which of a student's open notices a reply answers. A text or a call does not say which interview it is about, so it is
    attributed to the notice whose message was SENT most recently before the reply, on the same channel first, then on any channel;
    with nothing sent before it, to the newest notice. (The email link is tied to one notice and never needs this.)
    """
    for ch in (channel, None):
        best = None
        for seq in sequences:
            times = [a.sent_at for a in seq.attempts
                     if a.status == "sent" and a.sent_at and (ch is None or a.channel == ch) and (at is None or a.sent_at <= at)]
            if times and (best is None or max(times) > best[0]):
                best = (max(times), seq)
        if best is not None:
            return best[1]
    return sequences[0]


def handle_reply_for_sequences(db, sequences, text: str, channel: str, now: datetime,
                               alerts: Optional[RoleAlerts] = None, completion_fn=None,
                               env: Optional[Dict[str, str]] = None, received_at: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Decide what one student reply means for these (active) sequences: plain rules first (YES, STOP),
    then the AI reading, which only ever stops a sequence in live mode. Shared by the webhook and the poller.
    STOP ends every open notice (the student opted out of us). A YES or an AI-understood reply answers ONE notice, the one `pick_target` chooses;
    the student's other notices (other positions) keep their follow-ups. The notice that was answered is returned as "target".
    """
    M = _m()
    alerts = alerts or RoleAlerts(db=db)
    target = pick_target(sequences, channel, received_at or now)
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
        acknowledge(db, target, channel, "explicit", now)
        return {"handled": True, "action": "acknowledged", "kind": "explicit", "sequences": 1, "target": target}

    seq = target                                      # the notice this reply answers
    analysis = ra.analyze_reply(text, _interview_summary(db, seq), completion_fn=completion_fn)
    mode = ra.analysis_mode(now, env)
    stops = ra.may_stop_sequence(analysis, mode)
    db.add(M.ReplyAnalysis(sequence_id=seq.id, channel=channel, message_text=text[:2000],
                           outcome=analysis.outcome, confidence=analysis.confidence,
                           reason=analysis.reason, shadow=(mode == "shadow"), acted=stops))
    db.commit()
    if stops:
        acknowledge(db, seq, "ai", "ai_inferred", now)
        return {"handled": True, "action": "acknowledged", "kind": "ai_inferred", "mode": mode, "target": seq}
    if analysis.outcome != "understood":
        alerts.student_reply(seq, _student_name(db, seq), text, analysis.outcome)
    return {"handled": True, "action": "recorded", "outcome": analysis.outcome, "mode": mode, "target": seq}


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


def poll_replies(db, now: datetime, client, alerts: Optional[RoleAlerts] = None, completion_fn=None,
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
    alerts = alerts or RoleAlerts(db=db)
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
                                                completion_fn, env, received_at=message.received_at)
            _record_inbound(db, result.get("target") or primary, message, _handled_as(result))
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
            result = handle_reply_for_sequences(db, active, rule_text, "call", now, alerts, completion_fn, env, received_at=call.created_at)
            _record_inbound(db, result.get("target") or primary, record, _handled_as(result), text=call.human_words)
            if result.get("action") in ("acknowledged", "opted_out"):
                report.stopped += 1
    return report


class _CallRecord:
    """Adapts a Voice AI call to the shape _record_inbound writes."""
    channel, direction, text = "call", "outbound", ""

    def __init__(self, call):
        self.id, self.received_at = call.record_id, call.created_at
