"""
Does this "interview" email look like a real interview invitation, or a job board / lead-generation mailer?

A deterministic CHECK for Rob to read before he approves a student notification. It never decides and never blocks:
it lists what it saw (signals for and against) and gives one of three advisory verdicts. Pure function, no I/O,
no AI, so the same email always gets the same answer and every reason can be tested.

  looks_genuine      real-looking sender and concrete interview details
  needs_check        mixed or too little to tell; Rob should read the email
  likely_job_board   generic mailer language, tracked links, or a jobs-site sender and nothing concrete
"""

import re
from typing import Any, Dict, List, Optional

VERDICTS = ("looks_genuine", "needs_check", "likely_job_board")

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com", "live.com", "msn.com", "proton.me", "protonmail.com"}
GENERIC_MAILBOXES = {"info", "noreply", "no-reply", "donotreply", "do-not-reply", "hello", "support", "notifications",
                     "notification", "team", "mail", "news", "alerts", "jobs", "careers", "contact", "admin"}
JOBSITE_WORDS = ("job", "career", "hire", "hiring", "recruit", "talent", "staffing", "vacanc", "opening")
TRACKING_HOST_PREFIXES = ("dd.", "click.", "clicks.", "track.", "tracking.", "links.", "link.", "go.", "email.", "e.", "t.", "r.", "mailer.", "trk.")

# Wording typical of lead-generation mailers rather than a person arranging an interview.
GENERIC_PHRASES = (
    "confirm your availability", "confirm my interview request", "confirm it and we can continue", "still sitting open",
    "request is still open", "see other openings", "changed your mind", "you asked to be considered",
    "candidates to send forward", "hiring advisor", "employment advisor", "still available for roles",
    "roles in your area", "work near", "awaiting your confirmation", "your interview request", "unsubscribe",
    "view this email in your browser",
)
MEETING_LINK = re.compile(r"(zoom\.us|teams\.microsoft\.com|teams\.live\.com|meet\.google\.com|calendly\.com|webex\.com|gotomeeting\.com|whereby\.com)", re.I)
SPECIFIC_DATE = re.compile(
    r"\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\b[^.\n]{0,25}\b\d{1,2}(?:st|nd|rd|th)?\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}(?:st|nd|rd|th)?\b"
    r"|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.I)
SPECIFIC_TIME = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)\b", re.I)
REFERENCE_CODE = re.compile(r"\b(?:ref(?:erence)?(?:\s*id)?\s*[:#]?\s*[A-Z0-9]{5,})\b", re.I)
URL = re.compile(r"https?://([^\s/)>\"']+)([^\s)>\"']*)", re.I)
TAG = re.compile(r"<[^>]+>")
SCHEDULING_PHRASES = ("schedule an interview", "schedule a call", "interview with", "phone screen", "technical interview",
                      "hiring manager", "next steps")


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", text or "")).strip()


def _domain(address: str) -> str:
    match = re.search(r"@([A-Za-z0-9.-]+)", address or "")
    return match.group(1).lower() if match else ""


def _local(address: str) -> str:
    match = re.search(r"([A-Za-z0-9._%+-]+)@", address or "")
    return match.group(1).lower() if match else ""


def _company_tokens(company: Optional[str]) -> List[str]:
    stop = {"inc", "llc", "ltd", "corp", "corporation", "company", "co", "group", "systems", "solutions", "services", "the", "and"}
    words = re.findall(r"[a-z0-9]+", (company or "").lower())
    return [w for w in words if len(w) >= 4 and w not in stop]


def assess(subject: str, from_address: str, body: str, company: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns {"verdict", "against": [...], "for": [...], "note"}: plain-language reasons Rob can read.
    `body` may be raw HTML or text; only the text is read. A short body (a preview) is allowed: the note says so.
    """
    text = _plain(body)
    lowered = f"{subject or ''} {text}".lower()
    domain, local = _domain(from_address), _local(from_address)
    against: List[str] = []
    support: List[str] = []
    bad = good = 0
    strong = False          # a date/time, a meeting link or a named person: weak signals alone never make "looks genuine"

    # -- signs of a job board or lead-generation mailer
    tracked = []
    for host, path in URL.findall(body or ""):
        host = host.lower()
        opaque = re.search(r"[A-Za-z0-9_-]{40,}", path or "")
        if host.startswith(TRACKING_HOST_PREFIXES) or opaque:
            tracked.append(host)
    if tracked:
        against.append(f"Links go through a click-tracking address ({tracked[0]}), not straight to an employer or a meeting.")
        bad += 2
    hits = [p for p in GENERIC_PHRASES if p in lowered]
    if hits:
        shown = ", ".join(f'"{p}"' for p in hits[:3])
        against.append(f"Uses wording typical of job-board mailers: {shown}" + (f" and {len(hits) - 3} more." if len(hits) > 3 else "."))
        bad += min(len(hits), 3)
    if local in GENERIC_MAILBOXES and any(w in domain for w in JOBSITE_WORDS):
        against.append(f"Sent from a generic mailbox ({local}@) on a jobs-site domain ({domain}), not a named person.")
        bad += 2
    elif local in GENERIC_MAILBOXES and domain not in FREE_MAIL:
        against.append(f"Sent from a generic mailbox ({local}@{domain}), not a named person.")
        bad += 1
    if REFERENCE_CODE.search(f"{subject or ''} {text}"):
        against.append("Carries a reference code typical of automated mailers.")
        bad += 1

    # -- signs of a real interview arrangement
    if SPECIFIC_DATE.search(text) or SPECIFIC_TIME.search(text):
        support.append("States a specific date or time.")
        good += 2
        strong = True
    if MEETING_LINK.search(body or ""):
        support.append("Contains a meeting link (Zoom, Teams, Meet, Calendly...).")
        good += 2
        strong = True
    named_person = bool(re.fullmatch(r"[a-z]+(?:[._-][a-z]+)+|[a-z]+\d*", local)) and local not in GENERIC_MAILBOXES and "." in local
    if domain and domain not in FREE_MAIL and named_person and not any(w in domain for w in JOBSITE_WORDS):
        support.append(f"Sent by a named person at their own company domain ({local}@{domain}).")
        good += 1
        strong = True
    tokens = _company_tokens(company)
    if domain and tokens and not any(w in domain for w in JOBSITE_WORDS) and any(t in domain.replace("-", "") for t in tokens):
        support.append(f"The sender's domain matches the company name ({domain}).")
        good += 1
    sched = [p for p in SCHEDULING_PHRASES if p in lowered]
    if sched:
        support.append(f'Talks about the actual process ("{sched[0]}").')
        good += 1

    if good >= 2 and strong and bad <= 2:
        verdict = "looks_genuine"
    elif bad >= 4 and good <= 1:
        verdict = "likely_job_board"
    else:
        verdict = "needs_check"

    note = "This is a quick automatic check, not a decision. Please read the email before you approve."
    if len(text) < 700:
        note += " It only saw the start of the email."
    return {"verdict": verdict, "against": against, "for": support, "note": note}
