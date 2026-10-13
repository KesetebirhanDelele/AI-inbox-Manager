"""
Flags shown beside every interview notice, so a person decides with the facts in front of them (Kes, 2026-10-13: nothing is silently
dropped; every job interview is flagged, including "not on the roster" and/or "not in GHL", and a person still declines to stop a notice).

  roster: listed | name_only | unlisted | unknown     (the live roster sheet: personal or application email, then exact name)
  ghl:    found | not_found | check | unknown          (a READ-ONLY GHL lookup; nothing is ever written here)

Both are cached for a while and both fail soft: if the roster or GHL cannot be reached the flag is "unknown" and the notice is shown as before.
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional

import student_roster as sr

logger = logging.getLogger(__name__)
TTL_SECONDS = 30 * 60
_GHL_CACHE: Dict[Any, Any] = {}
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_ROOT, ".env"))
    except Exception:
        pass


def _student_dict(student: Any) -> Dict[str, Any]:
    return {"id": getattr(student, "id", None), "full_name": getattr(student, "full_name", None),
            "username": getattr(student, "username", None), "personal_email": getattr(student, "personal_email", None),
            "assigned_gmail": getattr(student, "assigned_gmail", None)}


def ghl_status(student: Any, client=None, clock=time.time) -> str:
    """found | not_found | check (ambiguous or odd: a person must look) | unknown (GHL not reachable or not configured)."""
    key = (getattr(student, "id", None), getattr(student, "personal_email", None), getattr(student, "assigned_gmail", None),
           getattr(student, "phone_number", None))
    hit = _GHL_CACHE.get(key)
    if hit and clock() - hit[0] < TTL_SECONDS:
        return hit[1]
    result = "unknown"
    try:
        import ghl_client as gc
        import notify_channels as nc
        if client is None:
            _load_env()
            cfg = gc.GhlConfig.from_env()
            client = gc.GhlClient(cfg) if cfg.can_read else None
        if client is not None:
            contact, _how, problem = nc.find_ghl_contact(client, student)
            result = "found" if contact else ("not_found" if "no GHL contact matches" in problem else "check")
    except Exception as exc:
        logger.warning(f"GHL flag lookup skipped: {exc}")
    if result != "unknown":
        _GHL_CACHE[key] = (clock(), result)
    return result


def roster_status(student: Any, roster: Optional[List[sr.RosterRow]] = None) -> str:
    _load_env()
    return sr.standing(_student_dict(student), roster if roster is not None else sr.cached_roster())


def warnings_for(roster: str, ghl: str) -> List[str]:
    """The words a person sees. Never a blocker: the person decides to approve or reject."""
    out = []
    if roster == "unlisted":
        out.append("NOT ON THE ROSTER: no personal or application email and no name on the student roster sheet matches this person. "
                   "Check before approving; reject the student if they are not ours.")
    elif roster == "name_only":
        out.append("On the roster by NAME only (the email differs): check it is the same person before approving.")
    if ghl == "not_found":
        out.append("NOT IN GHL: no GHL contact matches this student's email or phone (ours or the roster's). The call, text and email "
                   "cannot reach them until GHL or the roster sheet is corrected.")
    elif ghl == "check":
        out.append("GHL lookup needs a person: the student's emails and phone point to different or unclear GHL contacts.")
    return out
