"""
Put the emails of students who still need verifying into the Gmail label "Verify Student" (one-off, safe to rerun).

The pipeline now adds that label to NEW mail whose student had to be guessed (execution/process_inbox_auto.py). This script does the same for mail
that was processed before: for every pending notification draft (or every draft with --all-drafts) whose student is not verified yet, it
  1. applies the label "Verify Student" to the original email (looked up in "All Mail" by its Message-ID header; labels are global in Gmail), then
  2. takes the email out of the folder it was filed in (flag \\Deleted + UID EXPUNGE scoped to THAT folder only, which removes that folder's label,
     never the message: the new label keeps it alive, the same documented method as fetch_emails.move_emails), then
  3. records current_folder = "Verify Student" in the database.
Messages are always found by Message-ID, never by the stored IMAP number (that number is per folder and goes stale).

Dry-run by default: it only prints what it would do (counts and folders, no subjects). Nothing in Gmail or the database changes without --apply.
Nothing is deleted: a message that cannot be found is skipped and reported.

Usage (inside the cron container on the server):
    python execution/label_verify_students.py                # plan only
    python execution/label_verify_students.py --apply        # label and move
    python execution/label_verify_students.py --apply --keep-in-place   # label only, leave every email where it is
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger("label_verify_students")
LABEL = "Verify Student"
ALL_MAIL = '"[Gmail]/All Mail"'


def plan(db, all_drafts: bool = False) -> List[Dict[str, Any]]:
    """The emails to label: one row per email whose student is unverified and whose notification draft is still pending."""
    import models as M

    q = (db.query(M.Email)
         .join(M.InterviewEvent, M.InterviewEvent.email_id == M.Email.id)
         .join(M.StudentVerification, M.StudentVerification.student_id == M.InterviewEvent.student_id)
         .join(M.NotificationDraft, M.NotificationDraft.interview_event_id == M.InterviewEvent.id)
         .filter(M.StudentVerification.status != "verified"))
    if not all_drafts:
        q = q.filter(M.NotificationDraft.email_status == "draft")
    seen, items = set(), []
    for email in q.order_by(M.Email.received_date).all():
        if email.id in seen or (email.current_folder or "") == LABEL:
            continue
        seen.add(email.id)
        items.append({"email_id": email.id, "message_id": (email.message_id or "").strip(), "folder": email.current_folder or "INBOX"})
    return items


def _uid_by_message_id(imap, message_id: str) -> Optional[str]:
    status, data = imap.uid("SEARCH", None, "HEADER", "Message-ID", message_id)
    if status != "OK" or not data or not data[0]:
        return None
    uids = data[0].split()
    return uids[-1].decode() if uids else None


def apply_items(imap, items: List[Dict[str, Any]], move: bool = True) -> Dict[str, List[int]]:
    """Label (and optionally move) each item. Returns {"labelled": [...], "moved": [...], "skipped": [...]} of email ids."""
    from fetch_emails import _gm_label_atom, _quote_folder

    out: Dict[str, List[int]] = {"labelled": [], "moved": [], "skipped": []}
    status, _ = imap.select(ALL_MAIL)
    if status != "OK":
        raise RuntimeError("Cannot open All Mail")
    labelled_ids = []
    for it in items:
        if not it["message_id"]:
            out["skipped"].append(it["email_id"])
            continue
        uid = _uid_by_message_id(imap, it["message_id"])
        if not uid:
            logger.warning(f"email {it['email_id']}: not found in All Mail by Message-ID; skipped")
            out["skipped"].append(it["email_id"])
            continue
        s, _r = imap.uid("STORE", uid, "+X-GM-LABELS", f"({_gm_label_atom(LABEL)})")
        if s != "OK":
            out["skipped"].append(it["email_id"])
            continue
        out["labelled"].append(it["email_id"])
        labelled_ids.append(it)

    if move:
        by_folder: Dict[str, List[Dict[str, Any]]] = {}
        for it in labelled_ids:
            by_folder.setdefault(it["folder"], []).append(it)
        for folder, group in by_folder.items():
            if folder == LABEL:
                continue
            s, _ = imap.select(_quote_folder(folder))
            if s != "OK":
                logger.warning(f"folder {folder!r} cannot be opened: {len(group)} email(s) stay where they are (labelled only)")
                continue
            flagged, ids = [], []
            for it in group:
                uid = _uid_by_message_id(imap, it["message_id"])
                if not uid:
                    continue                      # no longer in that folder: nothing to remove
                s2, _r2 = imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                if s2 == "OK":
                    flagged.append(uid)
                    ids.append(it["email_id"])
            if flagged:
                typ, _resp = imap.uid("EXPUNGE", ",".join(flagged))      # UID-scoped to this folder; never a blind expunge
                if typ == "OK":
                    out["moved"].extend(ids)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="change Gmail and the database (default: plan only)")
    ap.add_argument("--all-drafts", action="store_true", help="include students whose draft is no longer pending")
    ap.add_argument("--keep-in-place", action="store_true", help="add the label but do not take the email out of its folder")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        print("No database connection.")
        return 1
    items = plan(db, all_drafts=args.all_drafts)
    folders: Dict[str, int] = {}
    for it in items:
        folders[it["folder"]] = folders.get(it["folder"], 0) + 1
    print(f"{len(items)} email(s) belong to unverified students; currently filed in: {folders or 'none'}")
    if not args.apply or not items:
        print("Plan only: nothing changed." if not args.apply else "Nothing to do.")
        return 0

    from fetch_emails import connect_to_imap
    imap = connect_to_imap(os.getenv("EMAIL_SERVER") or "imap.gmail.com", int(os.getenv("EMAIL_PORT", "993")),
                           os.environ["EMAIL_ADDRESS"], os.environ["EMAIL_PASSWORD"])
    try:
        result = apply_items(imap, items, move=not args.keep_in_place)
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    import models as M
    for email_id in (result["moved"] if not args.keep_in_place else []):
        row = db.get(M.Email, email_id)
        if row is not None:
            row.current_folder = LABEL
    db.commit()
    print(f"labelled {len(result['labelled'])}, moved {len(result['moved'])}, skipped {len(result['skipped'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
