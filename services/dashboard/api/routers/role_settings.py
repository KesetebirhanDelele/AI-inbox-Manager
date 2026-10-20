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
    review_alert_enabled: bool = True
    backup_after_hours: float = 2.0
    staff_alerts_enabled: bool = True


class RoleIn(BaseModel):
    email: str
    active: bool = True


class PilotIn(BaseModel):
    limit: int


class AlertSettingsIn(BaseModel):
    review_alert_enabled: bool
    backup_after_hours: float
    staff_alerts_enabled: bool = True


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
                         review_alert_enabled=_execution("review_alerts").enabled(db),
                         staff_alerts_enabled=roles.staff_alerts_on(db),
                         backup_after_hours=_execution("stale_draft_alerts").stale_minutes(None, db) / 60,
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


def _set(db: Session, key: str, value: str) -> None:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None:
        db.add(SystemConfig(key=key, value=value))
    else:
        row.value = value


@router.put("/alert-settings")
async def set_alert_settings(body: AlertSettingsIn, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    """The approver's "new card" email on or off, and how many business hours before the backup is told."""
    if not 0.25 <= body.backup_after_hours <= 72:
        raise HTTPException(status_code=422, detail="The backup time must be between 0.25 and 72 business hours")
    _set(db, _execution("roles").STAFF_ALERTS_KEY, "on" if body.staff_alerts_enabled else "off")
    _set(db, _execution("review_alerts").ENABLED_KEY, "on" if body.review_alert_enabled else "off")
    _set(db, _execution("stale_draft_alerts").HOURS_KEY, str(body.backup_after_hours))
    db.commit()
    return {"review_alert_enabled": body.review_alert_enabled, "backup_after_hours": body.backup_after_hours, "staff_alerts_enabled": body.staff_alerts_enabled}


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
