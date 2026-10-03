"""
Create the missing InterviewEvents for interview-related emails.

Until 2026-10-03 only emails classified "Interview Request" got an InterviewEvent. Phone Screen, Interview Cancelled / Confirmation /
Schedule, Assessment and similar emails were filed in folders with no event, so they never reached the Interviews page, Upcoming
interviews or the student notifications. The pipeline now creates them for new mail; this script does the same for the old mail.

It reuses the real pipeline step (`process_interview_email`: sub-classifier, student lookup, event, notification DRAFT), fed from what is
stored in the database (full body, classification). No email is sent: a draft only waits for the approver's approval.

Safe to rerun: an email that already has an event is skipped. Dry-run by default; nothing is written without --apply.

Usage (inside the api container on the server):
    python execution/backfill_interview_events.py            # report only
    python execution/backfill_interview_events.py --apply    # create the events
"""

import argparse
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Tuple

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger("backfill_interview_events")


# Application acknowledgements the primary classifier sometimes files as "Interview Cancelled": they are not interviews.
_NOT_AN_INTERVIEW_SUBJECT = re.compile(
    r"thank you for appl|application update|your application for|we.re ready when you are|application received|application status",
    re.I)


def normalized_subject(subject: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"^(re|fw|fwd):\s*", "", (subject or "").strip(), flags=re.I)).lower()


def skip_reason(category: str, subject: str, sender: str, seen: set) -> str:
    """Why this old email should NOT get an event (empty string = create it). `seen` holds (sender, subject) already handled, newest first."""
    if category == "Interview Cancelled" and _NOT_AN_INTERVIEW_SUBJECT.search(subject or ""):
        return "application notice mislabelled as a cancelled interview"
    key = ((sender or "").lower(), normalized_subject(subject))
    if key in seen:
        return "older repeat of the same message"
    seen.add(key)
    return ""


def build_inputs(email: Any, classification: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The (email_data, classification) dictionaries the pipeline step expects, rebuilt from stored rows."""
    body = getattr(email, "full_body", None) or getattr(email, "body_preview", None) or ""
    raw = getattr(classification, "raw_response", None)
    raw = dict(raw) if isinstance(raw, dict) else {}
    extracted = dict(raw.get("extracted_data") or {})
    extracted.setdefault("company_name", getattr(classification, "company_name", None))
    extracted.setdefault("position_title", getattr(classification, "position", None))
    email_data = {
        "email_id": email.email_id,
        "message_id": getattr(email, "message_id", None),
        "subject": email.subject,
        "sender_email": email.from_address,
        "from": email.from_address,
        "from_email": email.from_address,
        "sender_name": "",
        "email_date": email.received_date.isoformat() if getattr(email, "received_date", None) else "",
        "body_content": body,
        "body": body,
        "headers": {},
        "to_addresses": [],
    }
    cls = dict(raw)
    cls.update({
        "category": classification.category,
        "confidence": float(classification.confidence or 0.0),
        "extracted_data": extracted,
    })
    return email_data, cls


def run(apply: bool, limit: int = 0) -> Counter:
    from process_inbox_auto import get_db_session, creates_interview_event, process_interview_email
    from models import Classification, Email, InterviewEvent
    from sqlalchemy import func

    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")

    # newest classification per email
    newest = (db.query(Classification.email_id, func.max(Classification.id).label("cid"))
              .group_by(Classification.email_id).subquery())
    rows = (db.query(Email, Classification)
            .join(newest, Email.id == newest.c.email_id)
            .join(Classification, Classification.id == newest.c.cid)
            .order_by(Email.received_date.desc()).all())

    result = Counter()
    seen: set = set()
    for email, cls in rows:
        if not creates_interview_event({"category": cls.category, "confidence": float(cls.confidence or 0.0)}):
            continue
        if db.query(InterviewEvent.id).filter(InterviewEvent.email_id == email.id).first():
            result["already has an event"] += 1
            continue
        reason = skip_reason(cls.category, email.subject, email.from_address, seen)
        if reason:
            result[f"skipped: {reason}"] += 1
            print(f"skip ({reason}): [{cls.category}] {(email.subject or '')[:50]}")
            continue
        if limit and result["to create"] + result["created"] >= limit:
            break
        label = f"[{cls.category}] {email.received_date:%Y-%m-%d} {email.from_address.split('@')[-1][:30]} | {(email.subject or '')[:50]}"
        if not apply:
            result["to create"] += 1
            print("would create:", label)
            continue
        email_data, classification = build_inputs(email, cls)
        if process_interview_email(email_data, email.id, classification):
            result["created"] += 1
            print("created:", label)
        else:
            result["failed"] += 1
            print("FAILED:", label)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    print(dict(run(args.apply, args.limit)))
    if not args.apply:
        print("DRY RUN: nothing was written. Re-run with --apply to create the events.")


if __name__ == "__main__":
    main()
