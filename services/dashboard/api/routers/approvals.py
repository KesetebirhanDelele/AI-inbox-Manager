"""
Approval queue API endpoints.

Handles approval workflow for low-confidence email classifications.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from database import get_db
from auth import get_current_user
from models import Approval, Email, Classification, UserSession
from integration.email_actions import move_email, delete_email  # noqa: F401  (delete_email stays importable; the action is switched off)

DELETE_OFF = ("Delete is switched off: the system quarantines mail and never deletes it. "
              "Move the email to the Other (not job related) folder instead.")
from integration.email_classifier import reclassify_email
from integration.summary_importer import add_to_whitelist

router = APIRouter()


# Pydantic models for request/response
class ApprovalResponse(BaseModel):
    id: int
    email_id: int
    classification_id: int
    status: str
    email_subject: str
    email_from: str
    email_received_date: datetime
    category: str
    confidence: float
    company_name: Optional[str]
    position: Optional[str]

    class Config:
        from_attributes = True


class ApproveRequest(BaseModel):
    action: str  # "keep_inbox", "move_to_folder", "delete"
    target_folder: Optional[str] = None
    notes: Optional[str] = None


class OverrideRequest(BaseModel):
    new_category: str
    action: str  # "keep_inbox", "move_to_folder", "delete"
    target_folder: Optional[str] = None
    notes: Optional[str] = None
    add_to_whitelist: bool = False


@router.get("/pending", response_model=List[ApprovalResponse])
async def get_pending_approvals(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get all pending approvals (emails requiring human review).

    Returns emails with confidence < 0.70 sorted by received date (oldest first).
    """
    approvals = db.query(Approval).filter(
        Approval.status == "pending"
    ).order_by(
        Approval.id.asc()
    ).all()

    # Build response with email and classification data
    response = []
    for approval in approvals:
        email = db.query(Email).filter(Email.id == approval.email_id).first()
        classification = db.query(Classification).filter(
            Classification.id == approval.classification_id
        ).first()

        if email and classification:
            response.append(ApprovalResponse(
                id=approval.id,
                email_id=email.id,
                classification_id=classification.id,
                status=approval.status,
                email_subject=email.subject,
                email_from=email.from_address,
                email_received_date=email.received_date,
                category=classification.category,
                confidence=classification.confidence,
                company_name=classification.company_name,
                position=classification.position
            ))

    return response


@router.post("/{approval_id}/approve")
async def approve_classification(
    approval_id: int,
    request: ApproveRequest,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Approve an email classification and execute the specified action.

    Actions:
    - keep_inbox: Leave email in inbox
    - move_to_folder: Move to specified folder
    - delete: Delete the email
    """
    # Get approval
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Approval already {approval.status}"
        )

    # Get email
    email = db.query(Email).filter(Email.id == approval.email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # Execute action
    try:
        if request.action == "move_to_folder":
            if not request.target_folder:
                raise HTTPException(
                    status_code=400,
                    detail="target_folder required for move action"
                )
            move_email(
                db=db,
                email=email,
                target_folder=request.target_folder,
                performed_by=user.username,
                reason=f"Approved: {request.notes or 'No notes'}"
            )

        elif request.action == "delete":
            raise HTTPException(status_code=400, detail=DELETE_OFF)

        elif request.action == "keep_inbox":
            # No action needed, just mark as approved
            pass

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action: {request.action}"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing action: {str(e)}")

    # Update approval status
    approval.status = "approved"
    approval.human_action = request.action
    approval.target_folder = request.target_folder
    approval.reviewed_by = user.username
    approval.reviewed_at = datetime.utcnow()
    approval.notes = request.notes

    db.commit()

    return {
        "message": "Approval processed successfully",
        "approval_id": approval_id,
        "action": request.action
    }


@router.post("/{approval_id}/override")
async def override_classification(
    approval_id: int,
    request: OverrideRequest,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Override an email classification with human judgment.

    This updates the classification, optionally adds company to whitelist,
    and executes the specified action.
    """
    # Get approval
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Approval already {approval.status}"
        )

    # Get email and classification
    email = db.query(Email).filter(Email.id == approval.email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    classification = db.query(Classification).filter(
        Classification.id == approval.classification_id
    ).first()

    # Create new classification with human override
    new_classification = Classification(
        email_id=email.id,
        category=request.new_category,
        confidence=1.0,  # Human override = 100% confidence
        company_name=classification.company_name if classification else None,
        position=classification.position if classification else None,
        classification_timestamp=datetime.utcnow(),
        classifier_version="human-override",
        raw_response={"overridden_by": user.username, "notes": request.notes}
    )

    db.add(new_classification)
    db.flush()  # Get the ID

    # Add to whitelist if requested
    if request.add_to_whitelist and classification and classification.company_name:
        add_to_whitelist(
            db=db,
            company_name=classification.company_name,
            notes=f"Added by {user.username} during override",
            added_by=user.username
        )

    # Execute action
    try:
        if request.action == "move_to_folder":
            if not request.target_folder:
                raise HTTPException(
                    status_code=400,
                    detail="target_folder required for move action"
                )
            move_email(
                db=db,
                email=email,
                target_folder=request.target_folder,
                performed_by=user.username,
                reason=f"Overridden to {request.new_category}: {request.notes or 'No notes'}"
            )

        elif request.action == "delete":
            raise HTTPException(status_code=400, detail=DELETE_OFF)

        elif request.action == "keep_inbox":
            pass

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action: {request.action}"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing action: {str(e)}")

    # Update approval status
    approval.status = "overridden"
    approval.human_category = request.new_category
    approval.human_action = request.action
    approval.target_folder = request.target_folder
    approval.reviewed_by = user.username
    approval.reviewed_at = datetime.utcnow()
    approval.notes = request.notes
    approval.classification_id = new_classification.id  # Link to new classification

    db.commit()

    return {
        "message": "Classification overridden successfully",
        "approval_id": approval_id,
        "new_category": request.new_category,
        "action": request.action,
        "added_to_whitelist": request.add_to_whitelist
    }


@router.post("/{approval_id}/reject")
async def reject_approval(
    approval_id: int,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Reject an approval request (mark as not needing action).

    This leaves the email in its current state but marks the approval as rejected.
    """
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Approval already {approval.status}"
        )

    approval.status = "rejected"
    approval.reviewed_by = user.username
    approval.reviewed_at = datetime.utcnow()
    approval.notes = notes

    db.commit()

    return {
        "message": "Approval rejected",
        "approval_id": approval_id
    }
