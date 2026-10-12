"""
Add an ADDITIONAL email to one GHL contact, after a person has confirmed it (run by hand). Never changes the primary email.

  python execution/ghl_add_additional_email.py --contact-id <id> --email new@x.com --confirmed-by "Kes"            # DRY RUN: shows the plan, writes nothing
  python execution/ghl_add_additional_email.py --contact-id <id> --email new@x.com --confirmed-by "Kes" --apply    # LIVE: writes, then reads back

Why a person must confirm: GHL contacts are shared with other automations (Cora). The student's lookup in this app matches the primary OR
an additional email, so adding the address a student actually uses lets their notices find them without touching the primary one.
`--apply` turns the live switches on for this process only; `.env` is never changed. After the write the contact is read back and the
script fails loudly if the primary email changed or the address was not stored.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ghl_client as gc


def load_env() -> dict:
    from dotenv import dotenv_values
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in dotenv_values(os.path.join(root, ".env")).items() if v is not None}
    env.update({k: v for k, v in os.environ.items() if k.startswith(("GHL_", "NOTIFY_"))})
    return env


def run(argv=None, client_factory=gc.GhlClient, out=print) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contact-id", required=True)
    ap.add_argument("--email", required=True, help="the additional email to add")
    ap.add_argument("--confirmed-by", required=True, help="the person who confirmed this exact change")
    ap.add_argument("--apply", action="store_true", help="really write it (default: dry run)")
    args = ap.parse_args(argv)

    env = load_env()
    if args.apply:
        env.update({"GHL_WRITE_MODE": "live", "GHL_WRITE_SHADOW_LOG_ONLY": "false", "GHL_WRITE_NOTIFY_FIELDS": "true"})
    else:
        env.update({"GHL_WRITE_MODE": "shadow"})
    cfg = gc.GhlConfig.from_env(env)
    if not cfg.can_read:
        out("STOP: GHL_API_KEY / GHL_LOCATION_ID are not set.")
        return 2
    client = client_factory(cfg)
    contact = client.get_contact(args.contact_id)
    if not contact:
        out("STOP: no such contact. Nothing written.")
        return 2
    name = " ".join(x for x in ((contact.get("firstName") or ""), (contact.get("lastName") or "")) if x) or contact.get("contactName") or "(no name)"
    existing = gc.contact_emails(contact)
    out(f"contact ..{str(args.contact_id)[-5:]}: {name}; primary email: {contact.get('email') or '(none)'}; "
        f"additional: {existing[1:] if contact.get('email') else existing or '(none)'}")
    out(f"to add as an ADDITIONAL email: {args.email.strip().lower()} (confirmed by {args.confirmed_by})")
    try:
        result = client.add_additional_email(args.contact_id, args.email, args.confirmed_by)
    except gc.GhlError as exc:
        out(f"STOP: {exc}")
        return 2
    if not args.apply:
        out("DRY RUN: nothing written. Re-run with --apply to add it.")
    elif result.get("changed"):
        after = client.get_contact(args.contact_id)
        out(f"WRITTEN. primary email now: {after.get('email')}; all emails on the contact: {gc.contact_emails(after)}")
    else:
        out(f"Nothing to do: {result.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
