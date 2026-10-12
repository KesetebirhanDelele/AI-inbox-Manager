"""
Rewrite the email of every notification draft that has not been sent into the audit-safe wording (one-off, safe to rerun).

Older drafts carry the template wording, which names the job title in the body (a flagged word on the audit's list). At send time the app
already builds the audit-safe email for such a draft (notify_channels.email_parts), so nothing flagged can go out; this script makes the
approval card show the SAME text the student will receive. Only drafts whose status is draft or approved, with no follow-up sequence that
has already sent anything, and whose body is not already audit-safe ("[Interview Notification]" first line, no flagged word, no link), are touched. Dry run by default.

Usage (inside the cron container on the server):
    python execution/rewrite_pending_drafts.py            # list only
    python execution/rewrite_pending_drafts.py --apply
"""
import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def plan(db):
    """(draft, subject, body) for each draft that needs the new wording."""
    import models as M
    import content_audit as audit
    import notification_messages as nm

    out = []
    for draft in db.query(M.NotificationDraft).filter(M.NotificationDraft.email_status.in_(["draft", "approved"])).all():
        first = next((ln.strip() for ln in (draft.email_body or "").splitlines() if ln.strip()), "")
        if first == audit.REQUIRED_START and audit.email_problem(draft.email_body or "") is None:
            continue                                       # already the audit-safe wording (no flagged word, no link)
        seq = db.query(M.NotificationSequence).filter(M.NotificationSequence.draft_id == draft.id).first()
        if seq is not None and any(a.sent_at for a in seq.attempts):
            continue                                       # something already went out under the old wording: leave the record as it was
        event = db.get(M.InterviewEvent, draft.interview_event_id)
        student = db.get(M.Student, event.student_id) if event is not None and event.student_id else None
        facts = nm.facts_from_event(event, student)
        out.append((draft, nm.email_subject(facts), nm.email_body(facts)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the new wording to the drafts (default: list only)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        print("No database connection.")
        return 1
    import content_audit as audit
    items = plan(db)
    for draft, subject, body in items:
        verdict = audit.email_problem(body) or "clean"
        print(f"draft {draft.id} [{draft.email_status}]: '{(draft.email_subject or '')[:40]}' -> '{subject}' | audit: {verdict}")
    print(f"{len(items)} draft(s) need the new wording")
    if not args.apply or not items:
        print("List only: nothing changed." if not args.apply else "Nothing to do.")
        return 0
    for draft, subject, body in items:
        draft.email_subject, draft.email_body = subject, body
    db.commit()
    print(f"rewrote {len(items)} draft(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
