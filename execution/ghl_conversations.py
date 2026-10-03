"""
Reading what the student actually did.

All communication runs through GHL, so replies are READ from GHL (polled) rather than pushed to us:
  * a text reply   -> an inbound TYPE_SMS message in the candidate's Conversations
  * an email reply -> an inbound TYPE_EMAIL message (GHL also logs OUR outbound emails as inbound, so those
    echoes are filtered out)
  * a voice call   -> a Voice AI CALL LOG (GET /voice-ai/dashboard/call-logs). Its transcript is speaker-labelled
    ("bot:" / "human:" lines), so the student's words can be separated from the agent's. This replaces the
    Conversations transcript endpoint, which returns nothing on this account.

The AI must judge only the STUDENT's words: for calls, only the "human:" lines are ever analysed.

Pure parsing lives here (easy to test); the polling loop is in escalation_engine.py.
"""

import logging
import re
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
    status: str = ""               # texts: delivered, ...
    subject: str = ""


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
    return ConversationMessage(
        id=str(raw["id"]), channel=channel, direction=str(raw.get("direction") or "").lower(),
        text=str(raw.get("body") or raw.get("message") or "").strip(),
        received_at=parse_time(raw.get("dateAdded") or raw.get("dateUpdated")),
        status=str(raw.get("status") or "").lower(), subject=subject)


def is_echo(message: ConversationMessage, markers: Iterable[str]) -> bool:
    """
    True for an inbound email that is really OUR own message logged back: it contains the confirmation
    link or our subject. Texts are never echoes. `markers` is a list of strings unique to our sends.
    """
    if message.channel != "email":
        return False
    haystack = f"{message.subject}\n{message.text}".lower()
    return any(m and m.lower() in haystack for m in markers)


DEFAULT_MIN_CALL_SECONDS = 10
VOICE_ID_PREFIX = "voiceai:"          # keeps call-log ids apart from message ids in notification_inbound


@dataclass
class VoiceCall:
    id: str
    created_at: Optional[datetime]     # naive UTC
    duration: int                      # seconds
    human_words: str                   # ONLY the student's side of the transcript
    summary: str = ""
    actions: Optional[List[str]] = None
    outcome: str = ""                  # "confirmed" | "stop" | "" (see call_outcome)

    @property
    def record_id(self) -> str:
        return VOICE_ID_PREFIX + self.id


# The agent's confirmation question (docs/voice-agent-outbound-interview-prompt.md, step 3) must keep this phrase:
# "Can you confirm you got this information? Please just say yes."
CONFIRM_QUESTION_MARKER = "confirm you got"

_STOP_REQUEST = re.compile(
    r"\b(?:do not|don'?t|never|stop)\s+(?:ever\s+)?(?:call|calling|contact|contacting|phone)\b"
    r"|\bremove (?:me|my number)\b|\btake me off\b|\bunsubscribe\b|\bno more calls\b")
_YES_START = re.compile(r"^\W*(?:yes|yeah|yep|yup|ok|okay|sure|correct|i got it|got it|i did|i have)\b")
_YES_BUT = re.compile(r"\b(?:but|cannot|can'?t|can not|not|no|won'?t|problem|reschedule)\b")


def call_turns(transcript: Any) -> List[tuple]:
    """The transcript as [(speaker, text)] in order, where speaker is 'bot' or 'human'. Unlabelled lines continue the speaker."""
    if not isinstance(transcript, str):
        return []
    turns: List[list] = []
    for line in transcript.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith("human:"):
            speaker, stripped = "human", stripped[6:].strip()
        elif lowered.startswith("bot:"):
            speaker, stripped = "bot", stripped[4:].strip()
        else:
            speaker = turns[-1][0] if turns else None
        if speaker is None or not stripped:
            continue
        if turns and turns[-1][0] == speaker:
            turns[-1][1] += " " + stripped
        else:
            turns.append([speaker, stripped])
    return [(s, t) for s, t in turns]


