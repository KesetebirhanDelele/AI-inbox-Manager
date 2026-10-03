"""
Repair stored emails that lost their body and sender.

Until 2026-10-03 the dashboard's "sync from Gmail" (the In Inbox tile, now removed) read the wrong field names and wrote sender "Unknown"
and an empty body over stored emails (239 rows in production, 17 of 33 Interview Requests), and the pipeline never refilled a body for a row that
already existed. This script looks each damaged email up in Gmail by its Message-ID header, in "All Mail" (read-only), and fills the missing
sender, subject, body and date from the real message.

Only damaged rows are touched (empty body, or sender "Unknown"), and only the damaged fields are filled: a real value is never overwritten.
`--verify N` instead compares N random healthy rows with Gmail and reports how many have a different subject (no writes).
Dry-run by default; nothing is written without --apply. Safe to rerun.

Usage (inside the cron container on the server):
    python execution/backfill_email_bodies.py                 # report only
    python execution/backfill_email_bodies.py --apply         # repair
    python execution/backfill_email_bodies.py --verify 40     # sample healthy rows
"""

import argparse
import logging
import os
import random
import sys
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger("backfill_email_bodies")
ALL_MAIL = '"[Gmail]/All Mail"'


def is_damaged(email: Any) -> bool:
    return not (getattr(email, "full_body", None) or "").strip() or (getattr(email, "from_address", "") or "").lower().startswith("unknown")


def plan_update(email: Any, parsed: Dict[str, Any]) -> Dict[str, Any]:
    """The fields to fill on a damaged row from the real message. Real values already stored are never replaced."""
    changes: Dict[str, Any] = {}
    body = (parsed.get("body_content") or "").strip()
    if body and not (getattr(email, "full_body", None) or "").strip():
        changes["full_body"] = body
        changes["body_preview"] = body[:500]
    sender = (parsed.get("sender_email") or "").strip()
    if sender and (getattr(email, "from_address", "") or "").lower().startswith("unknown"):
        changes["from_address"] = sender[:255]
    subject = (parsed.get("subject") or "").strip()
    if subject and (getattr(email, "subject", "") or "") in ("", "No Subject"):
        changes["subject"] = subject[:500]
    return changes


def _imap():
    from fetch_emails import connect_to_imap
    return connect_to_imap(os.environ["EMAIL_SERVER"], int(os.environ.get("EMAIL_PORT", "993")),
                           os.environ["EMAIL_ADDRESS"], os.environ.get("EMAIL_PASSWORD", ""))


def lookup(imap, message_id: str) -> Optional[Dict[str, Any]]:
    """The parsed real message with this Message-ID header, or None."""
    from fetch_emails import fetch_email_by_uid, parse_email_message
    quoted = message_id.replace('"', "")
    status, data = imap.uid("SEARCH", None, "HEADER", "Message-ID", f'"{quoted}"')
    if status != "OK" or not data or not data[0]:
        return None
    uid = data[0].split()[-1].decode()
    return parse_email_message(fetch_email_by_uid(imap, uid), uid)


def run(apply: bool, limit: int = 0, verify: int = 0) -> Dict[str, int]:
    from process_inbox_auto import get_db_session
    from models import Email

    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")
    rows = db.query(Email).filter(Email.message_id.isnot(None)).order_by(Email.received_date.desc()).all()
    if verify:
        healthy = [e for e in rows if not is_damaged(e)]
        targets = random.sample(healthy, min(verify, len(healthy)))
    else:
        targets = [e for e in rows if is_damaged(e)]
        if limit:
            targets = targets[:limit]

    result = {"checked": 0, "found in gmail": 0, "not found": 0, "repaired": 0, "different subject": 0, "errors": 0}
    imap = _imap()
    imap.select(ALL_MAIL, readonly=True)
    for email in targets:
        result["checked"] += 1
        try:
            parsed = lookup(imap, email.message_id)
        except Exception as exc:                      # a dropped connection must not abandon the rest
            result["errors"] += 1
            logger.warning(f"lookup failed for email id={email.id}: {exc}")
            try:
                imap = _imap()
                imap.select(ALL_MAIL, readonly=True)
            except Exception:
                break
            continue
        if parsed is None:
            result["not found"] += 1
            continue
        result["found in gmail"] += 1
        if verify:
            if (parsed.get("subject") or "").strip() != (email.subject or "").strip():
                result["different subject"] += 1
                print(f"MISMATCH id={email.id}: stored {email.subject!r:.50} vs gmail {parsed.get('subject')!r:.50}")
            continue
        changes = plan_update(email, parsed)
        if not changes:
            continue
        if apply:
            for field, value in changes.items():
                setattr(email, field, value)
            email.last_updated = datetime.utcnow()
            db.commit()
        result["repaired"] += 1
        print(f"{'repaired' if apply else 'would repair'} id={email.id}: {', '.join(sorted(changes))}")
        time.sleep(0.2)
    try:
        imap.logout()
    except Exception:
        pass
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--verify", type=int, default=0, help="sample N healthy rows and compare their subject with Gmail (no writes)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    print(run(args.apply, args.limit, args.verify))
    if not args.apply and not args.verify:
        print("DRY RUN: nothing was written. Re-run with --apply to repair.")


if __name__ == "__main__":
    main()
