"""
Re-read every PENDING "Classification review" item with the corrected body and classify it again (one-off, safe to rerun).

Why: many items were queued when the classifier could not see the message (HTML in the text part, images, rules that did not exist yet).
Each item is run through the live path: the deterministic sender/body rules first, then the AI classifier on the cleaned text.
What is done with the answer:
  * a confident, non-interview category (see AUTO) is FILED: Gmail label + folder via file_review_items.apply_plan, approval closed;
  * "Other" at 50% or more is CLOSED (the pipeline already parked that mail in Spam Review / Quarantine; nothing is deleted);
  * everything else (any interview category, offers, rejections, requests for information, assessments, or low confidence) stays PENDING
    for a person, listed with the new suggestion.
A new classification row (classifier_version "review-reclassify") records the new answer; old rows are kept.

Dry-run by default: prints one line per item and the totals. Nothing changes in Gmail or the database without --apply.
The AI call sends the email text to the classifier, exactly as the pipeline does for new mail.

Usage (inside the cron container on the server):
    python execution/reclassify_review_items.py            # analyse only
    python execution/reclassify_review_items.py --apply
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

logger = logging.getLogger("reclassify_review_items")

# Categories that are filed automatically (never about an interview or a decision someone must make).
AUTO = ("Job Alert", "Job Invite", "LinkedIn Notification", "Application Notification", "Gmail Notification", "Basecamp", "Forwarded Email")
MIN_FILE_CONFIDENCE = 0.70      # same bar the pipeline uses to route
MIN_OTHER_CONFIDENCE = 0.50     # "Other" at or above this needs no person


def decide(category: str, confidence: float) -> str:
    """'file', 'close' or 'keep' for a new answer. Pure."""
    if category in AUTO and confidence >= MIN_FILE_CONFIDENCE:
        return "file"
    if category == "Other" and confidence >= MIN_OTHER_CONFIDENCE:
        return "close"
    return "keep"


def analyse(db, classify) -> List[Dict[str, Any]]:
    """One row per pending approval: the old answer, the new answer and the decision. `classify(email_data) -> {"category", "confidence", ...}`."""
    import models as M
    from process_inbox_auto import CATEGORY_TO_FOLDER, SPAM_REVIEW_FOLDER
    from text_cleaning import clean_email_text

    rows = (db.query(M.Approval, M.Email, M.Classification)
            .join(M.Email, M.Email.id == M.Approval.email_id)
            .join(M.Classification, M.Classification.id == M.Approval.classification_id)
            .filter(M.Approval.status == "pending").order_by(M.Email.received_date).all())
    out = []
    for approval, email, old in rows:
        email_data = {"subject": email.subject, "sender_email": email.from_address, "from": email.from_address,
                      "body_content": clean_email_text(email.full_body or email.body_preview or ""),
                      "message_id": email.message_id, "email_id": email.email_id}
        try:
            new = classify(email_data) or {}
        except Exception as exc:                      # one bad item must not stop the rest
            logger.warning(f"approval {approval.id}: classification failed ({exc}); left pending")
            new = {}
        category = str(new.get("category") or "")
        confidence = float(new.get("confidence") or 0.0)
        action = decide(category, confidence) if category else "keep"
        target = (SPAM_REVIEW_FOLDER if category == "Other" else CATEGORY_TO_FOLDER.get(category)) if action != "keep" else None
        if action == "file" and not target:
            action = "keep"
        out.append({"approval_id": approval.id, "email_id": email.id, "message_id": (email.message_id or "").strip(),
                    "folder": email.current_folder or "INBOX", "category": category, "confidence": confidence, "target": target,
                    "action": action, "old_category": old.category, "old_confidence": float(old.confidence or 0.0),
                    "sender": (email.from_address or "")[:45], "subject": (email.subject or "")[:50], "raw": new})
    return out


def live_classify(email_data: Dict[str, Any]) -> Dict[str, Any]:
    """The pipeline's own order: deterministic rules first, then the AI classifier."""
    from process_inbox_auto import pre_classify_by_sender
    from classify_email import classify_email

    rule = pre_classify_by_sender(email_data)
    if rule:
        return {"category": rule, "confidence": 0.99, "reasoning": "Deterministic rule"}
    result = classify_email(email_data, validate_only=False)
    result.pop("_gpt_usage", None)
    return result


def record_new_answers(db, rows: List[Dict[str, Any]]) -> None:
    """Keep the new answer on file (a new row; the old one stays)."""
    import models as M
    for r in rows:
        if r["category"]:
            db.add(M.Classification(email_id=r["email_id"], category=r["category"][:100], confidence=r["confidence"],
                                    classifier_version="review-reclassify", raw_response=r["raw"] or None))
    db.commit()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="file and close the items decided above (default: analyse only)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        print("No database connection.")
        return 1
    rows = analyse(db, live_classify)
    for r in rows:
        print(f"{r['action']:5} | {r['old_category']} {r['old_confidence']:.0%} -> {r['category'] or '?'} {r['confidence']:.0%} | {r['sender']} | {r['subject']}")
    totals: Dict[str, int] = {}
    for r in rows:
        totals[r["action"]] = totals.get(r["action"], 0) + 1
    print(f"\n{len(rows)} pending item(s): {totals}")
    if not args.apply:
        print("Analysis only: nothing changed.")
        return 0

    from file_review_items import apply_plan
    todo = [r for r in rows if r["action"] in ("file", "close")]
    if not todo:
        print("Nothing to apply.")
        return 0
    from fetch_emails import connect_to_imap
    imap = connect_to_imap(os.getenv("EMAIL_SERVER") or "imap.gmail.com", int(os.getenv("EMAIL_PORT", "993")),
                           os.environ["EMAIL_ADDRESS"], os.environ["EMAIL_PASSWORD"])
    try:
        out = apply_plan(db, imap, todo, now=datetime.utcnow())
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    record_new_answers(db, todo)
    print(f"applied: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
