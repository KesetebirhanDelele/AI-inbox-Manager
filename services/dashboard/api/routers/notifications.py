"""
Notification management API endpoints.

Provides endpoints for viewing, approving, rejecting, and sending
interview notification drafts.
"""

import hmac
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from database import get_db
from utils_text import clean_email_text
from auth import get_current_user
from types import SimpleNamespace

from models import (
    NotificationDraft,
    NotificationSequence,
    StudentVerification,
    InterviewEvent,
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


@router.get("/review-queue")
async def get_review_queue(
    include_done: bool = Query(False, description="also list notices already sent or rejected"),
    limit: int = Query(100, ge=1, le=300),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """
    Everything Rob needs to approve or reject a student notification on ONE screen.

    One item per interview event: the student and how to reach them, the interview facts, the source email with an
    advisory authenticity check (genuine interview or job-board mailer), the draft, a preview of what the student will
    receive, and the reasons Approve is blocked (blockers) or worth a second look (warnings). Events with no draft
    (the student could not be identified) are listed too, with the reason, so nothing hides.
    """
    authenticity = _execution_module("email_authenticity")
    nc = _execution_module("notify_channels")
    escalation_on = _escalation_enabled()

    rows = (
        db.query(InterviewEvent, NotificationDraft, Student, Email)
        .outerjoin(NotificationDraft, NotificationDraft.interview_event_id == InterviewEvent.id)
        .outerjoin(Student, InterviewEvent.student_id == Student.id)
        .outerjoin(Email, InterviewEvent.email_id == Email.id)
        .order_by(desc(Email.received_date), desc(InterviewEvent.id))
        .limit(limit * 3)
        .all()
    )

    items = []
    for event, draft, student, email in rows:
        status_ = draft.email_status if draft else None
        if status_ in ("sent", "rejected") and not include_done:
            continue
        blockers, warnings = [], []
        verification = (db.query(StudentVerification).filter(StudentVerification.student_id == student.id).first()
                        if student is not None else None)
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

        text = clean_email_text((email.full_body or email.body_preview) if email else "")
        check = authenticity.assess(
            email.subject if email else "", email.from_address if email else "", text[:6000], event.company_name)
        if check["verdict"] == "likely_job_board":
            warnings.insert(0, "This looks like a job-board mailer, not a real interview invitation. Please read the email before approving.")

        if draft is None:
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
                sequence = {"status": seq.status, "started_at": seq.started_at, "ack_channel": seq.ack_channel}

        items.append({
            "event_id": event.id,
            "draft_id": draft.id if draft else None,
            "state": state,
            "blockers": blockers,
            "warnings": warnings,
            "can_approve": state == "ready",
            "will_happen": ("Starts a call, a text and an email to the student, then follows up until they confirm."
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
    return {"escalation_enabled": escalation_on, "count": len(items), "items": items}


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
    """Rob confirms who a pipeline-created student is, correcting the guessed name, phone and personal email."""
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

    pending_check = (db.query(StudentVerification).filter(StudentVerification.student_id == student_for_guard.id,
                                                          StudentVerification.status != "verified").first())
    if pending_check is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This student has not been verified yet. Confirm who they are first.")

    # Update status to approved
    draft.email_status = "approved"
    draft.reviewed_by = user.username
    draft.reviewed_at = datetime.utcnow()
    db.commit()
    _tick_approve_step(db, event_for_guard, user.username)

    if _escalation_enabled():
        # Rob's approval starts the escalation: call + text + email now, then follow-ups until
        # the student acknowledges (or Rob closes it). Nothing is sent before this click.
        engine, channels_mod = _engine()
        event = db.query(InterviewEvent).filter(InterviewEvent.id == draft.interview_event_id).first()
        student = db.query(Student).filter(Student.id == event.student_id).first() if event and event.student_id else None
        now = datetime.utcnow()
        seq = engine.start_sequence(db, draft, student, now, started_by=user.username)
        report = engine.tick(db, now, channels_mod.channels_from_env(), engine.RobAlerts(), _ack_base_url())
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
    from execution.send_notification import send_email

    send_result = send_email(
        recipient_email=draft.recipient_email or "",
        subject=draft.email_subject or "",
        body=draft.email_body or "",
    )

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
        from execution.send_notification import send_email

        send_result = send_email(
            recipient_email=draft.recipient_email or "",
            subject=draft.email_subject or "",
            body=draft.email_body or "",
        )

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
    """Rob closes the follow-ups himself (for example the student told him directly)."""
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
    return engine.handle_inbound_reply(db, body.phone, body.text, body.channel, datetime.utcnow(), engine.RobAlerts())
