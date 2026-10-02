"""
Delivery channels for the student notification escalation.

A channel takes one planned attempt and delivers it. The engine (escalation_engine.py) does not
care how: it hands over a SendContext and records the ChannelResult.

Channels (chosen per kind with NOTIFY_CHANNEL_EMAIL / _SMS / _CALL, default "dry_run"):
  dry_run  logs what WOULD be sent and delivers nothing.
  smtp     email through the existing send_notification.send_email (email only).
  ghl      writes a field on the student's GHL contact; a GHL workflow does the sending
           (execution/ghl_client.py). Shadow-gated: until GHL_WRITE_MODE=live,
           GHL_WRITE_SHADOW_LOG_ONLY=false and GHL_WRITE_NOTIFY_FIELDS=true it only logs.
             email -> "Support Issue Ticket #2" (subject) + "Message:" (body)
             sms   -> "Support issue Ticket #4"
             call  -> "interview_notification"

GHL workflows trigger when a field CHANGES, so every value written here is unique per attempt
(a step tag plus the sequence reference), otherwise a repeated reminder would send nothing.
A successful write means "handed to GHL", not delivered.
"""

import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import ghl_client

logger = logging.getLogger(__name__)

SENT = "sent"
DRY_RUN = "dry_run"
FAILED = "failed"
SKIPPED = "skipped"        # deliberately not sent (for example the contact opted out)
DEFERRED = "deferred"      # not now; retry at result.retry_at (for example the daily text budget is used)

STEP_TAGS = {"start": "", "d1_2h": "Reminder 1: ", "d1_4h": "Reminder 2: ",
             "day2": "Day 2 reminder: ", "day3": "Day 3 reminder: ", "day4": "Final reminder: "}


@dataclass
class SendContext:
    attempt: Any            # NotificationAttempt
    sequence: Any           # NotificationSequence
    draft: Any              # NotificationDraft
    event: Any              # InterviewEvent (company, role, date), may be None
    student: Any            # Student, may be None
    ack_url: str            # one-tap "I got this" link for the email
    now: datetime
    db: Any = None          # session, used by the text budget


@dataclass
class ChannelResult:
    status: str             # sent | dry_run | failed | skipped | deferred
    provider_id: Optional[str] = None
    detail: Optional[str] = None
    segments: Optional[int] = None
    retry_at: Optional[datetime] = None     # only for deferred (naive UTC)


# -- message text ---------------------------------------------------------------

def _first_name(student: Any) -> str:
    name = (getattr(student, "full_name", None) or "").strip()
    return name.split()[0] if name else "there"


def _company_phrase(event: Any) -> str:
    company = (getattr(event, "company_name", None) or "").strip()
    return f" from {company}" if company else ""


def step_tag(ctx: SendContext) -> str:
    return STEP_TAGS.get(ctx.attempt.step, "Reminder: ")


def is_reminder(ctx: SendContext) -> bool:
    return ctx.attempt.step != "start"


def _ref(ctx: SendContext) -> str:
    return f"Ref {ctx.sequence.id}"


def sms_text(ctx: SendContext) -> str:
    """Short, no link (a link would be blocked), asks for a YES reply, unique per attempt."""
    return (f"{step_tag(ctx)}Colaberry: you have a new interview request{_company_phrase(ctx.event)}. "
            f"Reply YES to confirm you got this. {_ref(ctx)}")


def call_script(ctx: SendContext) -> str:
    return (f"{step_tag(ctx)}Hello {_first_name(ctx.student)}, this is Colaberry Interview Support. You have a new "
            f"interview request{_company_phrase(ctx.event)}. Please say yes to confirm you got this message. {_ref(ctx)}")


def email_parts(ctx: SendContext) -> tuple:
    subject = f"{step_tag(ctx)}{ctx.draft.email_subject or 'New interview request'}"
    body = ctx.draft.email_body or ""
    if ctx.ack_url:
        body = f"{body}\n\nPlease confirm you got this message by opening this link:\n{ctx.ack_url}\n"
    return subject, body


# -- text pre-send gate -----------------------------------------------------------

_CURLY = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "..."}
SMS_MAX_SEGMENTS = 4
SMS_DAILY_CAP_HARD_MAX = 999        # T-Mobile ceiling on the shared number (Ali, 2026-10-02)
SMS_DAILY_CAP_DEFAULT = 150         # our share; Cora uses the rest. Set NOTIFY_SMS_DAILY_SEGMENT_CAP.


def normalize_sms(text: str) -> str:
    """Curly quotes and dashes silently push a GSM-7 text into the costlier UCS-2 encoding."""
    for bad, good in _CURLY.items():
        text = text.replace(bad, good)
    return text


