"""
Read the live student roster (a Google Sheet kept by staff) and compare it with the students this app knows.

The roster sheet is a values-only copy of the columns we need (Agent, Name, STATUS, New Email Address, Personal Email Address), filled
by an Apps Script from the master sheet. This module only READS it, with a read-only service account; it never writes to the sheet,
to GHL or to the student records. Matching is pure logic so it can be tested without any network.
"""
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
ACTIVE_STATUSES = ("active", "in progress")
_EMAIL = re.compile(r"[^\s,;<>()\[\]]+@[^\s,;<>()\[\]]+\.[^\s,;<>()\[\]]+")


def norm_email(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def norm_name(value: Optional[str]) -> str:
    """Lower-case letters only, single spaces: 'Kwadjossan  Isaac.' == 'kwadjossan isaac'."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z\s]", " ", (value or "").lower())).strip()


def name_tokens(value: Optional[str]) -> set:
    return {t for t in norm_name(value).split() if len(t) > 1}


@dataclass
class RosterRow:
    name: str
    status: str
    agent: str = ""
    emails: List[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.status.strip().lower() in ACTIVE_STATUSES


def parse_rows(values: List[List[Any]]) -> List[RosterRow]:
    """Header-driven (case-insensitive), so a moved column does not break it. Raises if the columns we need are missing."""
    if not values:
        return []
    header = [str(h).strip().lower() for h in values[0]]

    def col(*names: str) -> int:
        for n in names:
            if n in header:
                return header.index(n)
        return -1

    c_name, c_status, c_agent = col("name"), col("status"), col("agent")
    c_emails = [i for i, h in enumerate(header) if "email" in h]
    if c_name < 0 or c_status < 0 or not c_emails:
        raise ValueError("Roster sheet is missing a Name, STATUS or Email column; header is: " + ", ".join(header))
    rows = []
    for r in values[1:]:
        def cell(i: int) -> str:
            return str(r[i]).strip() if 0 <= i < len(r) and r[i] is not None else ""
        name = cell(c_name)
        if not name:
            continue
        emails: List[str] = []
        for i in c_emails:
            for m in _EMAIL.findall(cell(i)):
                e = norm_email(m)
                if e not in emails:
                    emails.append(e)
        rows.append(RosterRow(name=name, status=cell(c_status), agent=cell(c_agent), emails=emails))
    return rows


def fetch_roster(sheet_id: Optional[str] = None, key_path: Optional[str] = None, tab: str = "roster", session=None) -> List[RosterRow]:
    """Read the roster tab live. `session` can be injected for tests."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sheet_id = (sheet_id or os.getenv("STUDENT_ROSTER_SHEET_ID", "")).strip()
    if not sheet_id:
        raise RuntimeError("STUDENT_ROSTER_SHEET_ID is not set.")
    if session is None:
        key_path = key_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY_PATH", "config/service-account-key.json")
        if not os.path.isabs(key_path):
            key_path = os.path.join(root, key_path)
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        session = AuthorizedSession(service_account.Credentials.from_service_account_file(key_path, scopes=[SCOPE]))
    resp = session.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{tab}", timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Roster sheet could not be read (HTTP {resp.status_code}). Is it shared with the service account as Viewer?")
    return parse_rows(resp.json().get("values", []))


@dataclass
class Match:
    student_id: int
    student_name: str
    how: str                       # email | name | none
    row: Optional[RosterRow] = None


def match_student(student: Dict[str, Any], roster: Iterable[RosterRow]) -> Match:
    """
    email: one of the student's known emails is on a roster row (strongest).
    name:  same full name, or the words of one name all appear in the other (at least two shared words, or one shared word when one
           side is a single word such as 'Betty').
    none:  not on the roster.
    """
    roster = list(roster)
    mine = {norm_email(student.get("personal_email")), norm_email(student.get("assigned_gmail"))} - {""}
    sid, sname = student["id"], student.get("full_name") or student.get("username") or ""
    for row in roster:
        if mine & set(row.emails):
            return Match(sid, sname, "email", row)
    want = norm_name(sname)
    wt = name_tokens(sname)
    for row in roster:
        if want and norm_name(row.name) == want:
            return Match(sid, sname, "name", row)
    for row in roster:
        rt = name_tokens(row.name)
        if wt and rt and (wt <= rt or rt <= wt) and len(wt & rt) >= (2 if min(len(wt), len(rt)) > 1 else 1):
            return Match(sid, sname, "name", row)
    return Match(sid, sname, "none")


def compare(students: List[Dict[str, Any]], roster: List[RosterRow]) -> Dict[str, Any]:
    """Pure comparison; nothing is written anywhere."""
    matches = [match_student(s, roster) for s in students]
    used = {id(m.row) for m in matches if m.row is not None}
    known_emails = {norm_email(s.get(k)) for s in students for k in ("personal_email", "assigned_gmail")} - {""}
    return {
        "by_email": [m for m in matches if m.how == "email"],
        "by_name_only": [m for m in matches if m.how == "name"],       # same person, but the roster holds a different email
        "not_on_roster": [m for m in matches if m.how == "none"],
        "roster_without_student": [r for r in roster if id(r) not in used and r.active],
        "roster_emails_unknown_to_us": sorted({e for r in roster if r.active for e in r.emails} - known_emails),
    }


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return (local[:2] + "***@" + domain) if domain else "***"


# ── Live use inside the app: cached, and it never blocks mail processing or the review screen ────────────────────────────
logger = logging.getLogger(__name__)
MIN_ROSTER_ROWS = 5                  # a blank or broken sheet must never make everyone look "not listed"
_CACHE: Dict[str, Any] = {"at": 0.0, "rows": None}


def cached_roster(ttl_minutes: float = 30, fetch=None, clock=time.time) -> Optional[List[RosterRow]]:
    """The roster, re-read at most every `ttl_minutes`. None when it cannot be trusted (not set, unreadable, or nearly empty)."""
    if _CACHE["rows"] is not None and clock() - _CACHE["at"] < ttl_minutes * 60:
        return _CACHE["rows"]
    if fetch is None and not os.getenv("STUDENT_ROSTER_SHEET_ID", "").strip():
        return _CACHE["rows"]
    try:
        rows = (fetch or fetch_roster)()
    except Exception as exc:                           # sheet down, key missing, header renamed: carry on without it
        logger.warning(f"Student roster could not be read: {exc}")
        return _CACHE["rows"]                          # the last good copy, else None
    if len(rows) < MIN_ROSTER_ROWS:
        logger.warning(f"Student roster has only {len(rows)} rows; ignoring it")
        return _CACHE["rows"]
    _CACHE.update(at=clock(), rows=rows)
    return rows


def standing(student: Dict[str, Any], roster: Optional[List[RosterRow]]) -> str:
    """listed (an email matches) | name_only (a person must look) | unlisted | unknown (no usable roster)."""
    if not roster:
        return "unknown"
    return {"email": "listed", "name": "name_only", "none": "unlisted"}[match_student(student, roster).how]


def roster_emails_for(student: Dict[str, Any], roster: Optional[List[RosterRow]]) -> List[str]:
    """Extra addresses to look the student up by in GHL: the roster row matched by email or by the exact full name."""
    if not roster:
        return []
    m = match_student(student, roster)
    if m.row is None or (m.how == "name" and norm_name(m.row.name) != norm_name(student.get("full_name"))):
        return []
    return list(m.row.emails)
