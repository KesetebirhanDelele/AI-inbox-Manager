"""
Notification management API endpoints.

Provides endpoints for viewing, approving, rejecting, and sending
interview notification drafts.
"""

import hmac
import os
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta

from database import get_db
from utils_text import clean_email_text
from auth import get_current_user
from types import SimpleNamespace

from models import (
    AlertLog,
    NotificationDraft,
    InterviewGateReview,
    NotificationInbound,
    NotificationSequence,
    StudentVerification,
    InterviewEvent,
    InterviewFollowUp,
    Student,
    Email,
    UserSession,
)

router = APIRouter()


# ----------------------------------------------------------------------------
# Student escalation (directives/student-notification-escalation.md)
# ----------------------------------------------------------------------------

def _escalation_enabled() -> bool:
    """Off unless NOTIFY_ESCALATION_ENABLED is 1/true/yes, so Approve keeps its old behaviour by default."""
    return os.getenv("NOTIFY_ESCALATION_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _delivery_is_live(db=None) -> bool:
    """True only when the server is armed (three GHL write switches) AND the Settings switch is on: otherwise every send is just logged (shadow)."""
    try:
        cfg = _execution_module("ghl_client").GhlConfig.from_env()
        return bool(cfg.armed and _execution_module("roles").live_delivery_on(db))
    except Exception:
        return False


def _engine():
    """The escalation engine. Its modules live in execution/, which is not on the API's import path."""
    exec_dir = str(Path(__file__).resolve().parents[4] / "execution")
    if exec_dir not in sys.path:
        sys.path.insert(0, exec_dir)
    import escalation_engine
    import notify_channels
    return escalation_engine, notify_channels


def _ack_base_url() -> str:
    return os.getenv("NOTIFY_ACK_BASE_URL", "https://2-29-47-89.nip.io/api/notifications/ack")


# ============================================================================
# Pydantic Models
# ============================================================================


class NotificationSummary(BaseModel):
    """Summary view of a notification draft."""

    id: int
    interview_event_id: int
    template_id: Optional[str]
    email_subject: Optional[str]
    recipient_email: Optional[str]
    email_status: str
    auto_send_eligible: bool
    missing_fields: Optional[list]
    created_at: Optional[datetime]

    # From InterviewEvent
    sub_type: Optional[str] = None
    company_name: Optional[str] = None
    position_title: Optional[str] = None
    confidence: Optional[float] = None

    # From Student
    student_name: Optional[str] = None
    student_username: Optional[str] = None

    class Config:
        from_attributes = True


class NotificationDetail(BaseModel):
    """Full detail view of a notification draft."""

    id: int
    interview_event_id: int

    # Email notification
    template_id: Optional[str]
    email_subject: Optional[str]
    email_body: Optional[str]
    recipient_email: Optional[str]
    email_status: str
    auto_send_eligible: bool

    # Review tracking
    missing_fields: Optional[list]
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    sent_at: Optional[datetime]
    send_error: Optional[str]
    created_at: Optional[datetime]

    # Interview details
    sub_type: Optional[str] = None
    company_name: Optional[str] = None
    position_title: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    interview_date: Optional[str] = None
    interview_time: Optional[str] = None
    interview_timezone: Optional[str] = None
    interview_format: Optional[str] = None
    confidence: Optional[float] = None
    is_job_machine: Optional[bool] = None

    # Student details
    student_name: Optional[str] = None
    student_username: Optional[str] = None
    student_personal_email: Optional[str] = None
    student_assigned_gmail: Optional[str] = None
    student_phone: Optional[str] = None

    # Source email
    email_db_id: Optional[int] = None
    email_subject_original: Optional[str] = None

    class Config:
        from_attributes = True


class EditDraftRequest(BaseModel):
    """Request to edit and optionally send a notification draft."""

    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    recipient_email: Optional[str] = None
    send_after_edit: bool = False


class RejectRequest(BaseModel):
    """Request to reject a notification draft."""

    reason: Optional[str] = None


class StudentResponse(BaseModel):
    """Student info response."""

    id: int
    username: str
    full_name: Optional[str]
    personal_email: Optional[str]
    assigned_gmail: Optional[str]
    phone_number: Optional[str]
    is_active: bool
    last_synced_at: Optional[datetime]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================================
# Helper Functions
# ============================================================================


def _build_notification_summary(
    draft: NotificationDraft,
    event: Optional[InterviewEvent] = None,
    student: Optional[Student] = None,
) -> dict:
    """Build a summary dict from ORM objects."""
    data = {
        "id": draft.id,
        "interview_event_id": draft.interview_event_id,
        "template_id": draft.template_id,
        "email_subject": draft.email_subject,
        "recipient_email": draft.recipient_email,
        "email_status": draft.email_status,
        "auto_send_eligible": draft.auto_send_eligible,
        "missing_fields": draft.missing_fields,
        "created_at": draft.created_at,
    }
    if event:
        data["sub_type"] = event.sub_type
        data["company_name"] = event.company_name
        data["position_title"] = event.position_title
        data["confidence"] = event.confidence
    if student:
        data["student_name"] = student.full_name
        data["student_username"] = student.username
    return data


def _build_notification_detail(
    draft: NotificationDraft,
    event: Optional[InterviewEvent] = None,
    student: Optional[Student] = None,
    email: Optional[Email] = None,
) -> dict:
    """Build a full detail dict from ORM objects."""
    data = {
        "id": draft.id,
        "interview_event_id": draft.interview_event_id,
        "template_id": draft.template_id,
        "email_subject": draft.email_subject,
        "email_body": draft.email_body,
        "recipient_email": draft.recipient_email,
        "email_status": draft.email_status,
        "auto_send_eligible": draft.auto_send_eligible,
        "missing_fields": draft.missing_fields,
        "reviewed_by": draft.reviewed_by,
        "reviewed_at": draft.reviewed_at,
        "sent_at": draft.sent_at,
        "send_error": draft.send_error,
        "created_at": draft.created_at,
    }
    if event:
        data["sub_type"] = event.sub_type
        data["company_name"] = event.company_name
        data["position_title"] = event.position_title
        data["contact_name"] = event.contact_name
        data["contact_email"] = event.contact_email
        data["interview_date"] = event.interview_date
        data["interview_time"] = event.interview_time
        data["interview_timezone"] = event.interview_timezone
        data["interview_format"] = event.interview_format
        data["confidence"] = event.confidence
        data["is_job_machine"] = event.is_job_machine
        data["email_db_id"] = event.email_id
    if student:
        data["student_name"] = student.full_name
        data["student_username"] = student.username
        data["student_personal_email"] = student.personal_email
        data["student_assigned_gmail"] = student.assigned_gmail
        data["student_phone"] = student.phone_number
    if email:
        data["email_subject_original"] = email.subject
    return data


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/pending", response_model=List[NotificationSummary])
async def get_pending_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Get notification drafts pending review."""
    results = (
        db.query(NotificationDraft, InterviewEvent, Student)
        .join(InterviewEvent, NotificationDraft.interview_event_id == InterviewEvent.id)
        .outerjoin(Student, InterviewEvent.student_id == Student.id)
        .filter(NotificationDraft.email_status.in_(["draft", "approved"]))
        .order_by(desc(NotificationDraft.created_at))
        .limit(limit)
        .offset(offset)
        .all()
    )

    return [
        _build_notification_summary(draft, event, student)
        for draft, event, student in results
    ]


@router.get("/sent", response_model=List[NotificationSummary])
async def get_sent_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Get sent notification history."""
    results = (
        db.query(NotificationDraft, InterviewEvent, Student)
        .join(InterviewEvent, NotificationDraft.interview_event_id == InterviewEvent.id)
        .outerjoin(Student, InterviewEvent.student_id == Student.id)
        .filter(NotificationDraft.email_status == "sent")
        .order_by(desc(NotificationDraft.sent_at))
        .limit(limit)
        .offset(offset)
        .all()
    )

    return [
        _build_notification_summary(draft, event, student)
        for draft, event, student in results
    ]


def _tick_approve_step(db, event, username: str) -> None:
    """Tick the checklist sub-step "Approve the notification" so the checklist and the real state agree."""
    if event is None:
        return
    from checklist_steps import approve_step_key
    from models import ChecklistCompletion
    key = approve_step_key(event.sub_type)
    row = (db.query(ChecklistCompletion)
           .filter(ChecklistCompletion.interview_event_id == event.id, ChecklistCompletion.step_key == key).first())
    if row is None:
        db.add(ChecklistCompletion(interview_event_id=event.id, step_key=key, is_completed=True,
                                   completed_by=username, completed_at=datetime.utcnow()))
    else:
        row.is_completed, row.completed_by, row.completed_at = True, username, datetime.utcnow()
    db.commit()


def _execution_module(name: str):
    exec_dir = str(Path(__file__).resolve().parents[4] / "execution")
    if exec_dir not in sys.path:
        sys.path.insert(0, exec_dir)
    return __import__(name)


def _single_email_enabled() -> bool:
    """The old one-email Approve is OFF unless SINGLE_EMAIL_APPROVE_ENABLED is 1/true/yes (the server .env has a real SMTP login, so without this switch a click would email a real student)."""
    return os.getenv("SINGLE_EMAIL_APPROVE_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _ensure_email_sending_configured() -> None:
    """
    Approve through the single-email path must be switched on on purpose AND have an SMTP login. It says so BEFORE it changes anything
    (before the draft is marked approved or a checklist step is ticked), so nothing is left half-done and nothing is sent by accident.
    """
    if not _single_email_enabled():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approve by single email is switched off until the three-channel flow starts, so nothing was sent and the draft is unchanged. "
                   "Tell Kes if this student must be told today (he can tell them by hand).",
        )
    mod = _execution_module("send_notification")
    if not (getattr(mod, "SMTP_USERNAME", "") and getattr(mod, "SMTP_PASSWORD", "")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This server has no email-sending login set up for the app, so nothing was sent and the draft is unchanged. "
                   "Tell Kes before approving.",
        )


def _send_draft_email(draft) -> dict:
    """
    Send one draft by email through execution/send_notification.py (the single-email path used while the three-channel flow is off).

    The module is loaded by its plain name (`execution/` is put on sys.path), because the API container has no `execution` package: the
    old `from execution.send_notification import ...` crashed every Approve with a 500 in production (2026-10-09).
    """
    send_email = _execution_module("send_notification").send_email
    return send_email(
        recipient_email=draft.recipient_email or "",
        subject=draft.email_subject or "",
        body=draft.email_body or "",
    )


REVIEW_MAX_AGE_DAYS = 14
CHECKER_ALERT_KIND = "student_check"      # alert_log key "<event id>:<n>": every click is kept, so the card can say who alerted whom and when


def _checker_alert_view(row) -> Optional[dict]:
    if row is None:
        return None
    to, _, by = (row.detail or "").partition("|")
    return {"sent_at": row.sent_at, "to": to, "by": by}


def _follow_up_in_view(db, draft_id: int, now: datetime) -> bool:
    """An approved notice stays on the Review screen while its follow-ups run, and for 24 hours after a reply, a stop or an acknowledgement."""
    seq = db.query(NotificationSequence).filter(NotificationSequence.draft_id == draft_id).first()
    if seq is None:
        return False
    if seq.status == "active":
        return True
    since = now - timedelta(hours=24)
    if (seq.ack_at and seq.ack_at >= since) or (seq.closed_at and seq.closed_at >= since):
        return True
    return db.query(NotificationInbound.id).filter(NotificationInbound.sequence_id == seq.id, NotificationInbound.created_at >= since).first() is not None


@router.get("/review-queue")
async def get_review_queue(
    include_done: bool = Query(False, description="also list notices already decided: sent, approved (plan running or finished) or rejected"),
    limit: int = Query(100, ge=1, le=300),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """
    Everything the approver needs to approve or reject a student notification on ONE screen.

    One item per interview event: the student and how to reach them, the interview facts, the source email with an
    advisory authenticity check (genuine interview or job-board mailer), the draft, a preview of what the student will
    receive, and the reasons Approve is blocked (blockers) or worth a second look (warnings). Events with no draft
    (the student could not be identified) are listed too, with the reason, so nothing hides.
    """
    authenticity = _execution_module("email_authenticity")
    nc = _execution_module("notify_channels")
    escalation_on = _escalation_enabled()
    delivery_live = escalation_on and _delivery_is_live(db)

    rows = (
        db.query(InterviewEvent, NotificationDraft, Student, Email)
        .outerjoin(NotificationDraft, NotificationDraft.interview_event_id == InterviewEvent.id)
        .outerjoin(Student, InterviewEvent.student_id == Student.id)
        .outerjoin(Email, InterviewEvent.email_id == Email.id)
        .order_by(desc(Email.received_date), desc(InterviewEvent.id))
        .limit(limit * 3)
        .all()
    )

    follow_ups = {row.event_id: row.original_event_id for row in db.query(InterviewFollowUp).all()}
    flags_mod = _execution_module("student_flags")
    checker_alerts = {}                    # event id -> the latest "student checker alerted" row
    for a in db.query(AlertLog).filter(AlertLog.kind == CHECKER_ALERT_KIND).order_by(AlertLog.id).all():
        checker_alerts[a.key.split(":")[0]] = a
    flags_deadline = time.time() + 12                       # lookups are cached; if a cold cache is slow, the rest show "unknown" this time
    items = []
    for event, draft, student, email in rows:
        status_ = draft.email_status if draft else None
        follow_up_of = follow_ups.get(event.id)
        if follow_up_of is not None and not include_done:
            continue                       # a reminder/reply about an interview the student was already told about: no decision needed
        if status_ in ("sent", "rejected", "approved") and not include_done:
            if not (status_ in ("sent", "approved") and _follow_up_in_view(db, draft.id, datetime.utcnow())):
                continue                   # already decided and quiet: only under "Show finished"
            # an approved notice whose follow-ups are still running (or that had a reply or stop in the last 24 hours) stays in view: it can be stopped
        # Old mail is never a decision for today: anything received more than REVIEW_MAX_AGE_DAYS ago only shows with "Show finished".
        if not include_done and email is not None and email.received_date and email.received_date < datetime.utcnow() - timedelta(days=REVIEW_MAX_AGE_DAYS):
            continue
        blockers, warnings = [], []
        verification = (db.query(StudentVerification).filter(StudentVerification.student_id == student.id).first()
                        if student is not None else None)
        if verification is not None and verification.status == "rejected" and not include_done:
            continue                       # the approver said this is not a student we can find: their notices are closed and hidden
        unverified = verification is not None and verification.status != "verified"
        if student is None:
            blockers.append("No student identified for this email, so there is nobody to notify. Check the email and the student list.")
        elif not (student.phone_number or student.personal_email or student.assigned_gmail):
            blockers.append("No phone, email or Gmail on file for this student: nothing can be sent. Add their contact details first.")
        else:
            if not (student.phone_number or "").strip():
                warnings.append("No phone number on file: the call and text will rely on the student's GHL contact having one.")
            if not ((student.personal_email or "").strip() or (student.assigned_gmail or "").strip()):
                warnings.append("No email on file for the student: the GHL contact is found by phone only.")
        if draft is not None and not (draft.recipient_email or "").strip():
            warnings.append("The draft has no recipient email.")
        if unverified:
            blockers.append("This student was created from the email's delivery address and is not verified yet. "
                            "Trace who they are (roster sheet, Drive, the original sign-up), correct the details below, and confirm.")

        # Every open interview notice says whether the student is on the roster sheet and found in GHL; a person decides (never silent).
        flags = {"roster": "unknown", "ghl": "unknown"}
        if student is not None and follow_up_of is None and status_ in (None, "draft", "approved"):
            try:
                flags["roster"] = flags_mod.roster_status(student)
                if time.time() < flags_deadline:
                    flags["ghl"] = flags_mod.ghl_status(student)
            except Exception:
                pass
            for w in reversed(flags_mod.warnings_for(flags["roster"], flags["ghl"])):
                warnings.insert(0, w)

        text = clean_email_text((email.full_body or email.body_preview) if email else "")
        gate_mod = _execution_module("interview_gate")
        gate_row = db.query(InterviewGateReview).filter(InterviewGateReview.event_id == event.id).first()
        # Live mode judges what the sender just wrote; the older thread under a reply would make any reply look like an interview.
        auth_text = _execution_module("quoted_text").new_text_only(text) if gate_mod.gate_mode() == "live" else text
        check = authenticity.assess(
            email.subject if email else "", email.from_address if email else "", auth_text[:6000], event.company_name)
        if check["verdict"] == "likely_job_board":
            warnings.insert(0, "This looks like a job-board mailer, not a real interview invitation. Please read the email before approving.")

        suggestion = None
        if draft is not None and status_ == "draft" and follow_up_of is None:
            try:
                suggestion = _execution_module("interview_followup").suggested_action(db, event, draft)
            except Exception:
                suggestion = None          # no opinion beats a wrong one

        if follow_up_of is not None:
            state = "follow_up"
        elif draft is None:
            state = "needs_student" if student is None else "no_draft"
            if student is not None:
                blockers.append("No draft was created for this email.")
        elif status_ == "draft":
            state = "needs_verification" if unverified and len(blockers) == 1 else ("blocked" if blockers else "ready")
        else:
            state = status_ or "unknown"

        preview = None
        if draft is not None and student is not None:
            ctx = nc.SendContext(attempt=SimpleNamespace(step="start"), sequence=SimpleNamespace(id="#"), draft=draft,
                                 event=event, student=student, ack_url="", now=datetime.utcnow())
            preview = {
                "call": nc.call_script(ctx).replace(" Reference: #.", ""),
                "text": nc.sms_text(ctx).replace(" Ref #", ""),
                "email_subject": draft.email_subject,
            }

        sequence = None
        if draft is not None:
            seq = db.query(NotificationSequence).filter(NotificationSequence.draft_id == draft.id).first()
            if seq is not None:
                replies = (db.query(NotificationInbound).filter(NotificationInbound.sequence_id == seq.id)
                           .order_by(NotificationInbound.id.desc()).limit(8).all())
                sequence = {"status": seq.status, "started_at": seq.started_at, "ack_channel": seq.ack_channel, "ack_kind": seq.ack_kind,
                            "can_stop": seq.status == "active",
                            "replies": [{"channel": r.channel, "text": (r.text or "")[:300], "received_at": r.received_at, "handled_as": r.handled_as}
                                        for r in reversed(replies) if r.handled_as != "echo"]}

        items.append({
            "event_id": event.id,
            "draft_id": draft.id if draft else None,
            "state": state,
            "follow_up_of": follow_up_of,
            "suggestion": suggestion,
            "blockers": blockers,
            "warnings": warnings,
            "flags": flags,
            "checker_alert": _checker_alert_view(checker_alerts.get(str(event.id))),
            "can_approve": state == "ready",
            "will_happen": (("Starts a call, a text and an email to the student, then follows up until they confirm."
                             if delivery_live else
                             "Nothing reaches the student: the system is in SHADOW mode. Approving only starts the follow-up plan and logs what it "
                             "would send (call, text, email). Tell the student by hand if it matters.")
                            if escalation_on else
                            "Sends one email to the student now. The call and text are not switched on yet."),
            "student": None if student is None else {
                "id": student.id, "name": student.full_name, "username": student.username,
                "personal_email": student.personal_email, "assigned_gmail": student.assigned_gmail,
                "phone": student.phone_number,
                "verification": None if verification is None else {
                    "status": verification.status, "basis": verification.basis, "guessed_name": verification.guessed_name,
                    "evidence": verification.evidence, "verified_by": verification.verified_by,
                },
            },
            "interview": {
                "type": event.sub_type, "company": event.company_name, "position": event.position_title,
                "date": event.interview_date, "time": event.interview_time, "timezone": event.interview_timezone,
                "format": event.interview_format, "contact_name": event.contact_name,
                "contact_email": event.contact_email, "confidence": event.confidence,
            },
            "email": None if email is None else {
                "id": email.id, "subject": email.subject, "from_address": email.from_address,
                "received_date": email.received_date, "excerpt": text[:1500],
            },
            "authenticity": check,
            "gate": None if gate_row is None or gate_row.verdict is None else {
                "verdict": gate_row.verdict, "flag": gate_mod.label({"verdict": gate_row.verdict, "round": gate_row.round, "format": gate_row.format}),
                "confidence": gate_row.confidence, "reason": gate_row.reason, "would_hide": bool(gate_row.would_hide), "mode": gate_row.mode},
            "draft": None if draft is None else {
                "subject": draft.email_subject, "body": draft.email_body,
                "recipient_email": draft.recipient_email, "status": draft.email_status,
            },
            "preview": preview,
            "sequence": sequence,
        })
        if len(items) >= limit:
            break

    order = {"ready": 0, "needs_verification": 1, "blocked": 2, "needs_student": 3, "no_draft": 4}
    items.sort(key=lambda i: order.get(i["state"], 4))
    from routers.callback_requests import callback_item
    from models import CallbackRequest
    callbacks = [callback_item(db, r).model_dump() for r in
                 db.query(CallbackRequest).filter(CallbackRequest.status == "open", CallbackRequest.student_id.isnot(None)).order_by(CallbackRequest.received_at).limit(50).all()]
    return {"escalation_enabled": escalation_on, "delivery_live": delivery_live, "count": len(items), "items": items, "callbacks": callbacks}


@router.post("/events/{event_id}/alert-student-checker")
async def alert_student_checker(
    event_id: int,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """
    Email the Student checker role (Settings) to verify a candidate who is not on the roster sheet or not in GHL, and to call them.
    Nothing is sent to the student and the card is not changed. Refuses, saying why, when nobody holds the role or staff alerts are off.
    """
    event = db.get(InterviewEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Interview notice not found")
    roles = _execution_module("roles")
    to = roles.role_email(db, "student_checker")
    if not to:
        raise HTTPException(status_code=409, detail="Nobody holds the Student checker role. Assign an email to it on the Settings page, then click Alert again.")
    if not roles.staff_alerts_on(db):
        raise HTTPException(status_code=409, detail="Email alerts to staff are switched off on the Settings page, so nothing was sent.")

    student = db.get(Student, event.student_id) if event.student_id else None
    email = db.get(Email, event.email_id) if event.email_id else None
    flags_mod = _execution_module("student_flags")
    problems = []
    if student is not None:
        try:
            problems = flags_mod.warnings_for(flags_mod.roster_status(student), flags_mod.ghl_status(student))
        except Exception:
            problems = []
    when = " ".join(x for x in (event.interview_date, event.interview_time, event.interview_timezone) if x) or "no time stated"
    who = (student.full_name if student else None) or "an unidentified student"
    lines = [
        f"{user.username} asks you to verify {who} and call them before their interview notice goes out.",
        "",
        f"Student: {who}",
        f"Phone: {(student.phone_number if student else None) or 'none on file'}",
        f"Personal email: {(student.personal_email if student else None) or 'none on file'}",
        f"Assigned Gmail: {(student.assigned_gmail if student else None) or 'none on file'}",
        "",
        f"Interview: {event.sub_type or 'Interview'} with {event.company_name or 'an unnamed company'}"
        + (f", {event.position_title}" if event.position_title else "") + f" ({when})",
        f"Source email: {(email.subject if email else '') or '(none)'} from {(email.from_address if email else '') or '(unknown)'}",
    ]
    if problems:
        lines += ["", "What the system found:"] + [f"- {p}" for p in problems]
    lines += ["", "Please confirm this is one of our students, get their current phone and email, and fix the roster sheet or GHL "
              "(or correct the details under Review > Verify students). Then tell the approver, who decides on the card.",
              f"Review screen: {os.getenv('DASHBOARD_URL', 'https://2-29-47-89.nip.io/review')}"]
    sent = _execution_module("escalation_engine").RoleAlerts(db=db).student_check(f"Please verify and call {who}", "\n".join(lines))
    if not sent:
        raise HTTPException(status_code=502, detail="The alert email could not be sent. Nothing was recorded; check the app's email login and try again.")
    n = db.query(AlertLog).filter(AlertLog.kind == CHECKER_ALERT_KIND, AlertLog.key.like(f"{event_id}:%")).count() + 1
    row = AlertLog(kind=CHECKER_ALERT_KIND, key=f"{event_id}:{n}", detail=f"{to}|{user.username}")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _checker_alert_view(row)


class VerifyStudentRequest(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    personal_email: Optional[str] = None


@router.post("/students/{student_id}/verify")
async def verify_student(
    student_id: int,
    request: VerifyStudentRequest,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """the approver confirms who a pipeline-created student is, correcting the guessed name, phone and personal email."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    if request.full_name is not None and request.full_name.strip():
        student.full_name = request.full_name.strip()[:255]
    if request.phone_number is not None and request.phone_number.strip():
        student.phone_number = request.phone_number.strip()[:50]
    if request.personal_email is not None and request.personal_email.strip():
        student.personal_email = request.personal_email.strip()[:255]
    row = db.query(StudentVerification).filter(StudentVerification.student_id == student_id).first()
    if row is None:
        row = StudentVerification(student_id=student_id, status="verified", basis="manual", guessed_name=student.full_name)
        db.add(row)
    row.status, row.verified_by, row.verified_at = "verified", user.username, datetime.utcnow()
    # drafts already written for this student carry the old personal email: keep them pointing at the corrected one
    if request.personal_email and request.personal_email.strip():
        for draft in (db.query(NotificationDraft).join(InterviewEvent, NotificationDraft.interview_event_id == InterviewEvent.id)
                      .filter(InterviewEvent.student_id == student_id, NotificationDraft.email_status == "draft").all()):
            draft.recipient_email = student.personal_email
    db.commit()
    return {"student_id": student_id, "full_name": student.full_name, "phone_number": student.phone_number,
            "personal_email": student.personal_email, "status": "verified", "verified_by": user.username}


class RejectStudentRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/students/{student_id}/reject-verification")
async def reject_student(
    student_id: int,
    request: RejectStudentRequest,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """
    The approver says this is NOT a student we can find (no matching contact, not one of ours): the verification is marked "rejected",
    every notice for them that has not gone out is rejected, and their follow-up plans are closed. Nothing is deleted and nothing is sent;
    the emails and interview events stay. A student who already has notices that went out is refused: a person must handle that.
    """
    student = db.query(Student).filter(Student.id == student_id).first()
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    drafts = (db.query(NotificationDraft).join(InterviewEvent, NotificationDraft.interview_event_id == InterviewEvent.id)
              .filter(InterviewEvent.student_id == student_id).all())
    sequences = [db.query(NotificationSequence).filter(NotificationSequence.draft_id == d.id).first() for d in drafts]
    if any(sq is not None and any(a.sent_at for a in sq.attempts) for sq in sequences) or any(d.email_status == "sent" for d in drafts):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="A notice for this student has already gone out, so this cannot be undone here. Please handle it by hand.")
    now = datetime.utcnow()
    reason = (request.reason or "not a student we can find").strip()[:200]
    row = db.query(StudentVerification).filter(StudentVerification.student_id == student_id).first()
    if row is None:
        row = StudentVerification(student_id=student_id, status="rejected", basis="manual", guessed_name=student.full_name)
        db.add(row)
    row.status, row.verified_by, row.verified_at = "rejected", user.username, now
    closed = 0
    engine = _execution_module("escalation_engine")
    for d, sq in zip(drafts, sequences):
        if sq is not None and sq.status == "active":
            engine.close_sequence(db, sq, user.username, now)
        if d.email_status in ("draft", "approved"):
            d.email_status, d.reviewed_by, d.reviewed_at = "rejected", user.username, now
            d.send_error = f"Rejected: {reason}"
            closed += 1
    db.commit()
    return {"student_id": student_id, "status": "rejected", "notices_closed": closed, "rejected_by": user.username}


@router.get("/{notification_id}", response_model=NotificationDetail)
async def get_notification_detail(
    notification_id: int,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Get full details of a notification draft."""
    result = (
        db.query(NotificationDraft, InterviewEvent, Student, Email)
        .join(InterviewEvent, NotificationDraft.interview_event_id == InterviewEvent.id)
        .outerjoin(Student, InterviewEvent.student_id == Student.id)
        .outerjoin(Email, InterviewEvent.email_id == Email.id)
        .filter(NotificationDraft.id == notification_id)
        .first()
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found",
        )

    draft, event, student, email = result
    return _build_notification_detail(draft, event, student, email)


@router.post("/{notification_id}/approve")
async def approve_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Approve and send a notification draft."""
    draft = (
        db.query(NotificationDraft)
        .filter(NotificationDraft.id == notification_id)
        .first()
    )

    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found",
        )

    if draft.email_status == "sent":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notification already sent",
        )

    # Server-side guard (the screen also disables Approve): nobody to notify, or no way to reach them
    event_for_guard = db.query(InterviewEvent).filter(InterviewEvent.id == draft.interview_event_id).first()
    student_for_guard = (db.query(Student).filter(Student.id == event_for_guard.student_id).first()
                         if event_for_guard and event_for_guard.student_id else None)
    if student_for_guard is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No student is identified for this interview, so there is nobody to notify.")
    if not (student_for_guard.phone_number or student_for_guard.personal_email or student_for_guard.assigned_gmail):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This student has no phone, email or Gmail on file. Add their contact details first.")

    # An interview that has already happened must never start a notice (the follow-up plan stops at the interview time).
    sched = _execution_module("escalation_schedule")
    when, _known = sched.interview_when(event_for_guard.interview_date, event_for_guard.interview_time, event_for_guard.interview_timezone,
                                        "America/Chicago")
    if when is not None and when <= datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"This interview was on {event_for_guard.interview_date}, so it has already happened and a notice would only confuse "
                                   "the student. Reject this card, or tell the student by hand if it still matters.")

    pending_check = (db.query(StudentVerification).filter(StudentVerification.student_id == student_for_guard.id,
                                                          StudentVerification.status != "verified").first())
    if pending_check is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This student has not been verified yet. Confirm who they are first.")

    if _escalation_enabled():
        # Pilot gate (Ali): until the limit is lifted on the Settings page, only that many notices may start a sequence.
        from routers.role_settings import pilot_limit
        limit = pilot_limit(db)
        started = db.query(NotificationSequence).count()
        already = db.query(NotificationSequence).filter(NotificationSequence.draft_id == draft.id).first() is not None
        if limit and started >= limit and not already:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Pilot limit reached: {started} of {limit} notices have already been started. "
                                       "Lift the limit on the Settings page once the pilot has run clean.")

    if not _escalation_enabled():
        _ensure_email_sending_configured()      # only the old one-email path needs (and risks) the SMTP login

    # Update status to approved
    draft.email_status = "approved"
    draft.reviewed_by = user.username
    draft.reviewed_at = datetime.utcnow()
    db.commit()
    _tick_approve_step(db, event_for_guard, user.username)

    if _escalation_enabled():
        # the approver's approval starts the escalation: call + text + email now, then follow-ups until
        # the student acknowledges (or the approver closes it). Nothing is sent before this click.
        engine, channels_mod = _engine()
        event = db.query(InterviewEvent).filter(InterviewEvent.id == draft.interview_event_id).first()
        student = db.query(Student).filter(Student.id == event.student_id).first() if event and event.student_id else None
        now = datetime.utcnow()
        seq = engine.start_sequence(db, draft, student, now, started_by=user.username)
        report = engine.tick(db, now, channels_mod.channels_from_env(), engine.RoleAlerts(db=db), _ack_base_url())
        db.refresh(draft)
        return {
            "id": draft.id,
            "email_status": draft.email_status,
            "send_error": draft.send_error,
            "sequence_id": seq.id,
            "sequence_status": seq.status,
            "first_round": {"sent": report.sent, "dry_run": report.dry_run, "failed": report.failed,
                            "skipped": report.skipped},
        }

    # Send the email
    send_result = _send_draft_email(draft)

    if send_result["status"] == "sent":
        draft.email_status = "sent"
        draft.sent_at = datetime.utcnow()
    else:
        draft.email_status = "failed"
        draft.send_error = send_result.get("error")

    db.commit()

    return {
        "id": draft.id,
        "email_status": draft.email_status,
        "send_error": draft.send_error,
    }


@router.post("/{notification_id}/edit")
async def edit_notification(
    notification_id: int,
    request: EditDraftRequest,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Edit a notification draft, optionally sending after edit."""
    draft = (
        db.query(NotificationDraft)
        .filter(NotificationDraft.id == notification_id)
        .first()
    )

    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found",
        )

    if draft.email_status == "sent":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit a sent notification",
        )

    # Apply edits
    if request.email_subject is not None:
        draft.email_subject = request.email_subject
    if request.email_body is not None:
        draft.email_body = request.email_body
    if request.recipient_email is not None:
        draft.recipient_email = request.recipient_email

    draft.reviewed_by = user.username
    draft.reviewed_at = datetime.utcnow()
    db.commit()

    result = {
        "id": draft.id,
        "email_status": draft.email_status,
        "email_subject": draft.email_subject,
    }

    # Optionally send after edit
    if request.send_after_edit:
        send_result = _send_draft_email(draft)

        if send_result["status"] == "sent":
            draft.email_status = "sent"
            draft.sent_at = datetime.utcnow()
        else:
            draft.email_status = "failed"
            draft.send_error = send_result.get("error")

        db.commit()
        result["email_status"] = draft.email_status
        result["send_error"] = draft.send_error

    return result


@router.post("/{notification_id}/reject")
async def reject_notification(
    notification_id: int,
    request: RejectRequest,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Reject a notification draft."""
    draft = (
        db.query(NotificationDraft)
        .filter(NotificationDraft.id == notification_id)
        .first()
    )

    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found",
        )

    draft.email_status = "rejected"
    draft.reviewed_by = user.username
    draft.reviewed_at = datetime.utcnow()
    if request.reason:
        draft.send_error = f"Rejected: {request.reason}"
    db.commit()

    return {
        "id": draft.id,
        "email_status": draft.email_status,
        "reviewed_by": draft.reviewed_by,
    }


# ============================================================================
# Student Endpoints
# ============================================================================


@router.get("/students/list", response_model=List[StudentResponse])
async def list_students(
    active_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """List all students."""
    query = db.query(Student)
    if active_only:
        query = query.filter(Student.is_active == True)
    students = query.order_by(Student.full_name).limit(limit).all()
    return students


@router.get("/students/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: int,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Get student details."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student {student_id} not found",
        )
    return student


@router.get("/by-email/{email_id}")
async def get_notification_by_email(
    email_id: int,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Get notification details for a specific source email.

    Used by the inbox view to show inline interview notification details
    when an interview email is selected.
    """
    result = (
        db.query(NotificationDraft, InterviewEvent, Student)
        .join(InterviewEvent, NotificationDraft.interview_event_id == InterviewEvent.id)
        .outerjoin(Student, InterviewEvent.student_id == Student.id)
        .filter(InterviewEvent.email_id == email_id)
        .order_by(desc(NotificationDraft.created_at))
        .first()
    )

    if not result:
        return None

    draft, event, student = result
    return _build_notification_detail(draft, event, student)


# ----------------------------------------------------------------------------
# Escalation endpoints
# ----------------------------------------------------------------------------

_ACK_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Confirmed</title></head><body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem">
<h1>{heading}</h1><p>{message}</p></body></html>"""


@router.get("/ack/{token}", response_class=HTMLResponse)
async def acknowledge_by_email_link(token: str, db: Session = Depends(get_db)):
    """The student's one-tap "I got this" link from the email. Public: the unguessable token is the credential."""
    engine, _ = _engine()
    result = engine.acknowledge_by_token(db, token, datetime.utcnow())
    if result == "unknown":
        return HTMLResponse(
            _ACK_PAGE.format(heading="Link not recognised",
                             message="This confirmation link is not valid. Please reply to the email instead."),
            status_code=404)
    return HTMLResponse(_ACK_PAGE.format(
        heading="Thank you", message="We have recorded that you received your interview notice. Good luck!"))


@router.get("/{notification_id}/sequence")
async def get_sequence(notification_id: int, db: Session = Depends(get_db),
                       user: UserSession = Depends(get_current_user)):
    """Escalation status and every attempt for one notification."""
    from models import NotificationSequence
    seq = db.query(NotificationSequence).filter(NotificationSequence.draft_id == notification_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="No escalation sequence for this notification")
    return {
        "id": seq.id, "status": seq.status, "timezone": seq.timezone, "timezone_source": seq.timezone_source,
        "started_at": seq.started_at, "ack_at": seq.ack_at, "ack_channel": seq.ack_channel,
        "ack_kind": seq.ack_kind, "closed_by": seq.closed_by,
        "attempts": [
            {"channel": a.channel, "step": a.step, "scheduled_for": a.scheduled_for, "status": a.status,
             "sent_at": a.sent_at, "detail": a.detail}
            for a in sorted(seq.attempts, key=lambda a: (a.scheduled_for, a.channel))
        ],
    }


@router.post("/{notification_id}/sequence/close")
async def close_sequence(notification_id: int, db: Session = Depends(get_db),
                         user: UserSession = Depends(get_current_user)):
    """the approver closes the follow-ups (for example the student told them directly)."""
    from models import NotificationSequence
    engine, _ = _engine()
    seq = db.query(NotificationSequence).filter(NotificationSequence.draft_id == notification_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="No escalation sequence for this notification")
    closed = engine.close_sequence(db, seq, user.username, datetime.utcnow())
    return {"id": seq.id, "status": seq.status, "closed_now": closed}


class InboundReply(BaseModel):
    phone: str
    text: str
    channel: str = "sms"          # sms | call


@router.post("/inbound/reply")
async def inbound_reply(body: InboundReply, db: Session = Depends(get_db),
                        x_notify_secret: Optional[str] = Header(None)):
    """
    A student's reply, forwarded by the SMS/voice provider. Closed unless NOTIFY_INBOUND_SECRET is set
    and matches the X-Notify-Secret header, because this endpoint can stop follow-ups.
    """
    secret = os.getenv("NOTIFY_INBOUND_SECRET", "")
    if not secret or not x_notify_secret or not hmac.compare_digest(secret, x_notify_secret):
        raise HTTPException(status_code=401, detail="Not authorised")
    if body.channel not in ("sms", "call"):
        raise HTTPException(status_code=422, detail="channel must be sms or call")
    engine, _ = _engine()
    return engine.handle_inbound_reply(db, body.phone, body.text, body.channel, datetime.utcnow(), engine.RoleAlerts(db=db))
