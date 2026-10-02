"""
One-contact test of the voice call path. Not part of the pipeline; run by hand.

  python execution/ghl_test_call.py --phone +15551234567   (or --email you@x.com)  # DRY RUN: looks up and checks, writes nothing
  python execution/ghl_test_call.py --phone +15551234567 --send          # LIVE: writes `interview_notification` (the call starts)
  python execution/ghl_test_call.py --phone +15551234567 --readback      # read the contact's Voice AI call logs

Safety: only ONE field is ever written (the call field), only on the contact whose phone matches EXACTLY (last 10
digits), and only after the same Do-Not-Disturb / opt-out check the app uses. `--send` turns the three live switches on
for this process only; `.env` is never changed. The value is facts only, like the real one, with a TEST reference so
it is unique and the agent can be told apart from a real notice.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ghl_client as gc
import ghl_conversations as gcv


def test_value(first_name: str, now: datetime) -> str:
    """Same shape as notify_channels.call_script(), with sample interview details and a unique TEST reference."""
    details = ("Interview type: Phone Screen; Company: Test Company; Position: Data Analyst; "
               "Date: 2026-10-08; Time: 2:00 PM CT; Format: video; Contact at the company: Jane Recruiter")
    return (f"Attempt: first notice. Candidate first name: {first_name or 'there'}. "
            f"Interview details: {details}. Reference: TEST-{now.strftime('%Y%m%d%H%M%S')}.")


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
    ap.add_argument("--send", action="store_true", help="really write the field (starts the call)")
    ap.add_argument("--readback", action="store_true", help="only read the contact's Voice AI call logs")
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
                f"reached a person: {gcv.reached_a_person(c)}")
            out(f"  student said: {c.human_words[:200]!r}")
        return 0

    why = gc.block_reason(contact, "call", cfg.block_tags)
    if why:
        out(f"STOP: {why}. Nothing written.")
        return 2
    if not client.field_id(cfg.field_call):
        out(f"STOP: the field {cfg.field_call!r} does not exist in this GHL location.")
        return 2
    out(f"field {cfg.field_call!r} found; DND/opt-out check passed")

    value = test_value(name, now)
    if not args.send:
        out("DRY RUN: nothing written. The value that would be written:")
        out(value)
        out("Re-run with --send between 8 AM and 8 PM in the contact's time zone to place the call.")
        return 0

    client.write_fields(cid, {cfg.field_call: value})
    out("WRITTEN: the call workflow should start within a minute. Check your phone, then run with --readback.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
