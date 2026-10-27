"""
Replay the third interview screen over interview mail that already went through the pipeline, so a person can judge it (shadow mode).

For every past interview event (newest first) it runs interview_gate.assess on the email as it was, seeing only mail OLDER than that email as history,
and saves the verdict in interview_gate_reviews (source 'replay'). It never touches events, notices, Gmail or students, and never overwrites a person's
decision. The Review > "Gate review" page then lists them for Kes to mark real / not real.

Usage (inside the cron container; calls the model, about $0.0005 per email):
  python execution/interview_gate_replay.py                  # dry run: lists what it would replay and the estimated cost
  python execution/interview_gate_replay.py --apply [--limit 100] [--since 2026-10-01]
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "execution", ROOT, ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

EST_COST_PER_EMAIL_USD = 0.0005


def candidates(db, since=None, limit=100, include_done=False):
    """(event, email) pairs not yet replayed, newest first. Duplicate events of one email count once."""
    from models import Email, InterviewEvent, InterviewGateReview
    query = db.query(InterviewEvent, Email).join(Email, Email.id == InterviewEvent.email_id).order_by(Email.received_date.desc(), InterviewEvent.id)
    if since:
        query = query.filter(Email.received_date >= since)
    done = set() if include_done else {r[0] for r in db.query(InterviewGateReview.email_id).all()}
    seen, out = set(), []
    for event, email in query.all():
        if email.id in seen or email.id in done:
            continue
        seen.add(email.id)
        out.append((event, email))
        if len(out) >= limit:
            break
    return out


def replay(db, pairs, assess=None, apply=True):
    """Runs the gate on each pair; returns [(email, out)]. Saves rows when `apply`."""
    import interview_gate
    assess = assess or interview_gate.assess
    results = []
    for event, email in pairs:
        out = assess(db, email.subject, email.from_address, email.full_body or email.body_preview or "",
                     received=email.received_date, exclude_email_id=email.id, company=event.company_name, student_id=event.student_id,
                     interview_date=event.interview_date, interview_time=event.interview_time)
        results.append((email, out))
        if apply:
            interview_gate.record_review(db, out, email.id, event.id, mode=interview_gate.gate_mode(), source="replay")
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replay the interview gate over past interview mail for human review.")
    ap.add_argument("--apply", action="store_true", help="call the model and save the verdicts (default: list only)")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--since", help="only mail received on/after this date (YYYY-MM-DD)")
    args = ap.parse_args(argv)
    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        print("No database connection.")
        return 1
    since = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
    pairs = candidates(db, since=since, limit=args.limit)
    print(f"{len(pairs)} past interview email(s) to replay (estimated cost ${len(pairs) * EST_COST_PER_EMAIL_USD:.3f}).")
    if not args.apply:
        for event, email in pairs[:20]:
            print(f"  event {event.id}  {email.received_date:%Y-%m-%d}  {(email.subject or '')[:70]}")
        print("List only: nothing called, nothing saved. Add --apply to run it.")
        return 0
    results = replay(db, pairs)
    tally = {}
    for _, out in results:
        key = (out["result"] or {}).get("verdict") or "error"
        tally[key] = tally.get(key, 0) + 1
    print("Done. Verdicts:", ", ".join(f"{k}={v}" for k, v in sorted(tally.items())), f"| cost ${sum(o['cost_usd'] for _, o in results):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
