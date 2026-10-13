"""
Dry-run report: compare the live student roster sheet with the students in the app. Read-only: no student, GHL or sheet is changed.

  python execution/student_roster_check.py            # run inside the cron container (needs the database + the roster settings)
  python execution/student_roster_check.py --days 30  # window for "recent interview mail" (default 30)

Needs STUDENT_ROSTER_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_KEY_PATH (the roster sheet shared with that service account as Viewer).
Emails are masked in the output. Who to verify or reject is still decided by a person in Review -> Verify students.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(_ROOT, "execution"), _ROOT, os.path.join(_ROOT, "services", "dashboard", "api")):
    if p not in sys.path:
        sys.path.insert(0, p)

import student_roster as sr  # noqa: E402


def load_students(db, since):
    from models import InterviewEvent, Student, StudentVerification
    from sqlalchemy import func
    verif = {v.student_id: v.status for v in db.query(StudentVerification).all()}
    recent = dict(db.query(InterviewEvent.student_id, func.count(InterviewEvent.id))
                  .filter(InterviewEvent.created_at >= since, InterviewEvent.student_id != None)  # noqa: E711
                  .group_by(InterviewEvent.student_id).all())
    out = []
    for s in db.query(Student).filter(Student.is_active == True).all():  # noqa: E712
        out.append({"id": s.id, "username": s.username, "full_name": s.full_name, "personal_email": s.personal_email,
                    "assigned_gmail": s.assigned_gmail, "verification": verif.get(s.id, "(none)"), "recent_events": recent.get(s.id, 0)})
    return out


def run(db, roster, days: int = 30, out=print) -> int:
    since = datetime.utcnow() - timedelta(days=days)
    students = load_students(db, since)
    info = {s["id"]: s for s in students}
    res = sr.compare(students, roster)
    active = [r for r in roster if r.active]
    out(f"Roster: {len(roster)} rows, {len(active)} active or in progress. App: {len(students)} active students.\n")

    out(f"MATCHED BY EMAIL ({len(res['by_email'])}): the same person")
    for m in res["by_email"]:
        s = info[m.student_id]
        out(f"  {m.student_name:<28} roster: {m.row.status:<12} app verification: {s['verification']:<10} interview mail last {days}d: {s['recent_events']}")

    out(f"\nSAME NAME, DIFFERENT EMAIL ({len(res['by_name_only'])}): probably the same person; the app holds another address")
    for m in res["by_name_only"]:
        s = info[m.student_id]
        ours = ", ".join(sorted({sr.mask_email(e) for e in (sr.norm_email(s["personal_email"]), sr.norm_email(s["assigned_gmail"])) if e})) or "(none)"
        theirs = ", ".join(sr.mask_email(e) for e in m.row.emails) or "(none)"
        out(f"  {m.student_name:<28} roster '{m.row.name}' ({m.row.status}) emails {theirs} | app: {ours} | verification: {s['verification']}")

    out(f"\nNOT ON THE ROSTER ({len(res['not_on_roster'])}): not a listed student; a person must decide")
    for m in res["not_on_roster"]:
        s = info[m.student_id]
        out(f"  {m.student_name:<28} app verification: {s['verification']:<10} interview mail last {days}d: {s['recent_events']}")

    out(f"\nACTIVE ON THE ROSTER, NOT IN THE APP ({len(res['roster_without_student'])}): no interview mail has reached us for them")
    for r in res["roster_without_student"]:
        out(f"  {r.name:<28} {r.status}")
    out(f"\nRoster emails the app does not hold for any student: {len(res['roster_emails_unknown_to_us'])} (they stay in the sheet only)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
    from process_inbox_auto import get_db_session
    roster = sr.fetch_roster()
    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")
    try:
        return run(db, roster, args.days)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
