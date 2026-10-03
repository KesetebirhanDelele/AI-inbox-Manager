"""
Inbox monitoring API endpoints.

Provides real-time and historical inbox state information.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from database import get_db
from utils_text import clean_preview, clean_email_text
from auth import get_current_user
from models import Email, Classification, UserSession
from integration.email_fetcher import get_current_inbox_state, get_unread_emails

router = APIRouter()


# Pydantic models
class InboxCountResponse(BaseModel):
    count: int
    synced: bool



class EmailResponse(BaseModel):
    id: int
    email_id: str
    subject: str
    from_address: str
    received_date: datetime
    body_preview: str
    current_folder: str
    is_read: bool
    latest_category: Optional[str]
    latest_confidence: Optional[float]
    latest_company: Optional[str]

    class Config:
        from_attributes = True


@router.get("/count", response_model=InboxCountResponse)
async def get_inbox_count(
    refresh: bool = Query(False, description="Fetch fresh data from IMAP and update count"),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get current inbox email count.

    Args:
        refresh: If True, fetch fresh data from IMAP server first. If False, use database count.

    Returns:
        Count of emails in INBOX and whether it was synced from IMAP
    """
    if refresh:
        # Fetch fresh from IMAP - this updates the database
        emails = get_current_inbox_state(db)
        return InboxCountResponse(count=len(emails), synced=True)
    else:
        # Get count from database
        count = db.query(Email).filter(
            Email.current_folder == "INBOX"
        ).count()
        return InboxCountResponse(count=count, synced=False)


@router.get("/current", response_model=List[EmailResponse])
async def get_current_inbox(
    refresh: bool = Query(False, description="Fetch fresh data from IMAP"),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get current INBOX state.

    Args:
        refresh: If True, fetch fresh data from IMAP server. If False, use database cache.

    Returns:
        List of emails currently in INBOX
    """
    if refresh:
        # Fetch fresh from IMAP
        emails = get_current_inbox_state(db)
    else:
        # Get from database
        emails = db.query(Email).filter(
            Email.current_folder == "INBOX"
        ).order_by(
            Email.received_date.desc()
        ).all()

    # Build response with latest classification
    response = []
    for email in emails:
        # Get latest classification
        latest_classification = db.query(Classification).filter(
            Classification.email_id == email.id
        ).order_by(
            Classification.classification_timestamp.desc()
        ).first()

        response.append(EmailResponse(
            id=email.id,
            email_id=email.email_id,
            subject=email.subject,
            from_address=email.from_address,
            received_date=email.received_date,
            body_preview=clean_preview(email.body_preview, email.full_body),
            current_folder=email.current_folder,
            is_read=email.is_read,
            latest_category=latest_classification.category if latest_classification else None,
            latest_confidence=latest_classification.confidence if latest_classification else None,
            latest_company=latest_classification.company_name if latest_classification else None
        ))

    return response


@router.get("/unread", response_model=List[EmailResponse])
async def get_unread_inbox_emails(
    refresh: bool = Query(False, description="Fetch fresh data from IMAP"),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get only unread emails from INBOX.

    Args:
        refresh: If True, fetch fresh data from IMAP server.

    Returns:
        List of unread emails
    """
    if refresh:
        emails = get_unread_emails(db)
    else:
        emails = db.query(Email).filter(
            Email.current_folder == "INBOX",
            Email.is_read == False
        ).order_by(
            Email.received_date.desc()
        ).all()

    # Build response
    response = []
    for email in emails:
        latest_classification = db.query(Classification).filter(
            Classification.email_id == email.id
        ).order_by(
            Classification.classification_timestamp.desc()
        ).first()

        response.append(EmailResponse(
            id=email.id,
            email_id=email.email_id,
            subject=email.subject,
            from_address=email.from_address,
            received_date=email.received_date,
            body_preview=clean_preview(email.body_preview, email.full_body),
            current_folder=email.current_folder,
            is_read=email.is_read,
            latest_category=latest_classification.category if latest_classification else None,
            latest_confidence=latest_classification.confidence if latest_classification else None,
            latest_company=latest_classification.company_name if latest_classification else None
        ))

    return response


@router.get("/history", response_model=List[EmailResponse])
async def get_inbox_history(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    folder: Optional[str] = Query(None, description="Filter by folder"),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get historical emails from database.

    Args:
        limit: Maximum number of emails to return (1-500)
        offset: Number of emails to skip (for pagination)
        folder: Optional folder filter (e.g., "INBOX", "Job Alerts")

    Returns:
        Paginated list of historical emails
    """
    query = db.query(Email)

    if folder:
        query = query.filter(Email.current_folder == folder)

    emails = query.order_by(
        Email.received_date.desc()
    ).limit(limit).offset(offset).all()

    # Build response
    response = []
    for email in emails:
        latest_classification = db.query(Classification).filter(
            Classification.email_id == email.id
        ).order_by(
            Classification.classification_timestamp.desc()
        ).first()

        response.append(EmailResponse(
            id=email.id,
            email_id=email.email_id,
            subject=email.subject,
            from_address=email.from_address,
            received_date=email.received_date,
            body_preview=clean_preview(email.body_preview, email.full_body),
            current_folder=email.current_folder,
            is_read=email.is_read,
            latest_category=latest_classification.category if latest_classification else None,
            latest_confidence=latest_classification.confidence if latest_classification else None,
            latest_company=latest_classification.company_name if latest_classification else None
        ))

    return response


@router.get("/{email_id}", response_model=dict)
async def get_email_detail(
    email_id: int,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get detailed information about a specific email.

    Includes full body, all classifications, and action history.
    """
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # Get all classifications
    classifications = db.query(Classification).filter(
        Classification.email_id == email_id
    ).order_by(
        Classification.classification_timestamp.desc()
    ).all()

    # Get action history
    from models import EmailAction
    actions = db.query(EmailAction).filter(
        EmailAction.email_id == email_id
    ).order_by(
        EmailAction.performed_at.desc()
    ).all()

    return {
        "email": {
            "id": email.id,
            "email_id": email.email_id,
            "subject": email.subject,
            "from_address": email.from_address,
            "received_date": email.received_date.isoformat(),
            "full_body": clean_email_text(email.full_body) if email.full_body else email.full_body,
            "current_folder": email.current_folder,
            "is_read": email.is_read,
            "fetch_timestamp": email.fetch_timestamp.isoformat(),
            "last_updated": email.last_updated.isoformat()
        },
        "classifications": [
            {
                "id": c.id,
                "category": c.category,
                "confidence": c.confidence,
                "company_name": c.company_name,
                "position": c.position,
                "timestamp": c.classification_timestamp.isoformat(),
                "classifier_version": c.classifier_version
            }
            for c in classifications
        ],
        "actions": [
            {
                "id": a.id,
                "action_type": a.action_type,
                "from_folder": a.from_folder,
                "to_folder": a.to_folder,
                "performed_by": a.performed_by,
                "performed_at": a.performed_at.isoformat(),
                "reason": a.reason
            }
            for a in actions
        ]
    }
