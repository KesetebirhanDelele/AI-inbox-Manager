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

STEP_TAGS = {"start": "", "d1_2h": "Reminder 1: ", "d1_4h": "Reminder 2: ", "final": "Interview soon: ",
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


UNREACHABLE = "UNREACHABLE: "     # prefix on a failed attempt's detail when only a human can fix it (tells the approver once)


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


def _ref_value(ctx: SendContext) -> str:
    return str(ctx.sequence.id)


def sms_text(ctx: SendContext) -> str:
    """The text: begins exactly "[Interview Notification]", 320 characters or fewer, no job title, no link (see notification_messages)."""
    import notification_messages as nm
    return nm.sms(nm.facts_from_event(ctx.event, ctx.student), step_tag(ctx), _ref_value(ctx))


def interview_facts(event: Any) -> list:
    """The interview details the voice agent may pass to the candidate. Only facts we actually have."""
    def pick(*names):
        for n in names:
            v = getattr(event, n, None)
            if v not in (None, ""):
                return str(v).strip()
        return ""

    facts = []
    kind = pick("sub_type").replace("_", " ")
    if kind:
        facts.append(f"Interview type: {kind}")
    for label, value in (("Company", pick("company_name")), ("Position", pick("position_title")),
                         ("Date", pick("interview_date")),
                         ("Time", " ".join(x for x in (pick("interview_time"), pick("interview_timezone")) if x)),
                         ("Format", pick("interview_format")), ("Contact at the company", pick("contact_name")),
                         ("Number of interviewers", pick("num_interviewers"))):
        if value:
            facts.append(f"{label}: {value}")
    if facts and not pick("interview_date"):
        facts.append("Date and time: not confirmed yet, the company will schedule it")
    return facts


ATTEMPT_LABELS = {"start": "first notice", "d1_2h": "reminder 1", "d1_4h": "reminder 2", "final": "final reminder shortly before the interview",
                  "day2": "day 2 reminder", "day3": "day 3 reminder", "day4": "final reminder"}


def call_script(ctx: SendContext) -> str:
    """
    The value written to `interview_notification`: FACTS ONLY. The agent's instructions (greet, verify, deliver,
    ask for a yes) live in the Voice AI agent's prompt (docs/voice-agent-outbound-interview-prompt.md), so the
    value never repeats or contradicts them. It tells the agent which attempt this is, so a reminder can say it is
    following up. Unique per attempt (attempt label + reference) because GHL only re-triggers on a CHANGED value.
    """
    details = "; ".join(interview_facts(ctx.event)) or "a new interview request (no details available)"
    label = ATTEMPT_LABELS.get(ctx.attempt.step, "reminder")
    return (f"Attempt: {label}. Candidate first name: {_first_name(ctx.student)}. "
            f"Interview details: {details}. Reference: {ctx.sequence.id}.")


def email_parts(ctx: SendContext) -> tuple:
    """Subject and body. A draft that already starts with "[Interview Notification]" (made by the new builder, or edited by the approver
    from it) is sent as it is; an older template draft is replaced by the audit-safe notification built from the interview facts."""
    import content_audit as audit
    import notification_messages as nm
    body = ctx.draft.email_body or ""
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    if first == audit.REQUIRED_START:
        subject = ctx.draft.email_subject or "Your interview notification"
    else:
        facts = nm.facts_from_event(ctx.event, ctx.student)
        subject, body = nm.email_subject(facts), nm.email_body(facts)
    subject = f"{step_tag(ctx)}{subject}"
    return subject, body            # no confirmation link: the student replies YES (the one-tap link was removed 2026-10-12)


def audit_problem(kind: str, ctx: SendContext) -> Optional[str]:
    """The content audit's verdict on what this attempt would send (texts and emails only; calls are not scanned), or None."""
    import content_audit as audit
    if kind == "sms":
        return audit.sms_problem(normalize_sms(sms_text(ctx)))
    if kind == "email":
        return audit.email_problem(email_parts(ctx)[1])
    return None


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
        blocked = audit_problem(self.name, ctx)
        if blocked:
            return ChannelResult(FAILED, detail=f"blocked by the content audit: {blocked}")
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
        blocked = audit_problem("email", ctx)
        if blocked:
            return ChannelResult(FAILED, detail=f"blocked by the content audit: {blocked}")
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


def opted_out_in_app(db, phone_e164: str, channel: str) -> bool:
    """True if the student asked us to stop on this channel (notification_opt_outs). No session = not checked."""
    if db is None:
        return False
    import models
    tail = re.sub(r"\D", "", phone_e164 or "")[-10:]
    return db.query(models.NotificationOptOut).filter_by(phone_tail=tail, channel=channel).first() is not None


def _first_names_agree(student_name: Optional[str], ghl_first_name: Optional[str]) -> bool:
    """True when either name is missing, or one first name starts with the other (Rob / Robert)."""
    a = (student_name or "").strip().split()
    b = (ghl_first_name or "").strip().split()
    if not a or not b:
        return True
    x, y = a[0].lower(), b[0].lower()
    return x.startswith(y) or y.startswith(x)


def possible_ghl_matches(client: Any, student: Any, limit: int = 3) -> str:
    """Near matches by NAME in GHL, for the message that tells a person the student could not be found (name, email, last 4 of the phone).
    Every name word is searched, then the contacts are ranked by how much of the student's name and email they share, so the person
    who changed their email comes first and a stranger who only shares a first name does not. Read-only and best effort."""
    search = getattr(client, "search_contacts_by_name", None)
    if search is None:
        return ""
    words = [w for w in re.split(r"\s+", (getattr(student, "full_name", None) or "").strip()) if len(w) >= 4]
    local = ((getattr(student, "personal_email", None) or getattr(student, "assigned_gmail", None) or "").split("@")[0]).lower()
    found: Dict[str, Any] = {}
    for word in words:
        try:
            for c in search(word):
                found.setdefault(str(c.get("id")), c)
        except Exception:
            break

    def score(c: Any) -> int:
        text = " ".join(str(c.get(k) or "") for k in ("firstName", "lastName", "contactName", "email")).lower()
        n = sum(1 for w in words if w[:5].lower() in text)
        their = str(c.get("email") or "").split("@")[0].lower()
        if len(their) >= 6 and local and (their in local or local in their):
            n += 2                                           # one address contains the other: the same person with a shortened or lengthened email
        return n

    ranked = sorted(found.values(), key=score, reverse=True)
    out = []
    for c in ranked[:limit]:
        name = " ".join(x for x in ((c.get("firstName") or ""), (c.get("lastName") or "")) if x) or (c.get("contactName") or "")
        out.append(f"{name or 'no name'} <{c.get('email') or 'no email'}>, phone ending {str(c.get('phone') or '')[-4:] or 'none'}")
    return "; ".join(out)


def find_ghl_contact(client: "ghl_client.GhlClient", student: Any) -> tuple:
    """
    The student's GHL contact, as (contact, how, problem). Exactly one of contact / problem is set.

    The interview notice identifies a student by email, so email is the normal way in: the student's personal email,
    then their assigned Gmail, then (fallback) their phone number. Every identifier we hold is tried and they must all
    agree: two different contacts is ambiguous and is refused, never guessed. A contact found ONLY by phone must also
    have a first name that agrees with the student's, so details cannot reach someone who shares or inherited a number.
    A problem means a human has to fix the data (a student may have changed their email and GHL needs updating).
    """
    emails = []
    for attr in ("personal_email", "assigned_gmail"):
        value = (getattr(student, attr, None) or "").strip()
        if value and value.lower() not in emails:
            emails.append(value.lower())
    try:                                  # the roster's personal / application emails are tried too; all identifiers must agree (below)
        import student_roster
        sd = {"id": getattr(student, "id", None), "full_name": getattr(student, "full_name", None),
              "personal_email": getattr(student, "personal_email", None), "assigned_gmail": getattr(student, "assigned_gmail", None)}
        for value in student_roster.roster_emails_for(sd, student_roster.cached_roster()):
            if value and value.lower() not in emails:
                emails.append(value.lower())
    except Exception:
        pass
    phone = to_e164(getattr(student, "phone_number", None))
    if not emails and phone is None:
        return None, "", "no email or phone number on file for this student"

    found: Dict[str, Any] = {}      # contact id -> contact
    how: Dict[str, list] = {}       # contact id -> [how it was found]
    for email in emails:
        contact = client.search_contact_by_email(email)
        if contact:
            found[contact["id"]] = contact
            how.setdefault(contact["id"], []).append("email")
    if phone is not None:
        contact = client.search_contact_by_phone(phone)
        if contact:
            found[contact["id"]] = contact
            how.setdefault(contact["id"], []).append("phone")

    if not found:
        tried = " and ".join(x for x in ("email" if emails else "", "phone" if phone else "") if x)
        near = possible_ghl_matches(client, student)
        hint = f" Possible matches in GHL by name: {near}." if near else ""
        return None, "", (f"no GHL contact matches this student's {tried}; the student may have changed their "
                          f"email or phone, so GHL or the student record needs updating.{hint}")
    if len(found) > 1:
        return None, "", "this student's email and phone point to different GHL contacts; refusing to guess which"
    contact_id, contact = next(iter(found.items()))
    if how[contact_id] == ["phone"] and not _first_names_agree(getattr(student, "full_name", None), contact.get("firstName")):
        return None, "", ("the GHL contact found by phone has a different first name than the student; "
                          "please check it is the right person")
    return contact, "+".join(how[contact_id]), ""


class GhlChannel:
    """
    Hands one attempt to GHL by writing the right field on the student's contact.

    Order of checks (nothing is written unless all pass): contact found in GHL by email, then phone (find_ghl_contact) ->
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
        if ctx.db is not None:                      # the Settings switch is read on EVERY send, so turning it off stops the next one
            import dataclasses
            import roles
            self.client.config = dataclasses.replace(self.client.config, live_switch=roles.live_delivery_on(ctx.db))
        cfg = self.client.config
        phone = to_e164(getattr(ctx.student, "phone_number", None))
        if phone is not None and opted_out_in_app(ctx.db, phone, self.name):
            return ChannelResult(SKIPPED, detail=f"not contacted: the student asked us to stop ({self.name})")

        blocked = audit_problem(self.name, ctx)
        if blocked:
            return ChannelResult(FAILED, detail=f"blocked by the content audit: {blocked}")
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
            contact, _how, problem = find_ghl_contact(self.client, ctx.student)
        except ghl_client.GhlError as exc:
            return ChannelResult(FAILED, detail=f"GHL contact lookup failed: {exc}")
        if problem:
            return ChannelResult(FAILED, detail=UNREACHABLE + problem)
        channel_key = {"email": "email", "sms": "sms", "call": "call"}[self.name]
        reason = ghl_client.block_reason(contact, channel_key, cfg.block_tags)
        if reason:
            return ChannelResult(SKIPPED, detail=f"not contacted: {reason}")
        contact_phone = to_e164(contact.get("phone"))
        if contact_phone is not None and opted_out_in_app(ctx.db, contact_phone, self.name):
            return ChannelResult(SKIPPED, detail=f"not contacted: the student asked us to stop ({self.name})")
        if self.name in ("call", "sms") and contact_phone is None:
            return ChannelResult(FAILED, detail=UNREACHABLE + "the student's GHL contact has no usable phone number for a call or text")
        if self.name == "email" and not str(contact.get("email") or "").strip():
            return ChannelResult(FAILED, detail=UNREACHABLE + "the student's GHL contact has no email address")

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
