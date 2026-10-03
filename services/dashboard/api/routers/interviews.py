"""
Interview requests API endpoints.

Provides access to detected interview requests.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date

from database import get_db
from auth import get_current_user
from models import Email, Classification, UserSession, InterviewEvent, Student, NotificationDraft
from checklist_steps import normalize_sub_type

router = APIRouter()


# Pydantic models
class InterviewRequest(BaseModel):
    id: int
    email_id: str
    subject: str
    from_address: str
    received_date: datetime
    company_name: Optional[str]
    position: Optional[str]
    confidence: float
    classification_timestamp: datetime
    body_preview: str
    current_folder: str
    is_read: bool
    student_name: Optional[str] = None
    interview_type: Optional[str] = None
    interview_date: Optional[str] = None
    interview_time: Optional[str] = None
    contact_name: Optional[str] = None
    interview_event_id: Optional[int] = None

    class Config:
        from_attributes = True


class InterviewEventRecord(BaseModel):
    event_id: int
    student_name: Optional[str]
    student_email: Optional[str]
    company_name: Optional[str]
    position_title: Optional[str]
    sub_type: str
    interview_type: Optional[str]
    interview_date: Optional[str]
    interview_time: Optional[str]
    interview_timezone: Optional[str]
    interview_format: Optional[str]
    notification_status: Optional[str]
    notified_at: Optional[datetime]
    recipient_email: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class UpcomingInterview(BaseModel):
    interview_event_id: int
    student_name: Optional[str]
    company_name: Optional[str]
    position: Optional[str]
    interview_type: Optional[str]
    interview_date: Optional[str]
    interview_time: Optional[str]
    interview_timezone: Optional[str]
    interview_format: Optional[str]
    meeting_link: Optional[str]
    contact_name: Optional[str]
    contact_email: Optional[str]

    class Config:
        from_attributes = True


@router.get("/upcoming", response_model=List[UpcomingInterview])
async def get_upcoming_interviews(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get interviews scheduled for today or in the future (have an interview_date set).

    Returns events ordered by interview_date ascending so the soonest appears first.
    """
    today_str = date.today().isoformat()  # "YYYY-MM-DD"

    results = db.query(InterviewEvent, Student).outerjoin(
        Student, InterviewEvent.student_id == Student.id
    ).filter(
        InterviewEvent.interview_date != None,
        InterviewEvent.interview_date >= today_str
    ).order_by(
        InterviewEvent.interview_date.asc(),
        InterviewEvent.interview_time.asc()
    ).all()

    upcoming = []
    for event, student in results:
        upcoming.append(UpcomingInterview(
            interview_event_id=event.id,
            student_name=student.full_name if student else "Unknown",
            company_name=event.company_name,
            position=event.position_title,
            interview_type=normalize_sub_type(event.sub_type),
            interview_date=event.interview_date,
            interview_time=event.interview_time,
            interview_timezone=event.interview_timezone,
            interview_format=event.interview_format,
            meeting_link=event.meeting_link,
            contact_name=event.contact_name,
            contact_email=event.contact_email,
        ))

    return upcoming


