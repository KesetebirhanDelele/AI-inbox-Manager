"""
GoHighLevel (GHL / LeadConnector) client for the student notification escalation.

The pattern (see .claude/skills/ghl-integration/KIT.md): the app does not call a messaging endpoint.
It writes a custom field on the student's GHL contact, and a GHL workflow that triggers on that
field changing sends the email / text / starts the voice call. Writing the field IS the send, so:
  * a successful write means "handed to GHL", not "delivered";
  * writes are shadow-gated: live needs GHL_WRITE_MODE=live AND GHL_WRITE_SHADOW_LOG_ONLY=false AND
    GHL_WRITE_NOTIFY_FIELDS=true. Anything else logs the payload and makes no write call;
  * a contact must be checked for Do-Not-Disturb and opt-out tags before every send.

Fields (labels live in env, defaults are the labels Cora already uses in the same GHL location):
  email  -> "Support Issue Ticket #2" (subject) + "Message:" (body)   workflow "AI Agent - Send Email"
  sms    -> "Support issue Ticket #4" (the text)                      workflow "AI Agent - Send SMS"
  call   -> "interview_notification"                                  voice-agent workflow (Kes, 2026-10-02)

Never log a phone number, token or message body here.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
API_VERSION = "2021-07-28"
DEFAULT_BLOCK_TAGS = ("do not contact", "do not call", "do not call again", "not interested", "dnd", "opted out")
DND_CHANNEL_NAMES = {"call": "Call", "sms": "SMS", "email": "Email"}


class GhlError(RuntimeError):
    """A GHL call failed after all retries, or the setup is wrong."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _digits_tail(phone: Any) -> str:
    """The last 10 digits of a phone number, so +1 972 555 0100 and (972) 555-0100 compare equal."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class GhlConfig:
    base_url: str = "https://services.leadconnectorhq.com"
    api_key: str = ""
    conversations_api_key: str = ""            # second Private Integration token: conversations scopes only
    location_id: str = ""
    voice_agent_id: str = ""                   # only read call logs of this Voice AI agent (the outbound one)
    timeout_seconds: float = 30.0
    retry_max: int = 3
    write_mode: str = "shadow"
    shadow_log_only: bool = True
    write_notify_fields: bool = False
    min_interval_seconds: float = 0.2          # shared rate limit: about 5 calls a second
    field_email_subject: str = "Support Issue Ticket #2"
    field_email_body: str = "Message:"
    field_sms: str = "Support issue Ticket #4"
    field_call: str = "interview_notification"
    block_tags: tuple = DEFAULT_BLOCK_TAGS

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "GhlConfig":
        env = os.environ if env is None else env
        g = lambda k, d="": (env.get(k) or d).strip()
        tags = tuple(t.strip().lower() for t in g("NOTIFY_BLOCK_TAGS").split(",") if t.strip()) or DEFAULT_BLOCK_TAGS
        return cls(
            base_url=g("GHL_BASE_URL", cls.base_url),
            api_key=g("GHL_API_KEY"),
            conversations_api_key=g("GHL_CONVERSATIONS_API_KEY"),
            location_id=g("GHL_LOCATION_ID"),
            voice_agent_id=g("GHL_VOICE_AGENT_ID"),
            timeout_seconds=float(g("GHL_TIMEOUT_SECONDS", "30")),
            retry_max=int(g("GHL_RETRY_MAX", "3")),
            write_mode=g("GHL_WRITE_MODE", "shadow").lower(),
            shadow_log_only=_truthy(env.get("GHL_WRITE_SHADOW_LOG_ONLY"), True),
            write_notify_fields=_truthy(env.get("GHL_WRITE_NOTIFY_FIELDS"), False),
            field_email_subject=g("GHL_FIELD_NOTIFY_EMAIL_SUBJECT", cls.field_email_subject),
            field_email_body=g("GHL_FIELD_NOTIFY_EMAIL_BODY", cls.field_email_body),
            field_sms=g("GHL_FIELD_NOTIFY_SMS", cls.field_sms),
            field_call=g("GHL_FIELD_NOTIFY_CALL") or g("GHL_FIELD_INTERVIEW_NOTIFICATION", cls.field_call),
            block_tags=tags,
        )

    @property
    def can_read(self) -> bool:
        return bool(self.api_key and self.location_id)

    @property
    def can_read_conversations(self) -> bool:
        return bool(self.conversations_api_key and self.location_id)

    @property
    def is_live(self) -> bool:
        """All three switches are needed: mode, log-only off, and the notification-fields area on."""
        return self.write_mode == "live" and not self.shadow_log_only and self.write_notify_fields


def _is_disguised_timeout_401(resp: Any) -> bool:
    """GHL sometimes reports its own backend timeout as HTTP 401 'Command timed out'. That one is retried."""
    try:
        body = resp.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("statusCode") == 401 and "timed out" in str(body.get("message", "")).lower()


class GhlClient:
    """Thin, resilient GHL client. Reads are always allowed; writes are shadow-gated."""

    def __init__(self, config: Optional[GhlConfig] = None, session: Any = None,
                 sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic):
        self.config = config or GhlConfig.from_env()
        self._session = session or requests.Session()
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_call = None            # type: Optional[float]
        self._location_fields = None      # type: Optional[List[dict]]

    # -- transport ------------------------------------------------------------

    def _headers(self, token: Optional[str] = None, version: Optional[str] = None) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token or self.config.api_key}", "Content-Type": "application/json",
                "Accept": "application/json", "Version": version or API_VERSION}

    def _pace(self) -> None:
        """Shared limiter in front of every call: bursts return 429."""
        now = self._monotonic()
        if self._last_call is not None:
            wait = self.config.min_interval_seconds - (now - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._monotonic()

    def _request(self, method: str, path: str, retry_delay: float = 1.0, token: Optional[str] = None,
                 version: Optional[str] = None, **kwargs: Any) -> Any:
        if not (token or self.config.api_key) or not self.config.location_id:
            raise GhlError("GHL_API_KEY (or the conversations token) and GHL_LOCATION_ID are required")
        url = self.config.base_url.rstrip("/") + path
        for attempt in range(self.config.retry_max + 1):
            self._pace()
            try:
                resp = self._session.request(method, url, headers=self._headers(token, version),
                                             timeout=self.config.timeout_seconds, **kwargs)
            except requests.exceptions.Timeout as exc:
                if attempt < self.config.retry_max:
                    self._sleep(retry_delay * (2 ** attempt))
                    continue
                raise GhlError(f"GHL timed out after {attempt + 1} attempts: {method} {path}") from exc

            if resp.status_code in RETRYABLE_STATUS or (resp.status_code == 401 and _is_disguised_timeout_401(resp)):
                if attempt < self.config.retry_max:
                    logger.warning(f"GHL transient error {resp.status_code} on {path}, attempt {attempt + 1}")
                    self._sleep(retry_delay * (2 ** attempt))
                    continue
                raise GhlError(f"GHL failed after {attempt + 1} attempts: HTTP {resp.status_code}", resp.status_code)
            if resp.status_code >= 400:
                raise GhlError(f"GHL HTTP {resp.status_code} on {path}", resp.status_code)
            return resp.json() if resp.content else {}
        raise GhlError(f"GHL exhausted retries: {method} {path}")

    # -- reads (always safe) --------------------------------------------------

    def search_contact_by_phone(self, phone_e164: str) -> Optional[dict]:
        """
        The contact whose phone number EXACTLY matches, or None. 'Not found' is a normal result.

        GHL's search is a free-text query, so it can return near matches. Taking the first result could
        send one student's interview details to another student, so only a contact whose digits equal
        ours is accepted, and two different exact matches are refused as ambiguous.
        """
        result = self._request("GET", "/contacts/", params={"locationId": self.config.location_id, "query": phone_e164})
        contacts = result.get("contacts", []) if isinstance(result, dict) else []
        wanted = _digits_tail(phone_e164)
        exact = [c for c in contacts if wanted and _digits_tail(c.get("phone")) == wanted]
        if len(exact) > 1:
            raise GhlError(f"{len(exact)} GHL contacts share this phone number; refusing to guess which student")
        return exact[0] if exact else None

    def search_contact_by_email(self, email: str) -> Optional[dict]:
        """The contact whose email EXACTLY matches (case-insensitive), or None; two exact matches are refused."""
        result = self._request("GET", "/contacts/", params={"locationId": self.config.location_id, "query": email})
        contacts = result.get("contacts", []) if isinstance(result, dict) else []
        exact = [c for c in contacts if str(c.get("email", "")).strip().lower() == email.strip().lower()]
        if len(exact) > 1:
            raise GhlError(f"{len(exact)} GHL contacts share this email; refusing to guess")
        return exact[0] if exact else None

    def get_contact(self, contact_id: str) -> dict:
        result = self._request("GET", f"/contacts/{contact_id}")
        return result.get("contact", result) if isinstance(result, dict) else {}

    def location_fields(self) -> List[dict]:
        """Every custom-field definition in the location (cached). The only place names and IDs appear together."""
        if self._location_fields is None:
            result = self._request("GET", f"/locations/{self.config.location_id}/customFields")
            self._location_fields = result.get("customFields", []) if isinstance(result, dict) else []
        return self._location_fields

    def field_id(self, label: str) -> Optional[str]:
        """Resolve a field label (or its key, with or without the 'contact.' prefix) to its UUID."""
        wanted = label.strip().lower()
        for f in self.location_fields():
            key = str(f.get("fieldKey", "")).strip().lower()
            if str(f.get("name", "")).strip().lower() == wanted or key == wanted or key.split(".", 1)[-1] == wanted:
                return f.get("id")
        return None

    # -- conversations (read-only; needs the SECOND token, the contacts token is refused with 401) ----

    def _conv(self) -> str:
        if not self.config.can_read_conversations:
            raise GhlError("GHL_CONVERSATIONS_API_KEY is required to read conversations")
        return self.config.conversations_api_key

    def conversations_for_contact(self, contact_id: str, limit: int = 5) -> List[dict]:
        """The contact's conversations, newest first."""
        result = self._request("GET", "/conversations/search", token=self._conv(),
                               params={"locationId": self.config.location_id, "contactId": contact_id, "limit": limit})
        return result.get("conversations", []) if isinstance(result, dict) else []

    def conversation_messages(self, conversation_id: str, limit: int = 50) -> List[dict]:
        """Messages in a conversation, newest first. GHL double-nests this response; both shapes are handled."""
        result = self._request("GET", f"/conversations/{conversation_id}/messages", token=self._conv(),
                               params={"limit": limit})
        outer = result.get("messages", []) if isinstance(result, dict) else []
        return outer.get("messages", []) if isinstance(outer, dict) else outer

    def voice_ai_call_logs(self, contact_id: str, agent_id: Optional[str] = None, page_size: int = 20) -> List[dict]:
        """
        This contact's Voice AI call logs, newest first. Each has duration, a speaker-labelled transcript
        ("bot:" / "human:" lines), summary and the actions the agent triggered. TRIAL (test) calls are excluded.

        Verified live 2026-10-02: works with the contacts token once it has the voice-ai-dashboard.readonly scope.
        """
        params: Dict[str, Any] = {"locationId": self.config.location_id, "contactId": contact_id, "callType": "LIVE",
                                  "pageSize": min(page_size, 50), "page": 1, "sortBy": "createdAt", "sort": "descend"}
        if agent_id:
            params["agentId"] = agent_id
        result = self._request("GET", "/voice-ai/dashboard/call-logs", params=params)
        return result.get("callLogs", []) if isinstance(result, dict) else []

    # -- writes (shadow-gated) -----------------------------------------------

    def write_fields(self, contact_id: str, updates: Dict[str, str]) -> Dict[str, Any]:
        """
        Write custom fields on a contact. THE WRITE IS THE SEND: it triggers the GHL workflow.

        Shadow (default): the payload is logged by field label only (never the values) and nothing is
        written. Live: labels are resolved to UUIDs first; an unresolved label is a setup error.
        Returns {"live": bool, "fields": [labels]}.
        """
        labels = sorted(updates)
        if not self.config.is_live:
            logger.info(f"[GHL shadow] would write fields {labels} on contact {contact_id}")
            return {"live": False, "fields": labels}
        payload = []
        for label in labels:
            fid = self.field_id(label)
            if not fid:
                raise GhlError(f"GHL custom field {label!r} was not found in this location")
            payload.append({"id": fid, "value": updates[label]})
        self._request("PUT", f"/contacts/{contact_id}", json={"customFields": payload})
        logger.info(f"GHL wrote fields {labels} on contact {contact_id}")
        return {"live": True, "fields": labels}


# -- opt-out checks -----------------------------------------------------------

def block_reason(contact: Dict[str, Any], channel: str, block_tags: tuple = DEFAULT_BLOCK_TAGS) -> Optional[str]:
    """
    Why this contact must NOT be contacted on `channel` (call | sms | email), or None if it is allowed.

    Checks everything the kit requires: the contact-level dnd flag, the per-channel dndSettings, and
    opt-out tags (which can exist with no DND set).
    """
    if contact.get("dnd") is True:
        return "contact has Do-Not-Disturb on for all channels"
    settings = contact.get("dndSettings") or {}
    entry = settings.get(DND_CHANNEL_NAMES[channel]) or {}
    if str(entry.get("status", "")).lower() == "active":
        return f"{DND_CHANNEL_NAMES[channel]} Do-Not-Disturb is active"
    tags = {str(t).strip().lower() for t in (contact.get("tags") or [])}
    hit = sorted(tags & {t.lower() for t in block_tags})
    if hit:
        return f"opt-out tag on the contact: {hit[0]}"
    return None
