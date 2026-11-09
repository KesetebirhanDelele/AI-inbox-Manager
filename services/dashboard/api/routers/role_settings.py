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
    live_delivery: dict = {}


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
                         live_delivery=live_delivery_status(db),
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


class LiveIn(BaseModel):
    enabled: bool
    confirm_text: str = ""


def live_delivery_status(db: Session) -> dict:
    """Armed = the server .env allows live writes; switch = the Settings choice; live = both. Who and when changed it last."""
    roles = _execution("roles")
    armed = bool(_execution("ghl_client").GhlConfig.from_env().armed)
    switch = roles.live_delivery_on(db)
    return {"armed": armed, "switch_on": switch, "live": armed and switch,
            "changed_by": roles.get_setting(db, roles.LIVE_DELIVERY_KEY + "_changed_by", ""),
            "changed_at": roles.get_setting(db, roles.LIVE_DELIVERY_KEY + "_changed_at", "")}


@router.put("/live-delivery")
async def set_live_delivery(body: LiveIn, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    """
    Turn live delivery to students on or off. Off needs nothing and takes effect on the very next send.
    On needs the server to be armed (env) and the typed words GO LIVE, so it can neither be clicked by accident nor left waiting for the server to be armed later.
    """
    roles = _execution("roles")
    if body.enabled:
        if not _execution("ghl_client").GhlConfig.from_env().armed:
            raise HTTPException(status_code=422, detail="The server is not armed for live delivery, so this switch cannot be turned on yet. Arming is a server step.")
        if body.confirm_text.strip().upper() != "GO LIVE":
            raise HTTPException(status_code=422, detail="Type GO LIVE to confirm that real students will be called, texted and emailed.")
    _set(db, roles.LIVE_DELIVERY_KEY, "on" if body.enabled else "off")
    _set(db, roles.LIVE_DELIVERY_KEY + "_changed_by", user.username)
    _set(db, roles.LIVE_DELIVERY_KEY + "_changed_at", datetime.utcnow().isoformat(timespec="seconds") + "Z")
    db.commit()
    return live_delivery_status(db)


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


class AgentIn(BaseModel):
    agent: str
    email: str = ""


@router.get("/agents")
async def get_agents(db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    """Every agent named on the roster sheet (with how many active students) plus the email set for each. A card goes to its student's agent first."""
    routing = _execution("agent_routing")
    sr = _execution("student_roster")
    emails = routing.agent_emails(db)
    _execution("student_flags")._load_env()
    roster = sr.cached_roster()
    seen = {}
    for row in roster or []:
        name = (row.agent or "").strip()
        if name and row.active:
            k = routing.key(name)
            seen.setdefault(k, {"agent": name, "students": 0})["students"] += 1
    for k, typed in routing.agent_names(db).items():           # an agent added by hand (or with no active students) is still listed
        seen.setdefault(k, {"agent": typed, "students": 0})
    out = [{"agent": v["agent"], "students": v["students"], "email": emails.get(k, "")} for k, v in seen.items()]
    return {"roster_readable": bool(roster), "agents": sorted(out, key=lambda a: a["agent"].lower())}


@router.put("/agents")
async def set_agent(body: AgentIn, db: Session = Depends(get_db), user: UserSession = Depends(get_current_user)):
    routing = _execution("agent_routing")
    email = (body.email or "").strip()
    if email and not _EMAIL.match(email):
        raise HTTPException(status_code=422, detail="That does not look like an email address")
    if not routing.key(body.agent):
        raise HTTPException(status_code=422, detail="Agent name is empty")
    routing.set_agent_email(db, body.agent, email, user.username)
    return {"agent": body.agent, "email": email}


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
