"""
File the "Classification review" items that the deterministic sender/subject rules already know the answer to (one-off, safe to rerun).

The Review > Classification review list holds emails the AI was unsure about (confidence under 70%). Many are mail the rules in
process_inbox_auto.pre_classify_by_sender classify with certainty today (a bare LinkedIn job link is a Job Alert), but they were queued
before the rule existed. For every PENDING approval whose email a rule now classifies as one of FILEABLE, this script
  1. applies the destination Gmail label (looked up in "All Mail" by Message-ID) and takes the email out of the folder it sits in
     (the same documented, UID-scoped method as label_verify_students.apply_items; nothing is ever deleted),
  2. sets emails.current_folder to the destination, and
  3. closes the approval as "approved" (human_action move_to_folder, target_folder, human_category, reviewed_by "rule-filing").

Dry-run by default: prints counts per destination folder only. Nothing in Gmail or the database changes without --apply.
A rule answer of "Other" (marketing, community and social mail) goes to Spam Review, where the pipeline's own second pass sends it to Quarantine; nothing is deleted.
Interview-type results are never filed here: a person still decides those.

Usage (inside the cron container on the server):
    python execution/file_review_items.py            # plan only
    python execution/file_review_items.py --apply
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

logger = logging.getLogger("file_review_items")

# Only rule answers that are never about an interview.
FILEABLE = ("Job Alert", "LinkedIn Notification", "Basecamp", "Gmail Notification", "Other")
REVIEWER = "rule-filing"


def plan(db) -> List[Dict[str, Any]]:
    """One row per pending approval whose email a rule classifies as FILEABLE."""
    import models as M
    from process_inbox_auto import CATEGORY_TO_FOLDER, SPAM_REVIEW_FOLDER, pre_classify_by_sender

    rows = (db.query(M.Approval, M.Email).join(M.Email, M.Email.id == M.Approval.email_id)
            .filter(M.Approval.status == "pending").order_by(M.Email.received_date).all())
    items = []
    for approval, email in rows:
        category = pre_classify_by_sender({
            "sender_email": email.from_address, "subject": email.subject,
            "body_content": email.full_body or email.body_preview or ""})
        if category not in FILEABLE:
            continue
        items.append({"approval_id": approval.id, "email_id": email.id, "message_id": (email.message_id or "").strip(),
                      "folder": email.current_folder or "INBOX", "category": category, "target": CATEGORY_TO_FOLDER.get(category, SPAM_REVIEW_FOLDER)})
    return items


def apply_plan(db, imap, items: List[Dict[str, Any]], now: datetime = None) -> Dict[str, int]:
    """Move each item in Gmail (grouped by destination) and close its approval. Items Gmail could not find are left pending."""
    import models as M
    from label_verify_students import apply_items

    now = now or datetime.utcnow()

    def close(it):
        email = db.get(M.Email, it["email_id"])
        approval = db.get(M.Approval, it["approval_id"])
        if email is not None:
            email.current_folder = it["target"] if not _already_there(it) else email.current_folder
        if approval is not None:
            approval.status = "approved"
            approval.human_action = "move_to_folder"
            approval.target_folder = it["target"]
            approval.human_category = it["category"]
            approval.reviewed_by = REVIEWER
            approval.reviewed_at = now
            approval.notes = "Filed by rule (execution/file_review_items.py)"

    by_target: Dict[str, List[Dict[str, Any]]] = {}
    done = skipped = 0
    for it in items:
        if _already_there(it):
            close(it)          # the pipeline already filed the email; only its review approval was still open
            done += 1
        else:
            by_target.setdefault(it["target"], []).append(it)
    for target, group in by_target.items():
        result = apply_items(imap, group, move=True, label=target)
        moved = set(result["moved"])
        for it in group:
            if it["email_id"] not in moved:
                skipped += 1
                continue
            close(it)
            done += 1
    db.commit()
    return {"filed": done, "skipped": skipped}


def _already_there(it: Dict[str, Any]) -> bool:
    """The email already sits in the destination (Quarantine counts as past Spam Review): nothing to do in Gmail."""
    return it["folder"] == it["target"] or (it["target"] == "Spam Review" and it["folder"] == "Quarantine")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="change Gmail and the database (default: plan only)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        print("No database connection.")
        return 1
    items = plan(db)
    per: Dict[str, int] = {}
    for it in items:
        per[it["target"]] = per.get(it["target"], 0) + 1
    import models as M
    pending = db.query(M.Approval).filter(M.Approval.status == "pending").count()
    print(f"{len(items)} of {pending} pending review item(s) can be filed by rule: {per or 'none'}")
    if not args.apply or not items:
        print("Plan only: nothing changed." if not args.apply else "Nothing to do.")
        return 0

    from fetch_emails import connect_to_imap
    imap = connect_to_imap(os.getenv("EMAIL_SERVER") or "imap.gmail.com", int(os.getenv("EMAIL_PORT", "993")),
                           os.environ["EMAIL_ADDRESS"], os.environ["EMAIL_PASSWORD"])
    try:
        out = apply_plan(db, imap, items)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    print(f"filed {out['filed']}, skipped {out['skipped']} (left pending)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