def sms_segments(text: str) -> int:
    """Billing segments: 160 characters in one, 153 per part beyond that; 70/67 if any non-GSM character."""
    gsm = all(ord(ch) < 128 for ch in text)
    single, multi = (160, 153) if gsm else (70, 67)
    return 1 if len(text) <= single else math.ceil(len(text) / multi)


def sms_content_problem(text: str) -> Optional[str]:
    """Why this text must not be sent at all, or None. These are bugs, not reasons to wait."""
    stripped = text.strip()
    if len(stripped.split()) < 3:
        return "text has fewer than 3 words"
    if "{{" in stripped or "}}" in stripped or re.search(r"\b(None|null|undefined)\b", stripped):
        return "text contains template or empty-value markers"
    if re.search(r"https?://|www\.", stripped, re.I):
        return "text contains a link (not allowed in a text)"
    if sms_segments(normalize_sms(stripped)) > SMS_MAX_SEGMENTS:
        return f"text is longer than {SMS_MAX_SEGMENTS} segments"
    return None


def pacific_day_start_utc(now: datetime) -> datetime:
    """Midnight US Pacific as naive UTC. The carrier's daily budget resets then."""
    pt = ZoneInfo("America/Los_Angeles")
    local = now.replace(tzinfo=timezone.utc).astimezone(pt)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)


def next_pacific_day_start_utc(now: datetime) -> datetime:
    start = pacific_day_start_utc(now)
    return pacific_day_start_utc(start + timedelta(hours=36))      # safely inside the next Pacific day


def sms_budget_used(ctx: SendContext) -> int:
    """Segments our REAL texts have used since midnight Pacific. Cora's own texts are not visible here."""
    if ctx.db is None:
        return 0
    import models
    start = pacific_day_start_utc(ctx.now)
    rows = (ctx.db.query(models.NotificationAttempt)
            .filter(models.NotificationAttempt.channel == "sms",
                    models.NotificationAttempt.status == SENT,
                    models.NotificationAttempt.sent_at >= start).all())
    return sum(r.segments or 0 for r in rows)


def sms_daily_cap(env: Optional[Dict[str, str]] = None) -> int:
    env = os.environ if env is None else env
    try:
        cap = int(env.get("NOTIFY_SMS_DAILY_SEGMENT_CAP") or SMS_DAILY_CAP_DEFAULT)
    except ValueError:
        cap = SMS_DAILY_CAP_DEFAULT
    return max(0, min(cap, SMS_DAILY_CAP_HARD_MAX))


# -- channels ---------------------------------------------------------------------

class DryRunChannel:
    """Logs what would be sent. Delivers nothing, and is recorded as dry_run, never as sent."""

    def __init__(self, name: str):
        self.name = name

    def send(self, ctx: SendContext) -> ChannelResult:
        if self.name == "sms":
            text = sms_text(ctx)
            logger.info(f"[dry_run] SMS step={ctx.attempt.step}: {text}")
            return ChannelResult(DRY_RUN, detail="dry run, nothing delivered", segments=sms_segments(normalize_sms(text)))
        if self.name == "call":
            logger.info(f"[dry_run] CALL step={ctx.attempt.step}: {call_script(ctx)}")
        else:
            subject, _ = email_parts(ctx)
            logger.info(f"[dry_run] EMAIL step={ctx.attempt.step}: {subject}")
        return ChannelResult(DRY_RUN, detail="dry run, nothing delivered")


class SmtpEmailChannel:
    """Email through the existing SMTP sender. Fails if the draft has no recipient."""
    name = "email"

    def __init__(self, send_fn=None):
        self._send_fn = send_fn

    def send(self, ctx: SendContext) -> ChannelResult:
        recipient = (ctx.draft.recipient_email or "").strip()
        if not recipient:
            return ChannelResult(FAILED, detail="draft has no recipient email")
        send = self._send_fn
        if send is None:
            from send_notification import send_email
            send = send_email
        subject, body = email_parts(ctx)
        result = send(recipient_email=recipient, subject=subject, body=body)
        if result.get("status") == "sent":
            return ChannelResult(SENT, provider_id=result.get("message_id") or None)
        return ChannelResult(FAILED, detail=str(result.get("error") or result.get("status")))


