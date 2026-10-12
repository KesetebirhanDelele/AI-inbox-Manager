"""
Put unsent notices for assessments right (one-off, safe to rerun; dry run by default).

Before 2026-10-12 an email classified "Assessment" could still become an interview-type notice, because the interview sub-classifier
relabelled it "Technical Interview" or "Interview Request", and the same assessment announced by two systems (the employer's applicant system and
the test vendor) gave two notices. For every unsent notice of an Assessment email this script
  1. sets the event's type to "Assessment" and rewrites the draft with the assessment wording ("a test, not an interview"),
  2. keeps ONE notice per student and company: the one whose email has readable text (else the earliest); the others are rejected
     (reviewed_by "duplicate-assessment"). Nothing is deleted and nothing is sent.

Usage (inside the cron container on the server):
    python execution/fix_assessment_notices.py            # list only
    python execution/fix_assessment_notices.py --apply
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def plan(db) -> List[Dict[str, Any]]:
    """One row per unsent notice of an Assessment email, with what to do: 'keep' (rewrite it) or 'reject' (a duplicate)."""
    import models as M
    from process_inbox_auto import _normalise_company

    rows = []
    for event in db.query(M.InterviewEvent).all():
        email = db.get(M.Email, event.email_id)
        if email is None:
            continue
        cls = db.query(M.Classification).filter(M.Classification.email_id == email.id).order_by(M.Classification.id.desc()).first()
        if cls is None or cls.category != "Assessment":
            continue
        draft = db.query(M.NotificationDraft).filter(M.NotificationDraft.interview_event_id == event.id).first()
        if draft is None or draft.email_status not in ("draft", "approved"):
            continue
        seq = db.query(M.NotificationSequence).filter(M.NotificationSequence.draft_id == draft.id).first()
        if seq is not None and any(a.sent_at for a in seq.attempts):
            continue
        rows.append({"event": event, "draft": draft, "email": email, "key": (event.student_id, _normalise_company(event.company_name)),
                     "has_text": len((email.full_body or "").strip()) >= 40})
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["key"], []).append(r)
    for group in groups.values():
        group.sort(key=lambda r: (not r["has_text"], r["email"].received_date))      # readable text first, then the earliest
        for i, r in enumerate(group):
            r["action"] = "keep" if i == 0 or not r["key"][0] or not r["key"][1] else "reject"
    return rows


def apply_plan(db, rows: List[Dict[str, Any]], now: datetime = None) -> Dict[str, int]:
    import notification_messages as nm
    import models as M

    now = now or datetime.utcnow()
    kept = rejected = 0
    for r in rows:
        event, draft = r["event"], r["draft"]
        event.sub_type = "Assessment"
        if r["action"] == "reject":
            draft.email_status, draft.reviewed_by, draft.reviewed_at = "rejected", "duplicate-assessment", now
            rejected += 1
            continue
        student = db.get(M.Student, event.student_id) if event.student_id else None
        facts = nm.facts_from_event(event, student)
        draft.template_id = "next_round_assessment"
        draft.email_subject, draft.email_body = nm.email_subject(facts), nm.email_body(facts)
        kept += 1
    db.commit()
    return {"rewritten": kept, "rejected_as_duplicates": rejected}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="rewrite and reject (default: list only)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        print("No database connection.")
        return 1
    rows = plan(db)
    for r in rows:
        e = r["event"]
        print(f"{r['action']:6} event {e.id} draft {r['draft'].id} | type now {e.sub_type} | {(e.company_name or '')[:34]} | "
              f"text: {'yes' if r['has_text'] else 'NO'} | from {(r['email'].from_address or '')[:30]}")
    print(f"{len(rows)} unsent assessment notice(s)")
    if not args.apply or not rows:
        print("List only: nothing changed." if not args.apply else "Nothing to do.")
        return 0
    print(apply_plan(db, rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
