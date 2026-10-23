"""
Callbacks waiting for a person (students who called back about an interview).

The AI receptionist only takes the message; the callback owner (a role) calls the student back and clicks "Called back". The list here feeds the
approval screen's "Callbacks waiting" section and the "Callback needed" flag on the student's interviews.
"""
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import CallbackRequest, InterviewEvent, Student, UserSession

router = APIRouter()


def _execution(name: str):
    exec_dir = str(Path(__file__).resolve().parents[4] / "execution")
    if exec_dir not in sys.path:
        sys.path.insert(0, exec_dir)
    return __import__(name)


class CallbackOut(BaseModel):
    id: int
    status: str
    received_at: datetime
    due_at: datetime
    overdue: bool
    caller_number: Optional[str]
    said: Optional[str]
    student_id: Optional[int]
    student_name: Optional[str]
    student_email: Optional[str]
    interviews: List[str]
    done_by: Optional[str]
    done_at: Optional[datetime]


def callback_item(db: Session, req: CallbackRequest, now: Optional[datetime] = None) -> CallbackOut:
    cbs = _execution("callbacks")
    bh = _execution("business_hours")
    now = now or datetime.utcnow()
    hours = bh.BusinessHours.from_env()
    student = db.get(Student, req.student_id) if req.student_id else None
    interviews = []
    if student is not None:
        for ev in (db.query(InterviewEvent).filter(InterviewEvent.student_id == student.id)
                   .order_by(desc(InterviewEvent.id)).limit(3).all()):
            interviews.append(", ".join(x for x in (ev.company_name, ev.position_title) if x) or "interview")
    waited = bh.business_minutes_between(req.received_at, req.done_at or now, hours)
    return CallbackOut(
        id=req.id, status=req.status, received_at=req.received_at, due_at=cbs.due_at(req.received_at, hours),
        overdue=req.status == "open" and waited >= cbs.SLA_BUSINESS_MINUTES, caller_number=req.caller_number, said=req.said,
        student_id=req.student_id, student_name=student.full_name if student else None,
        student_email=(student.personal_email or student.assigned_gmail) if student else None,
        interviews=interviews, done_by=req.done_by, done_at=req.done_at)


@router.get("", response_model=List[CallbackOut])
async def list_callbacks(include_done: bool = Query(False), db: Session = Depends(get_db),
                         user: UserSession = Depends(get_current_user)):
    # only callers matched to a roster student are interview callbacks; "ignored" rows and old unmatched rows are never shown
    q = db.query(CallbackRequest).filter(CallbackRequest.student_id.isnot(None), CallbackRequest.status != "ignored")
    if not include_done:
        q = q.filter(CallbackRequest.status == "open")
    return [callback_item(db, r) for r in q.order_by(CallbackRequest.received_at).limit(200).all()]


@router.post("/{callback_id}/done")
async def mark_called_back(callback_id: int, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    req = db.get(CallbackRequest, callback_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Callback not found")
    if req.status != "done":
        req.status, req.done_by, req.done_at = "done", user.username, datetime.utcnow()
        db.commit()
    return {"id": req.id, "status": req.status, "done_by": req.done_by}


@router.post("/{callback_id}/cancel")
async def cancel_callback(callback_id: int, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    """The notice was wrong (not a real interview callback, or already handled): clear it and stop the overdue clock. The row is kept for the record."""
    req = db.get(CallbackRequest, callback_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Callback not found")
    if req.status == "open":
        req.status, req.done_by, req.done_at = "cancelled", user.username, datetime.utcnow()
        db.commit()
    return {"id": req.id, "status": req.status, "done_by": req.done_by}
