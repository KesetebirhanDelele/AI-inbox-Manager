"""
Review and approve ONE card from an alert email, without logging in. Two things are needed: the link, and a one-time 6-digit code emailed to the approver's address,
so a forwarded link is useless to anyone who cannot read that mailbox.

  GET  /api/approve-links/{token}               the link's state only (needs_code | used | expired | decided); shows no card
  POST /api/approve-links/{token}/send-code     emails a fresh code to the address the alert went to (a button on the page, so mail scanners send nothing)
  POST /api/approve-links/{token}/open          {"code": "..."}  -> the card and the full original email
  POST /api/approve-links/{token}/approve       {"confirm": true, "code": "..."}   same checks and effects as Approve in the app
  POST /api/approve-links/{token}/reject        {"confirm": true, "code": "...", "reason": "..."}

An unknown token is a plain 404. The decision uses the code up, so the next decision needs a new one. A refused approval (a normal guard such as "no student") leaves the
code and link usable. The action is recorded as reviewed_by "link:<email>".
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
from models import Email, InterviewEvent, NotificationDraft
from routers import notifications as notif
from utils_text import clean_email_text

router = APIRouter()

ORIGINAL_EMAIL_MAX_CHARS = 20000          # the full employer email for the approver to read (the app's Review card shows the first 1500)


def _links():
    exec_dir = str(Path(__file__).resolve().parents[4] / "execution")
    if exec_dir not in sys.path:
        sys.path.insert(0, exec_dir)
    return __import__("approval_links")


class OpenIn(BaseModel):
    code: str = ""


class ActionIn(BaseModel):
    confirm: bool = False
    code: str = ""
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


def _require_code(al, db: Session, link, code: str, consume: bool = False) -> None:
    result = al.check_code(db, link, code, consume=consume)
    if result == "ok":
        return
    messages = {
        "none": (403, "Tap \"Email me a code\" first."),
        "wrong": (403, "That code is not right."),
        "expired": (403, "That code has expired. Ask for a new one."),
        "locked": (423, "Too many wrong tries. Ask for a new code."),
    }
    status_code, detail = messages[result]
    raise HTTPException(status_code=status_code, detail=detail)


@router.get("/{token}")
async def view_link(token: str, db: Session = Depends(get_db)):
    al, link = _load(db, token)
    draft = db.get(NotificationDraft, link.draft_id)
    reason = _blocked(al, link, draft)
    if reason:
        return {"state": reason, "used_action": link.used_action, "draft_status": draft.email_status if draft else None}
    return {"state": "needs_code", "sent_to": al.mask_email(link.recipient_email), "expires_at": link.expires_at}


@router.post("/{token}/send-code")
async def send_code(token: str, db: Session = Depends(get_db)):
    al, link = _load(db, token)
    draft = db.get(NotificationDraft, link.draft_id)
    reason = _blocked(al, link, draft)
    if reason:
        raise HTTPException(status_code=409, detail=f"This link can no longer be used ({reason}).")
    try:
        code = al.issue_code(db, link)
    except al.TooManyCodes:
        raise HTTPException(status_code=429, detail="Too many codes were requested for this link. Wait an hour, or open the Review page in the app.")
    from send_notification import send_email
    body = (f"Your InboxGenius approval code is {code}\n\nIt works for {al.CODE_MINUTES} minutes and for one approval or rejection. "
            "If you did not just open an approval link, ignore this email: nothing happens without the code.")
    result = send_email(recipient_email=link.recipient_email, subject=f"[InboxGenius] Your approval code: {code}", body=body, bcc="")
    if result.get("status") != "sent":
        raise HTTPException(status_code=502, detail="The code email could not be sent. Try again, or open the Review page in the app.")
    return {"sent": True, "sent_to": al.mask_email(link.recipient_email), "valid_minutes": al.CODE_MINUTES}


@router.post("/{token}/open")
async def open_link(token: str, body: OpenIn, db: Session = Depends(get_db)):
    al, link = _load(db, token)
    draft = db.get(NotificationDraft, link.draft_id)
    reason = _blocked(al, link, draft)
    if reason:
        return {"state": reason, "used_action": link.used_action, "draft_status": draft.email_status if draft else None}
    _require_code(al, db, link, body.code)
    queue = await notif.get_review_queue(include_done=True, limit=300, db=db, user=SimpleNamespace(username="link"))
    card = next((i for i in queue["items"] if i.get("draft_id") == link.draft_id), None)
    if card is None:
        return {"state": "decided", "draft_status": draft.email_status}
    event = db.get(InterviewEvent, draft.interview_event_id)
    email = db.get(Email, event.email_id) if event is not None else None
    original = None if email is None else {
        "subject": email.subject, "from_address": email.from_address, "received_date": email.received_date,
        "text": clean_email_text(email.full_body or email.body_preview or "")[:ORIGINAL_EMAIL_MAX_CHARS],
    }
    return {"state": "ready", "expires_at": link.expires_at, "delivery_live": queue.get("delivery_live"), "card": card, "original_email": original}


async def _act(token: str, action: str, body: ActionIn, db: Session):
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Confirmation is required.")
    al, link = _load(db, token)
    draft = db.get(NotificationDraft, link.draft_id)
    reason = _blocked(al, link, draft)
    if reason:
        raise HTTPException(status_code=409, detail=f"This link can no longer be used ({reason}).")
    _require_code(al, db, link, body.code)                       # checked first, used up only when the decision succeeds
    actor = SimpleNamespace(username=f"link:{link.recipient_email}")
    if action == "approve":
        result = await notif.approve_notification(link.draft_id, db=db, user=actor)       # the same guards as the app; a refusal leaves the link and code usable
    else:
        result = await notif.reject_notification(link.draft_id, notif.RejectRequest(reason=body.reason), db=db, user=actor)
    al.check_code(db, link, body.code, consume=True)
    link.used_at, link.used_action = datetime.utcnow(), "approved" if action == "approve" else "rejected"
    db.commit()
    return {"ok": True, "action": link.used_action, "result": result}


@router.post("/{token}/approve")
async def approve_link(token: str, body: ActionIn, db: Session = Depends(get_db)):
    return await _act(token, "approve", body, db)


@router.post("/{token}/reject")
async def reject_link(token: str, body: ActionIn, db: Session = Depends(get_db)):
    return await _act(token, "reject", body, db)
