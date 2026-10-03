"""
Identify the student for interview events that have none, by re-reading the original email's recipient in Gmail.

The recipient headers (To / Delivered-To) are not stored with an email, so older events could not be matched to a student
("Student not identified") even though the email was addressed to the student's own Gmail. This script looks each such event's
email up in Gmail by Message-ID (read-only), runs the same student identification the pipeline now uses
(`process_inbox_auto._identify_student`: roster by email, then the recipient Gmail itself), attaches the student to the event, and
creates the notification DRAFT if the event has none. Nothing is sent: a draft only waits for Rob's approval.

Dry-run by default; nothing is written without --apply. Safe to rerun (an event that already has a student is skipped).

Usage (inside the cron container on the server):
    python execution/backfill_event_students.py            # report only
    python execution/backfill_event_students.py --apply    # attach students and create drafts
"""

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger("backfill_event_students")


def draft_sub_type(stored: str) -> str:
    """The pipeline stores sub-types in two spellings; the draft templates are chosen from the title-case one."""
    value = (stored or "").strip()
    return value if " " in value or value[:1].isupper() else value.replace("_", " ").title()


def email_data_from_gmail(parsed: Dict[str, Any], email_row: Any) -> Dict[str, Any]:
    """The pipeline's email_data, from the real message (recipient headers included) plus the stored row."""
    data = dict(parsed)
    data.setdefault("body", data.get("body_content", ""))
    data["from"] = data.get("sender_email") or email_row.from_address
    data["from_email"] = data["from"]
    return data


def run(apply: bool, limit: int = 0) -> Counter:
    from process_inbox_auto import get_db_session, _identify_student
    from backfill_email_bodies import _imap, lookup, ALL_MAIL
    from backfill_interview_events import build_inputs
    from log_interview import upsert_student, log_notification_draft
    from models import Classification, Email, InterviewEvent, NotificationDraft
    from sqlalchemy import func

    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")

    events = (db.query(InterviewEvent).filter(InterviewEvent.student_id.is_(None))
              .order_by(InterviewEvent.id.desc()).all())
    if limit:
        events = events[:limit]
    result = Counter()
    imap = _imap()
    imap.select(ALL_MAIL, readonly=True)
    for event in events:
        email = db.get(Email, event.email_id)
        if email is None or not email.message_id:
            result["no message id"] += 1
            continue
        try:
            parsed = lookup(imap, email.message_id)
        except Exception as exc:
            result["gmail error"] += 1
            logger.warning(f"lookup failed for event {event.id}: {exc}")
            imap = _imap()
            imap.select(ALL_MAIL, readonly=True)
            continue
        if parsed is None:
            result["email not in gmail"] += 1
            continue
        cls_row = (db.query(Classification).filter(Classification.email_id == email.id)
                   .order_by(Classification.id.desc()).first())
        if cls_row is None:
            result["no classification"] += 1
            continue
        _, classification = build_inputs(email, cls_row)
        email_data = email_data_from_gmail(parsed, email)
        config, gmail = _identify_student(db, email_data, classification)
        if not config:
            result["still not identified"] += 1
            continue
        how = config.get("identified_by") or "roster / known student"
        result[f"identified: {how}"] += 1
        label = f"event {event.id} [{event.sub_type}] {event.company_name} -> {config['name']} ({how})"
        if not apply:
            print("would attach:", label)
            continue

        username = config.get("username") or config["name"].lower().replace(" ", ".")
        student = upsert_student(db=db, username=username, full_name=config["name"],
                                 personal_email=config.get("personal_email"), assigned_gmail=gmail,
                                 phone_number=config.get("phone") or None)
        event.student_id = student["id"]
        db.commit()
        has_draft = db.query(NotificationDraft.id).filter(NotificationDraft.interview_event_id == event.id).first()
        if not has_draft:
            from draft_notification import draft_notification
            from notify_student import _build_student_info_for_draft, _build_classification_for_draft
            sub = {"interview_sub_type": draft_sub_type(event.sub_type), "is_job_machine": bool(event.is_job_machine)}
            draft = draft_notification(
                classification=_build_classification_for_draft(classification, email_data, sub),
                student_info=_build_student_info_for_draft({**config, "phone": config.get("phone") or ""}),
                assistant_name=config.get("assigned_to"))
            log_notification_draft(db=db, interview_event_id=event.id, draft=draft,
                                   auto_send_eligible=draft["draft_status"] == "ready")
            result["draft created"] += 1
        print("attached:", label)
    try:
        imap.logout()
    except Exception:
        pass
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    print(dict(run(args.apply, args.limit)))
    if not args.apply:
        print("DRY RUN: nothing was written. Re-run with --apply to attach students and create drafts.")


if __name__ == "__main__":
    main()
