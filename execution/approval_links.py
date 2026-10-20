"""
Secure review-and-approve links for the alert emails (execution side: create links; the dashboard API serves the page and does the approve/reject).

A link is `<DASHBOARD_BASE_URL>/approve/<token>`. The token is random (32 bytes), only its SHA-256 is stored, it expires (APPROVE_LINK_HOURS, default 24), and it is
used up by the first approve or reject. The link opens a page with the card and a second confirmation tap; opening it changes nothing.
"""
import hashlib
import os
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "execution", _ROOT / "services" / "dashboard" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DEFAULT_BASE_URL = "https://2-29-47-89.nip.io"


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def base_url(env=None) -> str:
    env = os.environ if env is None else env
    return (env.get("DASHBOARD_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def ttl_hours(env=None) -> float:
    env = os.environ if env is None else env
    try:
        return max(0.25, float(env.get("APPROVE_LINK_HOURS") or 24))
    except ValueError:
        return 24.0


def create_link(db, draft_id: int, role: str, recipient_email: str, now: Optional[datetime] = None, env=None) -> str:
    """Store a new link for this card and return its URL (the only place the token ever appears)."""
    import models as M
    now = now or datetime.utcnow()
    token = secrets.token_urlsafe(32)
    db.add(M.ApprovalLink(token_hash=hash_token(token), draft_id=draft_id, role=role, recipient_email=recipient_email,
                          created_at=now, expires_at=now + timedelta(hours=ttl_hours(env))))
    db.commit()
    return f"{base_url(env)}/approve/{token}"


def find_link(db, token: str):
    import models as M
    if not token or len(token) > 200:
        return None
    return db.query(M.ApprovalLink).filter(M.ApprovalLink.token_hash == hash_token(token)).first()


def link_state(link, now: Optional[datetime] = None) -> str:
    """used | expired | ok"""
    now = now or datetime.utcnow()
    if link.used_at is not None:
        return "used"
    if link.expires_at <= now:
        return "expired"
    return "ok"
