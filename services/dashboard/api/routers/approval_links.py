"""
Review and approve ONE card from an alert email, without logging in. The token in the link is the credential.

  GET  /api/approve-links/{token}          the card (changes nothing)
  POST /api/approve-links/{token}/approve  {"confirm": true}   same checks and effects as Approve in the app
  POST /api/approve-links/{token}/reject   {"confirm": true, "reason": "..."}

An unknown token is a plain 404 (no hint whether it ever existed). A link is refused when it has expired, was already used, or the card was decided another way.
The action is recorded as reviewed_by "link:<email>" so the log shows who clicked.
"""
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import NotificationDraft
from routers import notifications as notif

router = APIRouter()


def _links():
    exec_dir = str(Path(__file__).resolve().parents[4] / "execution")
    if exec_dir not in sys.path:
        sys.path.insert(0, exec_dir)
    return __import__("approval_links")


class ActionIn(BaseModel):
    confirm: bool = False
    reason: Optional[str] = None


def _load(db: Session, token: str):
    al = _links()
    link = al.find_link(db, token)
    if link is None:
        raise HTTPException(status_code=404, detail="This link is not valid.")
    return al, link


def _blocked(al, link, draft) -> Optional[str]:
    """Why this link cannot be used now, or None."""
    state = al.link_state(link)
    if state == "used":
        return "used"
    if state == "expired":
        return "expired"
    if draft is None or draft.email_status != "draft":
        return "decided"
    return None


@router.get("/{token}")
async def view_link(token: str, db: Session = Depends(get_db)):
    al, link = _load(db, token)
    draft = db.get(NotificationDraft, link.draft_id)
    reason = _blocked(al, link, draft)
    if reason:
        return {"state": reason, "used_action": link.used_action, "draft_status": draft.email_status if draft else None}
    queue = await notif.get_review_queue(include_done=True, limit=300, db=db, user=SimpleNamespace(username="link"))
    card = next((i for i in queue["items"] if i.get("draft_id") == link.draft_id), None)
    if card is None:
        return {"state": "decided", "draft_status": draft.email_status}
    return {"state": "ready", "expires_at": link.expires_at, "delivery_live": queue.get("delivery_live"), "card": card}


async def _act(token: str, action: str, body: ActionIn, db: Session):
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Confirmation is required.")
    al, link = _load(db, token)
    draft = db.get(NotificationDraft, link.draft_id)
    reason = _blocked(al, link, draft)
    if reason:
        raise HTTPException(status_code=409, detail=f"This link can no longer be used ({reason}).")
    actor = SimpleNamespace(username=f"link:{link.recipient_email}")
    if action == "approve":
        result = await notif.approve_notification(link.draft_id, db=db, user=actor)       # the same guards as the app; a refusal leaves the link usable
    else:
        result = await notif.reject_notification(link.draft_id, notif.RejectRequest(reason=body.reason), db=db, user=actor)
    link.used_at, link.used_action = datetime.utcnow(), "approved" if action == "approve" else "rejected"
    db.commit()
    return {"ok": True, "action": link.used_action, "result": result}


@router.post("/{token}/approve")
async def approve_link(token: str, body: ActionIn, db: Session = Depends(get_db)):
    return await _act(token, "approve", body, db)


@router.post("/{token}/reject")
async def reject_link(token: str, body: ActionIn, db: Session = Depends(get_db)):
    return await _act(token, "reject", body, db)
