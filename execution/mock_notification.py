"""
Make a MOCK interview notification card for ONE existing student (normally the tester's own contact), to try the whole approval flow end to end:
the alert email to the approver, the tap-to-approve link, and (when live delivery is on) the real call, text and email to that student.

  python execution/mock_notification.py --find kes                  list matching students (id, name, masked contact); changes nothing
  python execution/mock_notification.py --student-id 12             DRY RUN: says what it would create; changes nothing
  python execution/mock_notification.py --student-id 12 --create    creates the mock email, interview and draft card, then sends the approver alert

The card is clearly marked ("TEST Company (mock)", "[TEST]"), is dated tomorrow 10:00 Central, and is a normal card: it can be approved or rejected like any other.
Approving it with live delivery ON really contacts the student. Nothing here writes to GHL; only approving does.
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "execution", _ROOT / "services" / "dashboard" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MOCK_COMPANY = "TEST Company (mock)"
MOCK_POSITION = "Mock interview, please ignore"


def _mask(value: str) -> str:
    value = value or ""
    if "@" in value:
        name, _, domain = value.partition("@")
        return f"{name[:2]}***@{domain}"
    return f"***{value[-4:]}" if len(value) >= 4 else "***"


def find_students(db, text: str):
    import models as M
    like = f"%{text.strip().lower()}%"
    from sqlalchemy import func, or_
    return (db.query(M.Student)
            .filter(or_(func.lower(M.Student.full_name).like(like), func.lower(M.Student.username).like(like),
                        func.lower(M.Student.personal_email).like(like)))
            .order_by(M.Student.id).limit(20).all())


def create_mock(db, student_id: int, now: datetime = None):
    """Create the mock email, interview event and open draft card for this student. Returns (event, draft)."""
    import models as M
    now = now or datetime.utcnow()
    student = db.get(M.Student, student_id)
    if student is None:
        raise SystemExit(f"No student with id {student_id}.")
    if not (student.phone_number or student.personal_email or student.assigned_gmail):
        raise SystemExit("That student has no phone, email or Gmail on file: nothing could be sent to them.")
    tomorrow = (now.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Chicago")) + timedelta(days=1)).strftime("%Y-%m-%d")
    mail = M.Email(email_id=f"mock-{int(now.timestamp())}", subject="[TEST] Mock interview notification", from_address="mock@test.invalid",
                   received_date=now)
    db.add(mail)
    db.flush()
    event = M.InterviewEvent(email_id=mail.id, student_id=student.id, sub_type="Phone Screen", company_name=MOCK_COMPANY, position_title=MOCK_POSITION,
                             interview_date=tomorrow, interview_time="10:00", interview_timezone="CT", interview_format="phone", confidence=0.95,
                             raw_extraction={"mock": True})
    db.add(event)
    db.flush()
    recipient = student.personal_email or student.assigned_gmail or ""
    draft = M.NotificationDraft(
        interview_event_id=event.id, template_id="mock", recipient_email=recipient, email_status="draft",
        email_subject=f"[TEST] Interview notification: {MOCK_COMPANY}",
        email_body=(f"Hello {student.full_name},\n\nThis is a TEST of the interview notification system. {MOCK_COMPANY} has a mock phone screen for "
                    f"{MOCK_POSITION} on {tomorrow} at 10:00 AM Central. No real interview exists; please reply YES to confirm you received this test.\n"),
        auto_send_eligible=False, missing_fields=[])
    db.add(draft)
    db.commit()
    return event, draft


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Create a mock interview notification card for one existing student.")
    ap.add_argument("--find", help="list students whose name, username or email contains this text")
    ap.add_argument("--student-id", type=int)
    ap.add_argument("--create", action="store_true", help="really create the mock card and send the approver alert (default: dry run)")
    ap.add_argument("--no-alert", action="store_true", help="create the card but do not send the approver alert email")
    args = ap.parse_args(argv)

    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        print("No database connection.")
        return 1
    import models as M

    if args.find:
        for s in find_students(db, args.find):
            print(f"id={s.id} name={s.full_name!r} phone={_mask(s.phone_number or '')} email={_mask(s.personal_email or s.assigned_gmail or '')}")
        return 0
    if not args.student_id:
        ap.error("give --student-id (or --find to look one up)")
    student = db.get(M.Student, args.student_id)
    if student is None:
        print(f"No student with id {args.student_id}.")
        return 1
    print(f"Student: {student.full_name!r} (id {student.id}), phone {_mask(student.phone_number or '')}, email {_mask(student.personal_email or student.assigned_gmail or '')}")
    if not args.create:
        print("DRY RUN: would create a mock email, a Phone Screen at TEST Company (mock) tomorrow 10:00 CT, and an open draft card. Add --create to do it.")
        return 0
    event, draft = create_mock(db, student.id)
    print(f"Created interview event {event.id} and draft card {draft.id}.")
    if not args.no_alert:
        import review_alerts
        print("Approver alert:", review_alerts.run(db))
    print("Open the Review page (or the link in the alert email) to approve or reject it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
