"""Students not on the live roster with a pending verification are rejected (dry run changes nothing); everyone else is left alone."""
import sys
from datetime import datetime
from pathlib import Path

from conftest import make_email, make_interview_event, make_notification_draft, make_student

_EXEC = str(Path(__file__).resolve().parents[3] / "execution")
if _EXEC not in sys.path:
    sys.path.insert(0, _EXEC)

import reject_unlisted_students as ru  # noqa: E402
import student_roster as sr  # noqa: E402

ROSTER = sr.parse_rows([["Name", "STATUS", "Personal Email Address"], ["Listed Person", "Active", "listed@x.com"]])


def _student(db, username, name, email, verification, with_notice=True, sent=False):
    from models import NotificationAttempt, NotificationSequence, StudentVerification
    s = make_student(db, username=username, full_name=name)
    s.personal_email = email
    db.add(s); db.commit()
    if verification:
        db.add(StudentVerification(student_id=s.id, status=verification, basis="greeting_name")); db.commit()
    if with_notice:
        d = make_notification_draft(db, make_interview_event(db, make_email(db), student=s), email_status="approved")
        seq = NotificationSequence(draft_id=d.id, student_id=s.id, status="active", timezone="America/Chicago",
                                   started_at=datetime.utcnow(), ack_token=f"t{s.id}")
        db.add(seq); db.flush()
        db.add(NotificationAttempt(sequence_id=seq.id, channel="email", step="start", planned_for=datetime.utcnow(),
                                   scheduled_for=datetime.utcnow(), status="sent" if sent else "pending",
                                   sent_at=datetime.utcnow() if sent else None))
        db.commit()
    return s


def test_dry_run_changes_nothing_and_apply_rejects_only_pending_unlisted(db):
    from models import NotificationDraft, NotificationSequence, StudentVerification
    listed = _student(db, "listed", "Listed Person", "listed@x.com", "unverified")        # on the roster: untouched
    stray = _student(db, "stray", "Stray Person", "stray@x.com", "unverified")             # not listed, pending: rejected
    legacy = _student(db, "legacy", "Legacy Person", "legacy@x.com", None)                 # not listed, no verification row: left alone
    checked = _student(db, "checked", "Checked Person", "checked@x.com", "verified")       # not listed but verified: left alone
    told = _student(db, "told", "Told Person", "told@x.com", "unverified", sent=True)      # a notice already went out: skipped

    lines = []
    ru.run(db, ROSTER, apply=False, out=lines.append)
    db.expire_all()
    assert db.query(StudentVerification).filter_by(student_id=stray.id).one().status == "unverified"
    assert "would reject" in "\n".join(lines)

    out = ru.run(db, ROSTER, apply=True, by="Kes", out=lambda *_: None)
    db.expire_all()
    assert out["done"] == ["Stray Person"] and out["skipped"] == ["Told Person"]
    assert db.query(StudentVerification).filter_by(student_id=stray.id).one().status == "rejected"
    for who, status in ((listed, "unverified"), (checked, "verified"), (told, "unverified")):
        assert db.query(StudentVerification).filter_by(student_id=who.id).one().status == status
    assert db.query(StudentVerification).filter_by(student_id=legacy.id).first() is None
    stray_draft = db.query(NotificationDraft).filter(NotificationDraft.email_status == "rejected").all()
    assert len(stray_draft) == 1
    assert db.query(NotificationSequence).filter_by(student_id=stray.id).one().status == "closed"
    assert db.query(NotificationSequence).filter_by(student_id=listed.id).one().status == "active"
