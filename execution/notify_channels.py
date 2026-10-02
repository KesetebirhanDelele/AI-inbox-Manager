"""
Delivery channels for the student notification escalation.

A channel takes one planned attempt and delivers it. The engine (escalation_engine.py) does not
care how: it hands over a SendContext and records the ChannelResult.

What exists today (2026-10-02):
  dry_run  logs what WOULD be sent and delivers nothing. This is the default for every channel.
  smtp     email through the existing send_notification.send_email.
  ghl / synthflow  NOT built yet. They need GHL credentials and a dedicated Synthflow agent, and
           selecting them fails loudly instead of silently doing nothing. How Cora does it:
             email  -> write GHL custom fields "Support Issue Ticket #2" (subject) + "Message" (body)
             SMS    -> write GHL custom field "Support issue Ticket #4" (the text)
             call   -> NOT a GHL field: POST to a Synthflow "Make Call" workflow webhook
           (see directives/student-notification-escalation.md).

Channels are chosen per channel by environment variable: NOTIFY_CHANNEL_EMAIL, NOTIFY_CHANNEL_SMS,
NOTIFY_CHANNEL_CALL, each "dry_run" (default) or a real adapter name.
"""

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SENT = "sent"
DRY_RUN = "dry_run"
FAILED = "failed"


@dataclass
class SendContext:
    attempt: Any            # NotificationAttempt
    sequence: Any           # NotificationSequence
    draft: Any              # NotificationDraft
    event: Any              # InterviewEvent (company, role, date), may be None
    student: Any            # Student, may be None
    ack_url: str            # one-tap "I got this" link for the email
    now: datetime


@dataclass
class ChannelResult:
    status: str             # sent | dry_run | failed
    provider_id: Optional[str] = None
    detail: Optional[str] = None
    segments: Optional[int] = None


# ── message text ─────────────────────────────────────────────────────────────

def _first_name(student: Any) -> str:
    name = (getattr(student, "full_name", None) or "").strip()
    return name.split()[0] if name else "there"


def _company_phrase(event: Any) -> str:
    company = (getattr(event, "company_name", None) or "").strip()
    return f" from {company}" if company else ""


def is_reminder(ctx: SendContext) -> bool:
    return ctx.attempt.step != "start"


def sms_text(ctx: SendContext) -> str:
    """Short, no link (Cora's SMS gate blocks links), asks for a YES reply."""
    prefix = "Reminder: " if is_reminder(ctx) else ""
    return (f"{prefix}Colaberry: you have a new interview request{_company_phrase(ctx.event)}. "
            f"Reply YES to confirm you got this.")


def call_script(ctx: SendContext) -> str:
    return (f"Hello {_first_name(ctx.student)}, this is Colaberry Interview Support. You have a new "
            f"interview request{_company_phrase(ctx.event)}. Please say yes, or press 1, to confirm you got this message.")


def email_parts(ctx: SendContext) -> tuple:
    subject = ctx.draft.email_subject or "New interview request"
    body = ctx.draft.email_body or ""
    if is_reminder(ctx):
        subject = f"Reminder: {subject}"
    if ctx.ack_url:
        body = f"{body}\n\nPlease confirm you got this message by opening this link:\n{ctx.ack_url}\n"
    return subject, body


def sms_segments(text: str) -> int:
    """Billing segments: 160 characters in one, 153 per part beyond that; 70/67 if any non-GSM character."""
    gsm = all(ord(ch) < 128 for ch in text)
    single, multi = (160, 153) if gsm else (70, 67)
    return 1 if len(text) <= single else math.ceil(len(text) / multi)


# ── channels ─────────────────────────────────────────────────────────────────

class DryRunChannel:
    """Logs what would be sent. Delivers nothing, and is recorded as dry_run, never as sent."""

    def __init__(self, name: str):
        self.name = name

    def send(self, ctx: SendContext) -> ChannelResult:
        if self.name == "sms":
            text = sms_text(ctx)
            logger.info(f"[dry_run] SMS step={ctx.attempt.step}: {text}")
            return ChannelResult(DRY_RUN, detail="dry run, nothing delivered", segments=sms_segments(text))
        if self.name == "call":
            logger.info(f"[dry_run] CALL step={ctx.attempt.step}: {call_script(ctx)}")
        else:
            subject, _ = email_parts(ctx)
            logger.info(f"[dry_run] EMAIL step={ctx.attempt.step}: {subject}")
        return ChannelResult(DRY_RUN, detail="dry run, nothing delivered")


class SmtpEmailChannel:
    """Email through the existing SMTP sender. Skips with a failure if the draft has no recipient."""
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


def channels_from_env(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Pick a channel per kind from NOTIFY_CHANNEL_<KIND>. Unbuilt adapters fail loudly at startup."""
    env = os.environ if env is None else env
    chosen: Dict[str, Any] = {}
    for kind in ("email", "sms", "call"):
        setting = (env.get(f"NOTIFY_CHANNEL_{kind.upper()}") or "dry_run").strip().lower()
        if setting == "dry_run":
            chosen[kind] = DryRunChannel(kind)
        elif setting == "smtp" and kind == "email":
            chosen[kind] = SmtpEmailChannel()
        else:
            raise NotImplementedError(
                f"NOTIFY_CHANNEL_{kind.upper()}={setting!r} is not available. Built: dry_run"
                f"{', smtp' if kind == 'email' else ''}. GHL and Synthflow adapters are not built yet "
                f"(they need GHL credentials and a dedicated Synthflow agent)."
            )
    return chosen
