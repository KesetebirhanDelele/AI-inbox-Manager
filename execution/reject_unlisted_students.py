"""
Reject the students who are NOT on the live roster and still have a pending (unverified) verification. Dry run unless --apply.

  python execution/reject_unlisted_students.py                       # shows who would be rejected, changes nothing
  python execution/reject_unlisted_students.py --apply --by "Kes"    # rejects them

Rule (Kes, 2026-10-13): someone who is not on the roster is on their own, so we do not notify them. Only students whose verification is
"unverified" are touched; verified students, students with no verification row, and anyone on the roster are left alone and listed.
Same effect as "Not a student: reject" in the Verify box: verification becomes "rejected", notices that have not gone out are closed,
follow-up plans are closed. Nothing is deleted or sent. A student with a notice that already went out is skipped for a person to handle.
"""
import argparse
import os
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(_ROOT, "execution"), _ROOT, os.path.join(_ROOT, "services", "dashboard", "api")):
    if p not in sys.path:
        sys.path.insert(0, p)

import student_roster as sr  # noqa: E402
import student_roster_check as chk  # noqa: E402

REASON = "not on the student roster"


def run(db, roster, apply: bool = False, by: str = "roster-check", out=print) -> dict:
    from models import InterviewEvent, NotificationDraft, NotificationSequence, StudentVerification
    import escalation_engine as engine

    students = chk.load_students(db, datetime(2000, 1, 1))
    res = sr.compare(students, roster)
    info = {s["id"]: s for s in students}
    done, skipped, left = [], [], []
    now = datetime.utcnow()
    for m in res["not_on_roster"]:
        s = info[m.student_id]
        if s["verification"] != "unverified":
            left.append((m.student_name, s["verification"]))
            continue
        drafts = (db.query(NotificationDraft).join(InterviewEvent, NotificationDraft.interview_event_id == InterviewEvent.id)
                  .filter(InterviewEvent.student_id == m.student_id).all())
        seqs = [db.query(NotificationSequence).filter(NotificationSequence.draft_id == d.id).first() for d in drafts]
        if any(d.email_status == "sent" for d in drafts) or any(sq is not None and any(a.sent_at for a in sq.attempts) for sq in seqs):
            skipped.append(m.student_name)
            continue
        closing = [d for d in drafts if d.email_status in ("draft", "approved")]
        out(f"  {'REJECT' if apply else 'would reject'}: {m.student_name:<22} notices to close: {len(closing)}, plans to close: {sum(1 for q in seqs if q is not None and q.status == 'active')}")
        if apply:
            v = db.query(StudentVerification).filter(StudentVerification.student_id == m.student_id).first()
            v.status, v.verified_by, v.verified_at = "rejected", by, now
            for d, sq in zip(drafts, seqs):
                if sq is not None and sq.status == "active":
                    engine.close_sequence(db, sq, by, now)
                if d.email_status in ("draft", "approved"):
                    d.email_status, d.reviewed_by, d.reviewed_at, d.send_error = "rejected", by, now, f"Rejected: {REASON}"
            db.commit()
        done.append(m.student_name)
    out(f"\n{'Rejected' if apply else 'Would reject'}: {len(done)}. Skipped (a notice already went out, handle by hand): {len(skipped)} {skipped}")
    out(f"Not on the roster but left alone (verified, or no verification row): {len(left)}")
    for name, v in left:
        out(f"  {name:<22} verification: {v}")
    return {"done": done, "skipped": skipped, "left": left}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--by", default="roster-check")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
    from process_inbox_auto import get_db_session
    roster = sr.fetch_roster()
    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")
    try:
        run(db, roster, args.apply, args.by)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
