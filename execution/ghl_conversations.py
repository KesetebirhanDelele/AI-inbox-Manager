"""
Reading what the student actually did, from the candidate's GHL Conversations.

All communication runs through GHL, so replies are READ from GHL (polled) rather than pushed to us:
  * a text reply  -> an inbound TYPE_SMS message
  * an email reply -> an inbound TYPE_EMAIL message (GHL also logs OUR outbound emails and unsubscribe
    boilerplate as inbound, so those echoes are filtered out)
  * a call         -> a TYPE_CALL message, with GHL's own transcript as sentence entries

The AI must judge only the STUDENT's words. GHL's transcript gives sentences per media channel but does
not say which channel is the student, so the student's channel has to be configured
(GHL_CALL_STUDENT_MEDIA_CHANNEL). Until it is, a call transcript is never analysed and never stops a
sequence: Rob is told the call happened instead.

Pure parsing lives here (easy to test); the polling loop is in escalation_engine.py.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

_TYPES = {"sms": "sms", "email": "email", "call": "call"}


@dataclass
class ConversationMessage:
    id: str
    channel: str                   # sms | email | call
    direction: str                 # inbound | outbound
    text: str
    received_at: Optional[datetime]   # naive UTC
    status: str = ""               # calls: meta.call.status ("completed" = connected); texts: delivered, ...
    subject: str = ""
    duration: Optional[int] = None  # calls only: meta.call.duration in seconds


def parse_time(value: Any) -> Optional[datetime]:
    """Naive UTC from an ISO 8601 string (with Z or an offset) or an epoch in seconds or milliseconds."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 1e11 else value
            return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, OverflowError, OSError):
        return None


def channel_of(message_type: Any) -> Optional[str]:
    """TYPE_SMS / SMS / Email / TYPE_CALL ... -> sms | email | call. Anything else (notes, activity) is None."""
    key = str(message_type or "").upper().replace("TYPE_", "").strip().lower()
    return _TYPES.get(key)


def normalize(raw: Dict[str, Any]) -> Optional[ConversationMessage]:
    channel = channel_of(raw.get("messageType") or raw.get("type"))
    if channel is None or not raw.get("id"):
        return None
    meta = raw.get("meta") or {}
    subject = str(raw.get("subject") or (meta.get("email") or {}).get("subject") or "")
    status, duration = str(raw.get("status") or "").lower(), None
    if channel == "call":
        call = meta.get("call") or {}                       # confirmed on Cora's account: status and duration live here
        status = str(call.get("status") or status).lower()
        try:
            duration = int(call["duration"]) if call.get("duration") is not None else None
        except (TypeError, ValueError):
            duration = None
    return ConversationMessage(
        id=str(raw["id"]), channel=channel, direction=str(raw.get("direction") or "").lower(),
        text=str(raw.get("body") or raw.get("message") or "").strip(),
        received_at=parse_time(raw.get("dateAdded") or raw.get("dateUpdated")),
        status=status, subject=subject, duration=duration)


DEFAULT_MIN_CALL_SECONDS = 10


def is_connected_call(message: ConversationMessage, min_seconds: int = DEFAULT_MIN_CALL_SECONDS) -> bool:
    """
    A call that actually reached a person: status "completed" AND a duration of at least `min_seconds`.

    A positive test on purpose (Cora's own rule is "completed and 20 s or more"): any other status, a missing
    duration, or a very short call is NOT connected, so an unfamiliar status word can never be mistaken for a
    real conversation. Our confirmation call can be short ("yes, got it"), so the default is 10 s, not Cora's 20 s.
    """
    return message.status == "completed" and bool(message.duration) and message.duration >= min_seconds


def is_echo(message: ConversationMessage, markers: Iterable[str]) -> bool:
    """
    True for an inbound email that is really OUR own message logged back: it contains the confirmation
    link or our subject. Texts are never echoes. `markers` is a list of strings unique to our sends.
    """
    if message.channel != "email":
        return False
    haystack = f"{message.subject}\n{message.text}".lower()
    return any(m and m.lower() in haystack for m in markers)


def student_words(sentences: Optional[List[Dict[str, Any]]], student_media_channel: Optional[str]) -> Optional[str]:
    """
    The student's side of a call transcript, in order, or None if it cannot be isolated.

    None (not "") means "we cannot tell who is who": the caller must not analyse or act on it.
    """
    if sentences is None or not student_media_channel:
        return None
    mine = [s for s in sentences if str(s.get("mediaChannel")) == str(student_media_channel)]
    mine.sort(key=lambda s: (s.get("sentenceIndex") is None, s.get("sentenceIndex"), s.get("startTime") or 0))
    return " ".join(str(s.get("transcript", "")).strip() for s in mine if s.get("transcript")).strip()


def fetch_new_messages(client: Any, contact_id: str, since: datetime, seen_ids: Set[str],
                       markers: Iterable[str] = ()) -> List[ConversationMessage]:
    """
    Messages on this contact since `since` that we have not processed: inbound texts and emails (echoes
    removed) and call messages. Oldest first. Raises GhlError on a failed read (the caller decides).
    """
    markers = list(markers)
    found: List[ConversationMessage] = []
    for conversation in client.conversations_for_contact(contact_id):
        for raw in client.conversation_messages(conversation["id"]):
            m = normalize(raw)
            if m is None or m.id in seen_ids or m.received_at is None or m.received_at < since - timedelta(seconds=1):
                continue
            if m.channel in ("sms", "email") and m.direction != "inbound":
                continue                                    # our own outbound messages
            if is_echo(m, markers):
                continue
            found.append(m)
    found.sort(key=lambda m: m.received_at)
    return found
