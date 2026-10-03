"""
Roles and notification settings (the dashboard's Settings page).

Who approves, who takes callbacks and who is told about stale drafts are ROLES assigned here, not people written into the code.
Also the pilot limit: until it is lifted, only that many approved notices may start a follow-up sequence (Ali: three that the approver
approves by hand, then everyone if it runs clean).
"""
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import RoleAssignment, NotificationSequence, SystemConfig, UserSession

router = APIRouter()

PILOT_KEY = "notify_pilot_limit"
PILOT_DEFAULT = "3"


def _execution(name: str):
    exec_dir = str(Path(__file__).resolve().parents[4] / "execution")
    if exec_dir not in sys.path:
        sys.path.insert(0, exec_dir)
    return __import__(name)


def pilot_limit(db: Session) -> int:
    """How many approved notices may start a sequence (0 = no limit)."""
    roles = _execution("roles")
    try:
        return max(0, int(roles.get_setting(db, PILOT_KEY, PILOT_DEFAULT)))
    except ValueError:
        return int(PILOT_DEFAULT)


class RoleOut(BaseModel):
    role: str
    label: str
    help: str
    email: str
    active: bool
    source: str            # database | environment | none


class RolesResponse(BaseModel):
    roles: List[RoleOut]
    pilot_limit: int
    pilot_used: int
    business_hours: str


class RoleIn(BaseModel):
    email: str
    active: bool = True


class PilotIn(BaseModel):
    limit: int


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("", response_model=RolesResponse)
async def get_roles(db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    roles = _execution("roles")
    hours = _execution("business_hours").BusinessHours.from_env()
    out = []
    for role in roles.ROLES:
        row = (db.query(RoleAssignment).filter(RoleAssignment.role == role).order_by(RoleAssignment.id.desc()).first())
        env_email = roles.role_email(None, role)
        if row is not None and (row.email or "").strip() and row.active:
            email, source, active = row.email.strip(), "database", True
        elif env_email:
            email, source, active = env_email, "environment", True
        else:
            email, source, active = (row.email or "").strip() if row else "", "none", bool(row.active) if row else False
        out.append(RoleOut(role=role, label=roles.ROLE_LABELS[role], help=roles.ROLE_HELP[role], email=email, active=active, source=source))
    used = db.query(NotificationSequence).count()
    days = ", ".join(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d] for d in hours.days)
    return RolesResponse(roles=out, pilot_limit=pilot_limit(db), pilot_used=used,
                         business_hours=f"{days}, {hours.start_hour:02d}:00 to {hours.end_hour:02d}:00 ({hours.tz})")


@router.put("/pilot-limit")
async def set_pilot_limit(body: PilotIn, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    if body.limit < 0 or body.limit > 100000:
        raise HTTPException(status_code=422, detail="limit must be 0 (no limit) or a positive number")
    row = db.query(SystemConfig).filter(SystemConfig.key == PILOT_KEY).first()
    if row is None:
        db.add(SystemConfig(key=PILOT_KEY, value=str(body.limit)))
    else:
        row.value = str(body.limit)
    db.commit()
    return {"pilot_limit": body.limit}


@router.put("/{role}")
async def assign_role(role: str, body: RoleIn, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    roles = _execution("roles")
    if role not in roles.ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown role {role!r}")
    email = (body.email or "").strip()
    if email and not _EMAIL.match(email):
        raise HTTPException(status_code=422, detail="That does not look like an email address")
    row = db.query(RoleAssignment).filter(RoleAssignment.role == role).order_by(RoleAssignment.id.desc()).first()
    if row is None:
        row = RoleAssignment(role=role)
        db.add(row)
    row.email, row.active, row.updated_by, row.updated_at = email, bool(body.active and email), user.username, datetime.utcnow()
    db.commit()
    return {"role": role, "email": row.email, "active": row.active}