# Both spellings are registered: behind the Caddy proxy FastAPI's slash redirect pointed at http://, which the
# browser dropped, so the page showed "No interview requests" while the count card said 35.
@router.get("", response_model=List[InterviewRequest], include_in_schema=False)
@router.get("/", response_model=List[InterviewRequest])
async def get_interview_requests(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get all detected interview requests.

    Args:
        limit: Number of records to return (1-200)
        offset: Number of records to skip

    Returns:
        List of interview requests with email and classification data
    """
    try:
        # Step 1: Get unique emails classified as Interview Request (deduplicated)
        email_query = db.query(Email, Classification).join(
            Classification, Email.id == Classification.email_id
        ).filter(
            Classification.category == "Interview Request"
        ).order_by(
            desc(Email.received_date)
        ).limit(limit).offset(offset).all()

        # Step 2: For each email, get only the most recent InterviewEvent
        interview_requests = []
        seen_email_ids = set()

        for email, classification in email_query:
            # Skip duplicates (shouldn't happen with this query but safety check)
            if email.id in seen_email_ids:
                continue
            seen_email_ids.add(email.id)

            # Get most recent InterviewEvent for this email
            interview_event = db.query(InterviewEvent).filter(
                InterviewEvent.email_id == email.id
            ).order_by(desc(InterviewEvent.id)).first()

            # Get student if interview_event has one
            student = None
            if interview_event and interview_event.student_id:
                student = db.query(Student).filter(
                    Student.id == interview_event.student_id
                ).first()

            interview_requests.append(InterviewRequest(
                id=email.id,
                email_id=email.email_id,
                subject=email.subject,
                from_address=email.from_address,
                received_date=email.received_date,
                company_name=classification.company_name,
                position=classification.position or (interview_event.position_title if interview_event else None),
                confidence=classification.confidence,
                classification_timestamp=classification.classification_timestamp,
                body_preview=email.body_preview or "",
                current_folder=email.current_folder,
                student_name=student.full_name if student else "Unknown",
                interview_type=normalize_sub_type(interview_event.sub_type) if interview_event else None,
                interview_date=interview_event.interview_date if interview_event else None,
                interview_time=interview_event.interview_time if interview_event else None,
                contact_name=interview_event.contact_name if interview_event else None,
                interview_event_id=interview_event.id if interview_event else None,
                is_read=email.is_read
            ))

        return interview_requests

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error fetching interview requests: {e}", exc_info=True)
        return []


@router.get("/count")
async def get_interview_count(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get total count of interview requests.

    Returns:
        Total count of emails classified as Interview Request
    """
    count = db.query(Email).join(
        Classification, Email.id == Classification.email_id
    ).filter(
        Classification.category == "Interview Request"
    ).count()

    return {"count": count}


@router.get("/events", response_model=List[InterviewEventRecord])
async def get_interview_events(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get all interview events with student info and notification status.

    Returns every row in interview_events joined with the student record
    and the latest notification draft for that event (if any).
    Ordered newest first.
    """
    # Subquery: latest notification draft ID per interview event
    latest_notif_subq = (
        db.query(
            NotificationDraft.interview_event_id,
            func.max(NotificationDraft.id).label("latest_id")
        )
        .group_by(NotificationDraft.interview_event_id)
        .subquery()
    )

    results = (
        db.query(InterviewEvent, Student, NotificationDraft)
        .outerjoin(Student, InterviewEvent.student_id == Student.id)
        .outerjoin(
            latest_notif_subq,
            InterviewEvent.id == latest_notif_subq.c.interview_event_id
        )
        .outerjoin(
            NotificationDraft,
            NotificationDraft.id == latest_notif_subq.c.latest_id
        )
        .order_by(desc(InterviewEvent.created_at))
        .all()
    )

    records = []
    for event, student, notif in results:
        records.append(InterviewEventRecord(
            event_id=event.id,
            student_name=student.full_name if student else "Unknown",
            student_email=student.personal_email if student else None,
            company_name=event.company_name,
            position_title=event.position_title,
            sub_type=event.sub_type,
            interview_type=normalize_sub_type(event.sub_type),
            interview_date=event.interview_date,
            interview_time=event.interview_time,
            interview_timezone=event.interview_timezone,
            interview_format=event.interview_format,
            notification_status=notif.email_status if notif else None,
            notified_at=notif.sent_at if notif else None,
            recipient_email=notif.recipient_email if notif else None,
            created_at=event.created_at,
        ))

    return records


@router.get("/{email_id}")
async def get_interview_detail(
    email_id: int,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get full details of a specific interview request.

    Args:
        email_id: Email database ID

    Returns:
        Full email content and classification details
    """
    result = db.query(Email, Classification).join(
        Classification, Email.id == Classification.email_id
    ).filter(
        and_(
            Email.id == email_id,
            Classification.category == "Interview Request"
        )
    ).first()

    if not result:
        return {"error": "Interview request not found"}

    email, classification = result

    return {
        "id": email.id,
        "email_id": email.email_id,
        "subject": email.subject,
        "from_address": email.from_address,
        "received_date": email.received_date.isoformat(),
        "full_body": email.full_body,
        "company_name": classification.company_name,
        "position": classification.position,
        "confidence": classification.confidence,
        "classification_timestamp": classification.classification_timestamp.isoformat(),
        "current_folder": email.current_folder,
        "is_read": email.is_read
    }
