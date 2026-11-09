"""
Sign in by an emailed link, and the list of people allowed to (Settings page).

/api/signin/* need no login (the link is the key). /api/users/* need a signed-in person who may manage the list.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import create_session, get_current_user
from database import get_db
from models import AllowedUser, UserSession

logger = logging.getLogger(__name__)
signin_router = APIRouter()
users_router = APIRouter()

NEUTRAL = "If that email is on the approved list, a sign-in link is on its way. It expires in a few minutes."


def _ll():
    exec_dir = str(Path(__file__).resolve().parents[4] / "execution")
    if exec_dir not in sys.path:
        sys.path.insert(0, exec_dir)
    return __import__("login_links")


def _send_link_email(email: str, url: str) -> None:
    """Runs after the response, so a known and an unknown email take the same time (the page cannot be used to find out who is on the list)."""
    try:
        from send_notification import send_email
        result = send_email(recipient_email=email, subject="[InboxGenius] Your sign-in link", body=_ll().link_email_text(url), bcc="")
        if result.get("status") != "sent":
            logger.error("Sign-in link email was not sent: %s", result.get("error"))
    except Exception:
        logger.exception("Sign-in link email failed")


class RequestIn(BaseModel):
    email: str


class RedeemIn(BaseModel):
    token: str


@signin_router.post("/request")
async def request_link(body: RequestIn, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    ll = _ll()
    email = ll.normalize_email(body.email)
    if ll.valid_email(email):
        url = ll.create_link(db, email)
        if url:
            tasks.add_task(_send_link_email, email, url)
        else:
            logger.info("Sign-in link not created (not on the list, removed, or asked too often)")
    return {"message": NEUTRAL}


@signin_router.post("/redeem")
async def redeem_link(body: RedeemIn, response: Response, db: Session = Depends(get_db)):
    ll = _ll()
    state, user = ll.redeem(db, body.token)
    if state != "ok":
        raise HTTPException(status_code=400, detail={"used": "This link was already used. Ask for a new one.",
                                                      "expired": "This link has expired. Ask for a new one."}.get(state, "This link is not valid. Ask for a new one."))
    session = create_session(user.email, db, role=user.role, hours=ll.session_hours())
    response.set_cookie(key="session_token", value=session["session_token"], httponly=True, secure=True, samesite="none",
                        max_age=ll.session_hours() * 3600)
    logger.info("User %s signed in by link", user.email)
    return {"message": "Login successful", "username": user.email}


# ── the list of people ────────────────────────────────────────────────────────────────────

def can_manage(db: Session, user: UserSession) -> bool:
    """A person on the list who may manage it, or a shared-password admin (no row on the list: the people who run the system)."""
    row = db.query(AllowedUser).filter(AllowedUser.email == (user.username or "").strip().lower()).first()
    if row is not None:
        return bool(row.active and row.can_manage and user.role == "admin")
    return user.role == "admin"


def _require_manager(db: Session, user: UserSession) -> None:
    if not can_manage(db, user):
        raise HTTPException(status_code=403, detail="Only the people who manage access can change this list.")


def _out(u: AllowedUser) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "can_manage": u.can_manage, "active": u.active,
            "last_login_at": u.last_login_at, "added_by": u.added_by}


class UserIn(BaseModel):
    email: str
    name: Optional[str] = None
    role: str = "admin"
    can_manage: bool = False


class UserPatch(BaseModel):
    active: Optional[bool] = None
    role: Optional[str] = None
    can_manage: Optional[bool] = None
    name: Optional[str] = None


@users_router.get("")
async def list_users(db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    return {"can_manage": can_manage(db, user), "users": [_out(u) for u in db.query(AllowedUser).order_by(AllowedUser.id).all()] if can_manage(db, user) else []}


@users_router.post("")
async def add_user(body: UserIn, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    _require_manager(db, user)
    ll = _ll()
    email = ll.normalize_email(body.email)
    if not ll.valid_email(email):
        raise HTTPException(status_code=422, detail="That does not look like an email address.")
    if body.role not in ll.ROLES:
        raise HTTPException(status_code=422, detail="Role must be admin or stakeholder.")
    row = db.query(AllowedUser).filter(AllowedUser.email == email).first()
    if row is None:
        row = AllowedUser(email=email, created_at=datetime.utcnow())
        db.add(row)
    row.name, row.role, row.can_manage, row.active, row.added_by = (body.name or row.name), body.role, body.can_manage, True, user.username
    db.commit()
    db.refresh(row)
    return _out(row)


@users_router.patch("/{user_id}")
async def change_user(user_id: int, body: UserPatch, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    _require_manager(db, user)
    row = db.get(AllowedUser, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such person.")
    if body.role is not None:
        if body.role not in _ll().ROLES:
            raise HTTPException(status_code=422, detail="Role must be admin or stakeholder.")
        row.role = body.role
    if body.active is not None:
        row.active = body.active
        if not body.active:                # removing a person also ends any session they have open
            db.query(UserSession).filter(UserSession.username == row.email).delete()
    if body.can_manage is not None:
        row.can_manage = body.can_manage
    if body.name is not None:
        row.name = body.name
    db.commit()
    db.refresh(row)
    return _out(row)