def call_outcome(transcript: Any) -> str:
    """
    Deterministic reading of a call, before any AI:
      "stop"      the student said something like "don't call me again" (wins over everything).
      "confirmed" the student's answer right after the agent's confirmation question starts with a plain yes
                  and holds no "but / can't / not / no" (so "yes but I can't make it" is NOT a confirmation).
      ""          neither; the words go to the normal reply rules and the AI reading.
    """
    turns = call_turns(transcript)
    for speaker, text in turns:
        if speaker == "human" and _STOP_REQUEST.search(text.lower().replace("’", "'")):
            return "stop"
    for i, (speaker, text) in enumerate(turns):
        if speaker == "bot" and CONFIRM_QUESTION_MARKER in text.lower():
            answer = next((t for s, t in turns[i + 1:] if s == "human"), "")
            low = answer.lower().replace("’", "'")
            if _YES_START.search(low) and not _YES_BUT.search(low):
                return "confirmed"
    return ""


def human_words(transcript: Any) -> str:
    """
    The student's side of a Voice AI transcript: the lines labelled "human:" (the agent's are "bot:"), in order.
    A line with no label continues the previous speaker. Returns "" if the student said nothing.
    """
    if not isinstance(transcript, str):
        return ""
    words, speaker = [], None
    for line in transcript.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith("human:"):
            speaker, stripped = "human", stripped[6:].strip()
        elif lowered.startswith("bot:"):
            speaker, stripped = "bot", stripped[4:].strip()
        if speaker == "human" and stripped:
            words.append(stripped)
    return " ".join(words)


def parse_call_log(raw: Dict[str, Any]) -> Optional[VoiceCall]:
    if not raw.get("id"):
        return None
    try:
        duration = int(raw.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    actions = [str(a.get("actionType")) for a in (raw.get("executedCallActions") or []) if isinstance(a, dict)]
    return VoiceCall(id=str(raw["id"]), created_at=parse_time(raw.get("createdAt")), duration=duration,
                     human_words=human_words(raw.get("transcript")), summary=str(raw.get("summary") or ""),
                     actions=actions, outcome=call_outcome(raw.get("transcript")))


def reached_a_person(call: VoiceCall, min_seconds: int = DEFAULT_MIN_CALL_SECONDS) -> bool:
    """
    A positive test: the call lasted at least `min_seconds` AND the student said something. Anything else
    (no answer, hung up, voicemail with no human speech) is not a conversation and is never analysed.
    """
    return call.duration >= min_seconds and bool(call.human_words)


def fetch_new_calls(client: Any, contact_id: str, since: datetime, seen_ids: Set[str],
                    agent_id: Optional[str] = None) -> List[VoiceCall]:
    """This contact's Voice AI calls since `since` that we have not processed, oldest first."""
    found: List[VoiceCall] = []
    for raw in client.voice_ai_call_logs(contact_id, agent_id=agent_id or None):
        call = parse_call_log(raw)
        if call is None or call.record_id in seen_ids or call.created_at is None:
            continue
        if call.created_at < since - timedelta(seconds=1):
            continue
        found.append(call)
    found.sort(key=lambda c: c.created_at)
    return found


def fetch_new_messages(client: Any, contact_id: str, since: datetime, seen_ids: Set[str],
                       markers: Iterable[str] = ()) -> List[ConversationMessage]:
    """
    Messages on this contact since `since` that we have not processed: inbound texts and emails, with echoes
    of our own emails removed. Calls are NOT read here; they come from Voice AI call logs (fetch_new_calls).
    Oldest first. Raises GhlError on a failed read (the caller decides).
    """
    markers = list(markers)
    found: List[ConversationMessage] = []
    for conversation in client.conversations_for_contact(contact_id):
        for raw in client.conversation_messages(conversation["id"]):
            m = normalize(raw)
            if m is None or m.id in seen_ids or m.received_at is None or m.received_at < since - timedelta(seconds=1):
                continue
            if m.channel not in ("sms", "email") or m.direction != "inbound":
                continue                                    # calls come from call logs; skip our own outbound messages
            if is_echo(m, markers):
                continue
            found.append(m)
    found.sort(key=lambda m: m.received_at)
    return found
