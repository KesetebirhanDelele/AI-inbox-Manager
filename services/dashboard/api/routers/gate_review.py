"""
Gate review: the third interview screen's verdicts next to a person's judgement (shadow mode).

Nothing here changes what the pipeline does. Each row is one email the gate looked at; the reviewer says whether it really was news about an
interview ('real') or not ('not_real'). The summary shows where the gate and the reviewer disagree, which is the evidence for (or against)
switching INTERVIEW_GATE_MODE to live. The dangerous disagreement is "gate would hide it, reviewer says it was real".
"""
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import Email, InterviewEvent, InterviewGateReview, NotificationDraft, UserSession

router = APIRouter()


def _gate():
    exec_dir = str(Path(__file__).resolve().parents[4] / "execution")
    if exec_dir not in sys.path:
        sys.path.insert(0, exec_dir)
    import interview_gate
    return interview_gate


def gate_says(row: InterviewGateReview, gate) -> str:
    """'real' (a card should show), 'not_real' (the gate would hide it), or 'unsure' (no usable verdict, or under the confidence floor)."""
    if row.verdict is None:
        return "unsure"
    if row.verdict in gate.SHOWS_CARD:
        return "real"
    return "not_real" if row.would_hide else "unsure"


class Decision(BaseModel):
    decision: str                       # 'real' | 'not_real' | 'clear'
    note: Optional[str] = None


@router.get("/summary")
async def summary(db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)) -> Dict[str, Any]:
    gate = _gate()
    rows = db.query(InterviewGateReview).all()
    decided = [r for r in rows if r.human_decision]
    out = {"total": len(rows), "decided": len(decided), "undecided": len(rows) - len(decided), "mode": gate.gate_mode(),
           "agree": 0, "hid_a_real_one": 0, "showed_a_non_interview": 0, "gate_unsure": 0,
           "cost_usd": round(sum(r.cost_usd or 0 for r in rows), 4)}
    for r in decided:
        says = gate_says(r, gate)
        if says == "unsure":
            out["gate_unsure"] += 1
        elif says == r.human_decision:
            out["agree"] += 1
        elif says == "not_real":
            out["hid_a_real_one"] += 1
        else:
            out["showed_a_non_interview"] += 1
    return out


@router.get("/reviews")
async def reviews(
    show: str = Query("undecided", description="undecided | decided | disagree | all"),
    gate_says_filter: Optional[str] = Query(None, alias="gate", description="real | not_real | unsure"),
    limit: int = Query(100, ge=1, le=300),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    gate = _gate()
    query = (db.query(InterviewGateReview, Email, InterviewEvent)
             .join(Email, Email.id == InterviewGateReview.email_id)
             .outerjoin(InterviewEvent, InterviewEvent.id == InterviewGateReview.event_id)
             .order_by(desc(Email.received_date), desc(InterviewGateReview.id)))
    if show == "undecided":
        query = query.filter(InterviewGateReview.human_decision.is_(None))
    elif show in ("decided", "disagree"):
        query = query.filter(InterviewGateReview.human_decision.isnot(None))
    items = []
    for row, email, event in query.limit(limit * 3).all():
        says = gate_says(row, gate)
        if gate_says_filter and says != gate_says_filter:
            continue
        if show == "disagree" and says in ("unsure", row.human_decision):
            continue
        draft = None
        if event is not None:
            draft = db.query(NotificationDraft).filter(NotificationDraft.interview_event_id == event.id).order_by(NotificationDraft.id).first()
        items.append({
            "id": row.id, "email_id": email.id, "subject": email.subject, "from_address": email.from_address, "received_date": email.received_date,
            "gate_says": says, "verdict": row.verdict, "confidence": row.confidence, "reason": row.reason, "error": row.error,
            "flag": gate.label({"verdict": row.verdict, "round": row.round, "format": row.format}) if row.verdict else None,
            "refers_to_event_id": row.refers_to_event_id, "source": row.source,
            "new_text": row.new_text, "quoted_chars": row.quoted_chars, "history": row.history or [],
            "event": None if event is None else {"id": event.id, "sub_type": event.sub_type, "company": event.company_name,
                                                 "date": event.interview_date, "time": event.interview_time, "format": event.interview_format},
            "notice_status": draft.email_status if draft else None,
            "human_decision": row.human_decision, "human_note": row.human_note, "decided_by": row.decided_by, "decided_at": row.decided_at,
        })
        if len(items) >= limit:
            break
    return items


@router.post("/reviews/{review_id}/decision")
async def decide(review_id: int, body: Decision, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)) -> Dict[str, Any]:
    if body.decision not in ("real", "not_real", "clear"):
        raise HTTPException(status_code=422, detail="decision must be real, not_real or clear")
    row = db.get(InterviewGateReview, review_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if body.decision == "clear":
        row.human_decision = row.decided_by = row.decided_at = row.human_note = None
    else:
        row.human_decision, row.decided_by, row.decided_at = body.decision, user.username, datetime.utcnow()
        row.human_note = (body.note or "")[:300] or None
    db.commit()
    return {"id": row.id, "human_decision": row.human_decision, "decided_by": row.decided_by}