def to_e164(phone: Optional[str]) -> Optional[str]:
    """+1XXXXXXXXXX for a 10- or 11-digit North American number, else None."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


class GhlChannel:
    """
    Hands one attempt to GHL by writing the right field on the student's contact.

    Order of checks (nothing is written unless all pass): usable phone -> contact exists in GHL ->
    not opted out (Do-Not-Disturb, tags) -> for texts, the content and daily-budget gate -> write.
    A student with no GHL contact is a FAILED attempt, not a quiet skip: that student cannot be
    reached, which is exactly the blind spot this system exists to remove.
    """

    def __init__(self, kind: str, client: "ghl_client.GhlClient", env: Optional[Dict[str, str]] = None):
        if kind not in ("email", "sms", "call"):
            raise ValueError(kind)
        self.name, self.client, self._env = kind, client, env

    def _updates(self, ctx: SendContext) -> Dict[str, str]:
        cfg = self.client.config
        if self.name == "email":
            subject, body = email_parts(ctx)
            return {cfg.field_email_subject: f"{subject} ({_ref(ctx)})", cfg.field_email_body: body}
        if self.name == "sms":
            return {cfg.field_sms: normalize_sms(sms_text(ctx))}
        return {cfg.field_call: call_script(ctx)}

    def send(self, ctx: SendContext) -> ChannelResult:
        cfg = self.client.config
        phone = to_e164(getattr(ctx.student, "phone_number", None))
        if phone is None:
            return ChannelResult(FAILED, detail="student has no usable phone number to find the GHL contact")

        updates = self._updates(ctx)
        segments = None
        if self.name == "sms":
            text = updates[cfg.field_sms]
            problem = sms_content_problem(text)
            if problem:
                return ChannelResult(FAILED, detail=f"text blocked: {problem}")
            segments = sms_segments(text)

        if not cfg.can_read:
            if cfg.is_live:
                return ChannelResult(FAILED, detail="GHL_API_KEY / GHL_LOCATION_ID missing while live")
            logger.info(f"[GHL shadow, no credentials] {self.name} step={ctx.attempt.step} would write {sorted(updates)}")
            return ChannelResult(DRY_RUN, detail="GHL shadow (no credentials): would write " + ", ".join(sorted(updates)),
                                 segments=segments)

        try:
            contact = self.client.search_contact_by_phone(phone)
        except ghl_client.GhlError as exc:
            return ChannelResult(FAILED, detail=f"GHL contact lookup failed: {exc}")
        if not contact:
            return ChannelResult(FAILED, detail="no GHL contact found for this student's phone number")

        channel_key = {"email": "email", "sms": "sms", "call": "call"}[self.name]
        reason = ghl_client.block_reason(contact, channel_key, cfg.block_tags)
        if reason:
            return ChannelResult(SKIPPED, detail=f"not contacted: {reason}")

        if self.name == "sms" and cfg.is_live:
            cap = sms_daily_cap(self._env)
            if sms_budget_used(ctx) + segments > cap:
                return ChannelResult(DEFERRED, detail=f"daily text budget of {cap} segments used; retry tomorrow",
                                     retry_at=next_pacific_day_start_utc(ctx.now) + timedelta(hours=8, minutes=5))

        try:
            written = self.client.write_fields(contact["id"], updates)
        except ghl_client.GhlError as exc:
            return ChannelResult(FAILED, detail=f"GHL write failed: {exc}")
        if written["live"]:
            return ChannelResult(SENT, provider_id=str(contact["id"]), segments=segments,
                                 detail="handed to GHL (not yet confirmed delivered)")
        return ChannelResult(DRY_RUN, detail="GHL shadow: would write " + ", ".join(written["fields"]), segments=segments)


def channels_from_env(env: Optional[Dict[str, str]] = None, ghl: Optional["ghl_client.GhlClient"] = None) -> Dict[str, Any]:
    """Pick a channel per kind from NOTIFY_CHANNEL_<KIND>. An unknown or misconfigured choice fails loudly."""
    env = os.environ if env is None else env
    chosen: Dict[str, Any] = {}
    shared: Dict[str, Any] = {}
    for kind in ("email", "sms", "call"):
        setting = (env.get(f"NOTIFY_CHANNEL_{kind.upper()}") or "dry_run").strip().lower()
        if setting == "dry_run":
            chosen[kind] = DryRunChannel(kind)
        elif setting == "smtp" and kind == "email":
            chosen[kind] = SmtpEmailChannel()
        elif setting == "ghl":
            if "client" not in shared:
                shared["client"] = ghl or ghl_client.GhlClient(ghl_client.GhlConfig.from_env(env))
            cfg = shared["client"].config
            if cfg.is_live and not cfg.can_read:
                raise ValueError("NOTIFY_CHANNEL is ghl and GHL writes are live, but GHL_API_KEY / GHL_LOCATION_ID are not set")
            chosen[kind] = GhlChannel(kind, shared["client"], env)
        else:
            options = "dry_run, ghl" + (", smtp" if kind == "email" else "")
            raise ValueError(f"NOTIFY_CHANNEL_{kind.upper()}={setting!r} is not available. Options: {options}.")
    return chosen
