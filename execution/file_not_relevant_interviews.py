"""
Close the interview notices whose email the rules now call "not relevant" (one-off, safe to rerun; dry run by default).

Example: a home-care firm asking a student for a call about a Certified Nursing Assistant posting. Such a job has nothing to do with the
data and technology training, and Kes decided (2026-10-12) it must not create a student notice. New mail is caught by the rule in
process_inbox_auto.pre_classify_by_sender; this script handles the ones that already created an interview event and a draft.

For every interview event whose email the rules now classify as "Other" and whose draft is still draft or approved with nothing yet sent:
  1. the draft is rejected (it leaves the approval screen; the record says why),
  2. the email is moved to Spam Review in Gmail by Message-ID (the pipeline's route for "Other"; nothing is deleted),
  3. a new classification row "Other" is recorded and emails.current_folder is updated.
The interview event itself is kept (it still shows in Reports > Interviews); delete it by hand if you want it gone.

Usage (inside the cron container on the server):
    python execution/file_not_relevant_interviews.py            # list only
    python execution/file_not_relevant_interviews.py --apply
"""
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

TARGET = "Spam Review"
REVIEWER = "not-relevant-rule"


def plan(db) -> List[Dict[str, Any]]:
    import models as M
    from process_inbox_auto import pre_classify_by_sender
    from text_cleaning import clean_email_text

    items = []
    for event in db.query(M.InterviewEvent).all():
        email = db.get(M.Email, event.email_id)
        draft = db.query(M.NotificationDraft).filter(M.NotificationDraft.interview_event_id == event.id).first()
        if email is None or draft is None or draft.email_status not in ("draft", "approved"):
            continue
        seq = db.query(M.NotificationSequence).filter(M.NotificationSequence.draft_id == draft.id).first()
        if seq is not None and any(a.sent_at for a in seq.attempts):
            continue                                       # something already went out: a person decides
        verdict = pre_classify_by_sender({"sender_email": email.from_address, "subject": email.subject,
                                          "body_content": clean_email_text(email.full_body or email.body_preview or "")})
        if verdict != "Other":
            continue
        student = db.get(M.Student, event.student_id) if event.student_id else None
        items.append({"event_id": event.id, "draft_id": draft.id, "email_id": email.id, "message_id": (email.message_id or "").strip(),
                      "student": (student.full_name if student else "(none)"), "company": event.company_name or "",
                      "position": event.position_title or "", "folder": email.current_folder or "INBOX"})
    return items


def apply_plan(db, items: List[Dict[str, Any]], relabel, now: datetime = None) -> Dict[str, int]:
    """`relabel(message_id, target) -> bool` moves the mail in Gmail. A mail Gmail cannot find still gets its draft rejected."""
    import models as M
    now = now or datetime.utcnow()
    moved = missing = 0
    for it in items:
        draft = db.get(M.NotificationDraft, it["draft_id"])
        draft.email_status = "rejected"
        draft.reviewed_by, draft.reviewed_at = REVIEWER, now
        email = db.get(M.Email, it["email_id"])
        ok = bool(it["message_id"]) and relabel(it["message_id"], TARGET)
        if ok:
            email.current_folder = TARGET
            moved += 1
        else:
            missing += 1
        db.add(M.Classification(email_id=email.id, category="Other", confidence=0.99, classifier_version=REVIEWER,
                                raw_response={"reason": "not relevant: care job unrelated to the training"}))
    db.commit()
    return {"rejected": len(items), "moved": moved, "not_found_in_gmail": missing}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="reject the drafts and move the mail (default: list only)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        print("No database connection.")
        return 1
    items = plan(db)
    for it in items:
        print(f"event {it['event_id']} draft {it['draft_id']}: {it['student']} | {it['company'][:40]} | {it['position'][:40]} | in {it['folder']}")
    print(f"{len(items)} interview notice(s) are not relevant")
    if not args.apply or not items:
        print("List only: nothing changed." if not args.apply else "Nothing to do.")
        return 0
    import models as M
    from fetch_emails import relabel_by_message_id
    known = {r[0] for r in db.query(M.Email.current_folder).distinct() if r[0]} | {"INBOX"}

    def relabel(message_id, target):
        return relabel_by_message_id(os.getenv("EMAIL_SERVER") or "imap.gmail.com", int(os.getenv("EMAIL_PORT", "993")),
                                     os.environ["EMAIL_ADDRESS"], os.environ["EMAIL_PASSWORD"], message_id, target, known)

    print(apply_plan(db, items, relabel))
    return 0


if __name__ == "__main__":
    sys.exit(main())
