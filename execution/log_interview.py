"""
Interview event logging execution script.

Logs interview events and notification drafts to the dashboard database.
Provides functions to create/update Student, InterviewEvent, and
NotificationDraft records.

Design principles:
- Pure database logic, no orchestration
- Accepts SQLAlchemy session from caller (testable via in-memory DB)
- Returns created/updated records as dictionaries
- Handles upsert for students (create or update)
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def upsert_student(
    db: Session,
    username: str,
    full_name: Optional[str] = None,
    personal_email: Optional[str] = None,
    assigned_gmail: Optional[str] = None,
    phone_number: Optional[str] = None,
    drive_folder_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create or update a student record.

    If a student with the given username already exists, updates their info.
    Otherwise creates a new record.

    Args:
        db: SQLAlchemy database session
        username: Student's username (Drive folder name / Gmail local part)
        full_name: Student's real name
        personal_email: Student's personal email (notification target)
        assigned_gmail: Student's assigned Gmail (job submission email)
        phone_number: Student's phone number
        drive_folder_id: Google Drive folder ID

    Returns:
        Dictionary with student record fields and 'created' flag
    """
    # Import here to avoid circular imports at module level
    from models import Student

    existing = db.query(Student).filter(Student.username == username).first()

    if existing:
        # Update existing student
        if full_name:
            existing.full_name = full_name
        if personal_email:
            existing.personal_email = personal_email
        if assigned_gmail:
            existing.assigned_gmail = assigned_gmail
        if phone_number:
            existing.phone_number = phone_number
        if drive_folder_id:
            existing.drive_folder_id = drive_folder_id
        existing.last_synced_at = datetime.utcnow()

        db.commit()
        db.refresh(existing)
        logger.info(f"Updated student: {username}")

        return {
            "id": existing.id,
            "username": existing.username,
            "full_name": existing.full_name,
            "personal_email": existing.personal_email,
            "assigned_gmail": existing.assigned_gmail,
            "phone_number": existing.phone_number,
            "created": False,
        }

    # Create new student
    student = Student(
        username=username,
        full_name=full_name,
        personal_email=personal_email,
        assigned_gmail=assigned_gmail,
        phone_number=phone_number,
        drive_folder_id=drive_folder_id,
        last_synced_at=datetime.utcnow(),
        is_active=True,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    logger.info(f"Created student: {username}")

    return {
        "id": student.id,
        "username": student.username,
        "full_name": student.full_name,
        "personal_email": student.personal_email,
        "assigned_gmail": student.assigned_gmail,
        "phone_number": student.phone_number,
        "created": True,
    }


def log_interview_event(
    db: Session,
    email_db_id: int,
    classification: Dict[str, Any],
    student_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Log an interview event to the database.

    Creates an InterviewEvent record from sub-classification results.

    Args:
        db: SQLAlchemy database session
        email_db_id: Database ID of the source email (emails.id)
        classification: Sub-classification result from subclassify_interview.py
        student_id: Database ID of the student (students.id), if resolved

    Returns:
        Dictionary with created InterviewEvent fields
    """
    from models import InterviewEvent

    event = InterviewEvent(
        email_id=email_db_id,
        student_id=student_id,
        sub_type=classification.get("interview_sub_type", ""),
        company_name=classification.get("company_name"),
        position_title=classification.get("position_title"),
        contact_name=classification.get("contact_name"),
        contact_email=classification.get("contact_email"),
        contact_phone=classification.get("contact_phone"),
        interview_date=classification.get("interview_date"),
        interview_time=classification.get("interview_time"),
        interview_timezone=classification.get("interview_timezone"),
        interview_format=classification.get("interview_format"),
        meeting_link=classification.get("meeting_link_or_dial_in"),
        num_interviewers=classification.get("num_interviewers"),
        is_job_machine=classification.get("is_job_machine", False),
        is_next_round=classification.get("is_next_round", False),
        confidence=classification.get("confidence", 0.0),
        raw_extraction=classification,
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    logger.info(
        f"Logged interview event: {event.sub_type} at {event.company_name} "
        f"(ID: {event.id})"
    )

    return {
        "id": event.id,
        "email_id": event.email_id,
        "student_id": event.student_id,
        "sub_type": event.sub_type,
        "company_name": event.company_name,
        "confidence": event.confidence,
    }


def mark_unverified(db: Session, student_id: int, basis: str, guessed_name: str, evidence: str = "") -> bool:
    """
    Flag a pipeline-created student for Rob to verify. Never touches a student that already has a record (so a verified
    student is never downgraded) and never flags the roster's students. Returns True when a new flag was created.
    """
    from models import StudentVerification
    if db.query(StudentVerification).filter(StudentVerification.student_id == student_id).first():
        return False
    db.add(StudentVerification(student_id=student_id, status="unverified", basis=basis,
                               guessed_name=guessed_name, evidence=evidence))
    db.commit()
    return True


def log_notification_draft(
    db: Session,
    interview_event_id: int,
    draft: Dict[str, Any],
    auto_send_eligible: bool = False,
) -> Dict[str, Any]:
    """
    Log a notification draft to the database.

    Creates a NotificationDraft record from draft_notification results.

    Args:
        db: SQLAlchemy database session
        interview_event_id: Database ID of the InterviewEvent
        draft: Draft notification result from draft_notification.py
        auto_send_eligible: Whether this draft qualifies for auto-sending

    Returns:
        Dictionary with created NotificationDraft fields
    """
    from models import NotificationDraft

    notification = NotificationDraft(
        interview_event_id=interview_event_id,
        template_id=draft.get("template_id"),
        email_subject=draft.get("email_subject"),
        email_body=draft.get("email_body"),
        recipient_email=draft.get("recipient_email"),
        email_status="draft",
        auto_send_eligible=auto_send_eligible,
        missing_fields=draft.get("missing_fields"),
    )

    db.add(notification)
    db.commit()
    db.refresh(notification)

    logger.info(
        f"Logged notification draft: template={notification.template_id} "
        f"recipient={notification.recipient_email} (ID: {notification.id})"
    )

    return {
        "id": notification.id,
        "interview_event_id": notification.interview_event_id,
        "template_id": notification.template_id,
        "recipient_email": notification.recipient_email,
        "email_status": notification.email_status,
        "auto_send_eligible": notification.auto_send_eligible,
    }


def update_notification_status(
    db: Session,
    notification_id: int,
    email_status: str,
    send_error: Optional[str] = None,
    reviewed_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update the status of a notification draft.

    Used after sending, approving, or rejecting a notification.

    Args:
        db: SQLAlchemy database session
        notification_id: Database ID of the NotificationDraft
        email_status: New status (sent, failed, approved, rejected)
        send_error: Error message if sending failed
        reviewed_by: Username of reviewer (if approved/rejected)

    Returns:
        Dictionary with updated notification fields
    """
    from models import NotificationDraft

    notification = db.query(NotificationDraft).filter(
        NotificationDraft.id == notification_id
    ).first()

    if not notification:
        logger.error(f"Notification draft not found: {notification_id}")
        return {"error": f"Notification {notification_id} not found"}

    notification.email_status = email_status

    if email_status == "sent":
        notification.sent_at = datetime.utcnow()
    if send_error:
        notification.send_error = send_error
    if reviewed_by:
        notification.reviewed_by = reviewed_by
        notification.reviewed_at = datetime.utcnow()

    db.commit()
    db.refresh(notification)

    logger.info(
        f"Updated notification {notification_id} status to: {email_status}"
    )

    return {
        "id": notification.id,
        "email_status": notification.email_status,
        "sent_at": notification.sent_at.isoformat() if notification.sent_at else None,
        "send_error": notification.send_error,
        "reviewed_by": notification.reviewed_by,
    }


