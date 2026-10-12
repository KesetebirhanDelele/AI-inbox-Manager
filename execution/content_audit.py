"""
The outbound-content audit, mirrored here so a message that would be flagged is never sent.

Another automated system scans the BODY of every outbound text and email (not calls, not the email subject) and flags a message
that contains any of FLAGGED_TERMS as a whole word or phrase, case-insensitive. A text must also stay free of marketing wording
(SMS_BANNED_TERMS, and any "$" amount). A notification is not marketing and Colaberry does not offer the position, so the
notification builders (notification_messages.py) never name the job title, and this module is the last check before a send.

Pure functions, no I/O.
"""
import re
from typing import List, Optional

# Flagged in the body of a text or an email, whole words / phrases, case-insensitive (list from the audit owner, 2026-10-12).
FLAGGED_TERMS = (
    "data analytics", "data analyst", "data science", "bootcamp", "boot camp", "power bi", "tableau", "sql", "excel",
    "full stack", "full-stack", "cybersecurity", "cyber security", "business intelligence", "employment rate",
    "placement rate", "job placement", "job guarantee", "guaranteed job", "hiring rate", "employment outcome",
)

# Not allowed in a text: a text is a notification channel, not marketing.
SMS_BANNED_TERMS = (
    "open house", "rsvp", "webinar", "enroll", "register", "sign up", "discount", "limited time", "free class",
    "scholarship", "tuition", "price", "pricing", "success story", "cohort", "hurry", "last chance",
)

REQUIRED_START = "[Interview Notification]"
SMS_MAX_CHARS = 320


def _pattern(term: str) -> "re.Pattern":
    # whole word or phrase; spaces and hyphens inside a phrase match either ("full stack" / "full-stack")
    parts = [re.escape(p) for p in re.split(r"[ -]+", term.strip())]
    return re.compile(r"(?<![A-Za-z0-9])" + r"[ \-]+".join(parts) + r"(?![A-Za-z0-9])", re.I)


_FLAGGED = [(t, _pattern(t)) for t in FLAGGED_TERMS]
_SMS_BANNED = [(t, _pattern(t)) for t in SMS_BANNED_TERMS]


def find_flagged(text: str) -> List[str]:
    """The audit's flagged terms that appear in `text` (whole words, case-insensitive). Empty list = clean."""
    return [term for term, rx in _FLAGGED if rx.search(text or "")]


def find_sms_banned(text: str) -> List[str]:
    """Marketing wording and money amounts that must not appear in a text."""
    found = [term for term, rx in _SMS_BANNED if rx.search(text or "")]
    if "$" in (text or ""):
        found.append("$ amount")
    return found


def contains_flagged(name: Optional[str]) -> bool:
    return bool(find_flagged(name or "")) or bool(find_sms_banned(name or ""))


_LINK = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|co|us|ly)/", re.I)


def has_link(text: str) -> bool:
    """A web address of any kind (messages carry no links)."""
    return bool(_LINK.search(text or ""))


def sms_problem(text: str) -> Optional[str]:
    """Why this text must not go out under the audit rules, or None."""
    t = text or ""
    if not t.startswith(REQUIRED_START):
        return f'text must begin with exactly "{REQUIRED_START}"'
    if len(t) > SMS_MAX_CHARS:
        return f"text is {len(t)} characters, the limit is {SMS_MAX_CHARS}"
    if has_link(t):
        return "the text contains a link (messages carry no links)"
    flagged = find_flagged(t) + find_sms_banned(t)
    if flagged:
        return "content audit: the text contains " + ", ".join(sorted(set(flagged)))
    return None


def email_problem(body: str) -> Optional[str]:
    """Why this email body must not go out under the audit rules, or None. The subject is not scanned."""
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    if not lines or lines[0].strip() != REQUIRED_START:
        return f'the first line of the email must be exactly "{REQUIRED_START}"'
    if has_link(body):
        return "the email contains a link (messages carry no links)"
    flagged = find_flagged(body)
    if flagged:
        return "content audit: the email contains " + ", ".join(sorted(set(flagged)))
    return None
