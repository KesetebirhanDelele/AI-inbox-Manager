"""
Sign in by an emailed one-time link (execution side: who is allowed, create / redeem links).

The username is the person's email. The link is `<DASHBOARD_BASE_URL>/signin/<token>`: random (32 bytes), only its SHA-256 is stored, valid LOGIN_LINK_MINUTES
(default 15), used up by the first sign-in. Opening the page changes nothing; the person taps Continue (so a mail scanner that fetches the link cannot use it up).
Asking for a link never reveals whether an email is on the list.
"""
import hashlib
import os
import re
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "execution", _ROOT / "services" / "dashboard" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MAX_LINKS_PER_HOUR = 5          # per email: nobody can flood a person's inbox
ROLES = ("admin", "stakeholder")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(_EMAIL.match(normalize_email(email))) and len(email) <= 255


def base_url(env=None) -> str:
    env = os.environ if env is None else env
    return (env.get("DASHBOARD_BASE_URL") or "https://2-29-47-89.nip.io").strip().rstrip("/")


def link_minutes(env=None) -> int:
    env = os.environ if env is None else env
    try:
        return max(1, int(env.get("LOGIN_LINK_MINUTES") or 15))
    except ValueError:
        return 15


def session_hours(env=None) -> int:
    env = os.environ if env is None else env
    try:
        return max(1, int(env.get("LINK_SESSION_HOURS") or 168))
    except ValueError:
        return 168


def find_user(db, email: str):
    """The active allowed user for this email, or None."""
    import models as M
    return db.query(M.AllowedUser).filter(M.AllowedUser.email == normalize_email(email), M.AllowedUser.active.is_(True)).first()


def create_link(db, email: str, now: Optional[datetime] = None, env=None) -> Optional[str]:
    """URL of a new link for an allowed email; None when the email is not allowed or asked too often (the caller says the same thing either way)."""
    import models as M
    now = now or datetime.utcnow()
    user = find_user(db, email)
    if user is None:
        return None
    recent = db.query(M.LoginLink).filter(M.LoginLink.email == user.email, M.LoginLink.created_at >= now - timedelta(hours=1)).count()
    if recent >= MAX_LINKS_PER_HOUR:
        return None
    token = secrets.token_urlsafe(32)
    db.add(M.LoginLink(token_hash=hash_token(token), email=user.email, created_at=now, expires_at=now + timedelta(minutes=link_minutes(env))))
    db.commit()
    return f"{base_url(env)}/signin/{token}"


def link_email_text(url: str, env=None) -> str:
    return (f"Open this link to sign in to InboxGenius:\n\n{url}\n\nIt works once and expires in {link_minutes(env)} minutes. "
            "If you did not ask to sign in, ignore this email: nothing happens unless the link is opened.")


def redeem(db, token: str, now: Optional[datetime] = None):
    """Use the link up. Returns (state, user): state is ok | used | expired | invalid, user only when ok."""
    import models as M
    now = now or datetime.utcnow()
    if not token or len(token) > 200:
        return "invalid", None
    link = db.query(M.LoginLink).filter(M.LoginLink.token_hash == hash_token(token)).first()
    if link is None:
        return "invalid", None
    if link.used_at is not None:
        return "used", None
    if link.expires_at <= now:
        return "expired", None
    user = find_user(db, link.email)
    if user is None:                       # removed after the link was sent
        return "invalid", None
    link.used_at = now
    user.last_login_at = now
    db.commit()
    return "ok", user
