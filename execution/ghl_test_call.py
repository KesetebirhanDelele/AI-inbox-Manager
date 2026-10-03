"""
One-contact test of the notification channels (call, text, email). Not part of the pipeline; run by hand.

  python execution/ghl_test_call.py --email you@x.com                        # DRY RUN of the call: looks up and checks, writes nothing
  python execution/ghl_test_call.py --email you@x.com --send                 # LIVE: writes `interview_notification` (the call starts)
  python execution/ghl_test_call.py --email you@x.com --channel sms --send   # LIVE: writes the text field (a text is sent)
  python execution/ghl_test_call.py --email you@x.com --channel email --send # LIVE: writes the email subject + body fields
  python execution/ghl_test_call.py --email you@x.com --readback             # the contact's Voice AI calls and recent messages
(--phone +15551234567 works instead of --email.)

Safety: only the field(s) of the ONE chosen channel are ever written, only on the contact whose phone or email matches EXACTLY
(a phone is matched on its last 10 digits), and only after the same Do-Not-Disturb / opt-out check the app uses. `--send` turns the three live switches on
for this process only; `.env` is never changed. The value is facts only, like the real one, with a TEST reference so
it is unique and the agent can be told apart from a real notice.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ghl_client as gc
import ghl_conversations as gcv
import notify_channels as nc


def test_value(first_name: str, now: datetime) -> str:
    """Same shape as notify_channels.call_script(), with sample interview details and a unique TEST reference."""
    details = ("Interview type: Phone Screen; Company: Test Company; Position: Data Analyst; "
               "Date: 2026-10-08; Time: 2:00 PM CT; Format: video; Contact at the company: Jane Recruiter")
    return (f"Attempt: first notice. Candidate first name: {first_name or 'there'}. "
            f"Interview details: {details}. Reference: TEST-{now.strftime('%Y%m%d%H%M%S')}.")


def sms_test_text(now: datetime) -> str:
    """A text that passes the same gate as real ones (no links, 3+ words, short). Unique per run."""
    return ("Colaberry: your Data Analyst interview with Test Company is Thu Oct 8, 2 PM CT. "
            f"Reply YES to confirm you got this. (test {now.strftime('%H%M%S')})")


def email_test_parts(first_name: str, now: datetime) -> tuple:
    """Subject and body for the email fields. No links. Unique per run."""
    ref = f"TEST-{now.strftime('%Y%m%d%H%M%S')}"
    subject = f"Test: interview notification ({ref})"
    body = (f"Hi {first_name or 'there'}," + chr(10) * 2 + "This is a TEST of the Colaberry interview notification email. "
            "Your Data Analyst interview with Test Company is Thursday, October 8 at 2:00 PM CT, by video." + chr(10) * 2 +
            "No action is needed for this test.")
    return subject, body


def load_env() -> dict:
    from dotenv import dotenv_values
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in dotenv_values(os.path.join(root, ".env")).items() if v is not None}
    env.update({k: v for k, v in os.environ.items() if k.startswith(("GHL_", "NOTIFY_"))})
    return env


def run(argv=None, client_factory=gc.GhlClient, now=None, out=print) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", help="the test contact's phone in E.164, e.g. +15551234567")
    ap.add_argument("--email", help="or the test contact's exact email")
    ap.add_argument("--channel", choices=("call", "sms", "email"), default="call", help="which channel to test (default call)")
    ap.add_argument("--send", action="store_true", help="really write the field(s) (the call, text or email goes out)")
    ap.add_argument("--readback", action="store_true", help="only read the contact's Voice AI calls and recent messages")
    args = ap.parse_args(argv)
    now = now or datetime.now(timezone.utc)

    env = load_env()
    if args.send:
        env.update({"GHL_WRITE_MODE": "live", "GHL_WRITE_SHADOW_LOG_ONLY": "false", "GHL_WRITE_NOTIFY_FIELDS": "true"})
    else:
        env.update({"GHL_WRITE_MODE": "shadow"})
    cfg = gc.GhlConfig.from_env(env)
    if not cfg.can_read:
        out("STOP: GHL_API_KEY / GHL_LOCATION_ID are not set.")
        return 2
    client = client_factory(cfg)

    if bool(args.phone) == bool(args.email):
        out("STOP: give exactly one of --phone or --email.")
        return 2
    contact = client.search_contact_by_phone(args.phone) if args.phone else client.search_contact_by_email(args.email)
    if not contact:
        out("STOP: no contact matched exactly (or more than one matched). Nothing written.")
        return 2
    cid = contact.get("id")
    name = (contact.get("firstName") or "").strip()
    phone = str(contact.get("phone") or "")
    out(f"contact found: id {cid}, first name {name or '(none)'}, phone ends {phone[-4:] or '(none)'}")
    if not phone:
        out("STOP: this contact has no phone number, so there is nobody to call. Nothing written.")
        return 2

    if args.readback:
        logs = client.voice_ai_call_logs(cid, cfg.voice_agent_id or None)
        calls = [c for c in (gcv.parse_call_log(x) for x in logs) if c]
        out(f"{len(calls)} Voice AI call(s) for this contact")
        for c in calls[:5]:
            out(f"- {c.created_at} duration {c.duration}s; student spoke: {bool(c.human_words)}; "
                f"reached a person: {gcv.reached_a_person(c)}; app reads it as: {c.outcome or 'no rule match (AI reading)'}")
            out(f"  student said: {c.human_words[:200]!r}")
        if cfg.can_read_conversations:
            since = now.replace(tzinfo=None) - timedelta(days=1)
            try:
                msgs = gcv.fetch_new_messages(client, cid, since, set())
            except gc.GhlError as exc:
                msgs = []
                out(f"could not read messages: {exc}")
            out(f"{len(msgs)} message(s) in the last 24 hours (replies and our own emails)")
            for m in msgs[:8]:
                out(f"- {m.received_at} {m.channel} {m.direction}: {m.text[:100]!r}")
        else:
            out("(GHL_CONVERSATIONS_API_KEY not set: messages not read)")
        return 0

    channel = args.channel
    why = gc.block_reason(contact, channel, cfg.block_tags)
    if why:
        out(f"STOP: {why}. Nothing written.")
        return 2
    if channel == "call":
        updates = {cfg.field_call: test_value(name, now)}
    elif channel == "sms":
        text = nc.normalize_sms(sms_test_text(now))
        problem = nc.sms_content_problem(text)
        if problem:
            out(f"STOP: the test text fails the app's text gate: {problem}")
            return 2
        updates = {cfg.field_sms: text}
    else:
        subject, body = email_test_parts(name, now)
        updates = {cfg.field_email_subject: subject, cfg.field_email_body: body}
    missing = [label for label in updates if not client.field_id(label)]
    if missing:
        out(f"STOP: field(s) not found in this GHL location: {missing}")
        return 2
    out(f"{channel}: field(s) {sorted(updates)} found; DND/opt-out check passed")

    if not args.send:
        out("DRY RUN: nothing written. What would be written:")
        for label, value in updates.items():
            out(f"  {label}: {value}")
        out("Re-run with --send to do it" + (" (calls only 8 AM to 8 PM in the contact's time zone)." if channel == "call" else "."))
        return 0

    client.write_fields(cid, updates)
    out(f"WRITTEN: the {channel} workflow should start within a minute. Then run with --readback.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
