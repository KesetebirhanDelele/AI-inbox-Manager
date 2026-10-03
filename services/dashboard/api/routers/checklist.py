"""
Interview process checklist API endpoints.

Provides endpoints for retrieving checklist definitions with completion
state, and toggling step completion.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from database import get_db
from auth import get_current_user
from models import InterviewEvent, ChecklistCompletion, UserSession
from checklist_steps import CHECKLIST_DEFINITIONS, get_all_step_keys, definition_key

router = APIRouter()


# Pydantic response models

class SubStepResponse(BaseModel):
    key: str
    label: str
    is_completed: bool
    completed_by: Optional[str] = None
    completed_at: Optional[datetime] = None


class MainStepResponse(BaseModel):
    key: str
    label: str
    is_completed: bool
    completed_by: Optional[str] = None
    completed_at: Optional[datetime] = None
    sub_steps: List[SubStepResponse]


class ChecklistResponse(BaseModel):
    interview_event_id: int
    sub_type: str
    sub_type_label: str
    steps: List[MainStepResponse]
    total_steps: int
    completed_steps: int
    progress_percent: float


class ToggleStepRequest(BaseModel):
    step_key: str
    is_completed: bool


# Endpoints

@router.get("/{interview_event_id}", response_model=ChecklistResponse)
async def get_checklist(
    interview_event_id: int,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Get checklist definition and completion state for an interview event."""
    event = db.query(InterviewEvent).filter(
        InterviewEvent.id == interview_event_id
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Interview event not found")

    normalized = definition_key(event.sub_type)
    defn = CHECKLIST_DEFINITIONS[normalized]

    # Load all completions for this event
    completions = (
        db.query(ChecklistCompletion)
        .filter(ChecklistCompletion.interview_event_id == interview_event_id)
        .all()
    )
    completion_map = {c.step_key: c for c in completions}

    # Build response with definitions merged with completion state
    total = 0
    completed = 0
    steps = []

    for step_def in defn["steps"]:
        main_comp = completion_map.get(step_def["key"])
        sub_steps_out = []

        for sub_def in step_def["sub_steps"]:
            total += 1
            sub_comp = completion_map.get(sub_def["key"])
            is_done = bool(sub_comp and sub_comp.is_completed)
            if is_done:
                completed += 1
            sub_steps_out.append(SubStepResponse(
                key=sub_def["key"],
                label=sub_def["label"],
                is_completed=is_done,
                completed_by=sub_comp.completed_by if sub_comp else None,
                completed_at=sub_comp.completed_at if sub_comp else None,
            ))

        # Main step also counts
        total += 1
        main_done = bool(main_comp and main_comp.is_completed)
        if main_done:
            completed += 1

        steps.append(MainStepResponse(
            key=step_def["key"],
            label=step_def["label"],
            is_completed=main_done,
            completed_by=main_comp.completed_by if main_comp else None,
            completed_at=main_comp.completed_at if main_comp else None,
            sub_steps=sub_steps_out,
        ))

    return ChecklistResponse(
        interview_event_id=interview_event_id,
        sub_type=normalized,
        sub_type_label=defn["label"],
        steps=steps,
        total_steps=total,
        completed_steps=completed,
        progress_percent=round((completed / total * 100) if total > 0 else 0, 1),
    )


@router.put("/{interview_event_id}/toggle")
async def toggle_step(
    interview_event_id: int,
    request: ToggleStepRequest,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
):
    """Toggle a checklist step completion state."""
    event = db.query(InterviewEvent).filter(
        InterviewEvent.id == interview_event_id
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Interview event not found")

    # Validate step_key against known definitions
    valid_keys = get_all_step_keys(event.sub_type)
    if request.step_key not in valid_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid step_key '{request.step_key}' for sub_type '{event.sub_type}'"
        )

    # Upsert: find existing or create new
    existing = (
        db.query(ChecklistCompletion)
        .filter(
            ChecklistCompletion.interview_event_id == interview_event_id,
            ChecklistCompletion.step_key == request.step_key,
        )
        .first()
    )

    if existing:
        existing.is_completed = request.is_completed
        existing.completed_by = user.username if request.is_completed else None
        existing.completed_at = datetime.utcnow() if request.is_completed else None
    else:
        new_comp = ChecklistCompletion(
            interview_event_id=interview_event_id,
            step_key=request.step_key,
            is_completed=request.is_completed,
            completed_by=user.username if request.is_completed else None,
            completed_at=datetime.utcnow() if request.is_completed else None,
        )
        db.add(new_comp)

    db.commit()

    return {
        "interview_event_id": interview_event_id,
        "step_key": request.step_key,
        "is_completed": request.is_completed,
    }
