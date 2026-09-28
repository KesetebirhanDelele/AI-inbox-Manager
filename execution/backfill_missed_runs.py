#!/usr/bin/env python3
"""
Backfill dashboard DB rows for pipeline runs whose DB writes failed.

Context (2026-09-24/25 incident, RUNBOOK.md §16): runs kept classifying and
moving mail in Gmail, but every DB write failed, so the dashboard lost both
the ``ProcessRun`` rows (which drive "Emails Today") and the per-email
``emails`` / ``classifications`` rows.

Sources of truth, both read-only:
  * GitHub Actions job logs (``gh run view <id> --log``) -- each run's summary
    totals and the per-email ``[category] (conf%) → folder — subject`` lines.
  * Gmail, opened with EXAMINE (read-only): cannot change flags or move mail.

What it writes:
  * one ``ProcessRun`` per log (skipped if that run_timestamp already exists)
  * ``emails`` + ``classifications`` rows for emails that were moved OUT of
    INBOX (skipped if the Message-ID already exists). Interview emails that
    were kept in INBOX are NOT touched -- they stay UNSEEN and the next
    healthy pipeline run imports them with full interview processing.

Emails quarantined to Spam Review and then purged by a later run no longer
exist in Gmail and are reported as unmatched.

Usage:
    # 1. save logs:  gh run view <id> --log > <dir>/<id>.log   (one per run)
    # 2. dry run (default, writes nothing):
    python execution/backfill_missed_runs.py --logs-dir <dir> --db-url-env NEON_DATABASE_URL
    # 3. apply:
    python execution/backfill_missed_runs.py --logs-dir <dir> --db-url-env NEON_DATABASE_URL --apply
"""

import argparse
import email as email_lib
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_EXECUTION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_EXECUTION_DIR))

INTERVIEW_CATEGORY_FALLBACK = "Interview Request"
# The log's run Timestamp is when the run started; its IMAP fetch happens a
# little later, so mail arriving just after the timestamp was still picked up.
_FETCH_SLACK = timedelta(minutes=2)

# "<GH prefix> 2026-09-25 16:13:37,308 - __main__ - INFO - <msg>"
_MSG = re.compile(
    r"(?P<d>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} - (?:__main__|classify_email)"
    r" - (?:INFO|WARNING|ERROR) - (?P<msg>.*)$"
)
_ORGANIZED = re.compile(
    r"^\[\d+/\d+\] \[(?P<cat>[^\]]+)\] \((?P<conf>\d+)%\) → (?P<folder>.+?) — (?P<subj>.*)$"
)
_SPAM = re.compile(r"^\[\d+/\d+\] \[POSSIBLE SPAM → (?P<folder>[^\]]+)\] - (?P<subj>.*)$")
_INTERVIEW = re.compile(
    r"^\[\d+/\d+\] \*\* (?:INTERVIEW REQUEST|SAFETY PROTECTED) \((?:NEW|ALREADY)[^)]*\) \*\* - (?P<subj>.*)$"
)
_ALREADY = re.compile(r"^\[\d+/\d+\] \[ALREADY PROCESSED\] - ")
_CAT_LINE = re.compile(r"^\s+Category: (?P<cat>.+?) \(confidence")


# ── Pure parsing ─────────────────────────────────────────────────────────────

def parse_run_log(text: str) -> Dict[str, Any]:
    """Parse one run's GH Actions log into ProcessRun stats + per-email entries.

    ``entries`` holds only emails moved out of INBOX:
    ``{"category", "confidence", "folder", "subject60"}``.
    """
    result: Dict[str, Any] = {
        "timestamp": None, "total_emails": 0, "interview_requests": 0,
        "organized": 0, "spam_deleted": 0, "categories": {},
        "duration_seconds": 0.0, "gpt_cost_usd": 0.0, "entries": [],
        "interview_subjects": [],
    }
    start = end = None
    pending_interview = False

    for raw in text.splitlines():
        m = _MSG.search(raw)
        if not m:
            continue
        msg = m.group("msg")
        line_time = datetime.strptime(m.group("d"), "%Y-%m-%d %H:%M:%S")

        # An interview line may be followed by an indented "Category:" line.
        if pending_interview:
            cat_m = _CAT_LINE.match(msg)
            if cat_m:
                _bump(result["categories"], cat_m.group("cat"))
                pending_interview = False
                continue
            if msg.startswith("  "):
                continue  # Company: / [KEPT IN INBOX ...] detail lines
            _bump(result["categories"], INTERVIEW_CATEGORY_FALLBACK)
            pending_interview = False

        if msg.startswith("Timestamp: "):
            result["timestamp"] = msg.split(": ", 1)[1].strip()
            start = line_time
        elif msg.startswith("Total Processed: "):
            result["total_emails"] = int(msg.rsplit(" ", 1)[1])
        elif msg.startswith("Interview Requests (kept in inbox): "):
            result["interview_requests"] = int(msg.rsplit(" ", 1)[1])
        elif msg.startswith("Organized to folders: "):
            result["organized"] = int(msg.rsplit(" ", 1)[1])
        elif msg.startswith("Quarantined to Spam Review: "):
            result["spam_deleted"] = int(msg.rsplit(" ", 1)[1])
        elif msg.startswith("GPT usage: ") and "estimated cost: $" in msg:
            result["gpt_cost_usd"] = float(msg.rsplit("$", 1)[1])
        elif msg.startswith("Summary saved to: "):
            end = line_time
        elif (om := _ORGANIZED.match(msg)):
            cat = om.group("cat")
            _bump(result["categories"], cat)
            result["entries"].append({
                "category": cat,
                "confidence": int(om.group("conf")) / 100.0,
                "folder": om.group("folder"),
                "subject60": om.group("subj"),
            })
        elif (sm := _SPAM.match(msg)):
            result["entries"].append({
                "category": "Other", "confidence": 0.0,
                "folder": sm.group("folder"), "subject60": sm.group("subj"),
            })
        elif (im := _INTERVIEW.match(msg)):
            result["interview_subjects"].append(im.group("subj"))
            pending_interview = True
        elif _ALREADY.match(msg):
            pending_interview = True

    if pending_interview:
        _bump(result["categories"], INTERVIEW_CATEGORY_FALLBACK)
    if start and end:
        result["duration_seconds"] = (end - start).total_seconds()
    return result


def _bump(d: Dict[str, int], key: str) -> None:
    d[key] = d.get(key, 0) + 1


def run_datetime(timestamp: str) -> datetime:
    return datetime.strptime(timestamp, "%Y%m%d_%H%M%S")


# ── Gmail (read-only) ────────────────────────────────────────────────────────

def _decode_subject(raw_header: bytes) -> str:
    from fetch_emails import decode_email_header
    msg = email_lib.message_from_bytes(raw_header)
    return decode_email_header(msg.get("Subject", "") or "")


def pick_candidate(
    candidates: List[Dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    known_message_ids: set,
    used_uids: set,
) -> Optional[Dict[str, Any]]:
    """Choose the Gmail message a log entry refers to.

    Subjects repeat (daily job alerts), so a subject match alone can land on
    an older, already-imported email or on mail the pipeline never handled.
    A candidate must have *arrived* (INTERNALDATE, naive UTC) after the
    previous run and no later than this run, and not already be in the DB or
    claimed by another entry. Newest first, mirroring the pipeline's fetch.
    """
    for c in sorted(candidates, key=lambda c: c["arrived"], reverse=True):
        if c["uid"] in used_uids or (c["message_id"] and c["message_id"] in known_message_ids):
            continue
        if window_start < c["arrived"] <= window_end:
            return c
    return None


def index_folder(imap, folder: str, since: datetime) -> Dict[str, List[Dict[str, Any]]]:
    """Map subject[:60] → [{uid, arrived, message_id}, ...] for ``folder`` since ``since``."""
    import imaplib
    import time
    from fetch_emails import select_folder  # opens read-only (EXAMINE)
    try:
        select_folder(imap, folder)
    except Exception as e:
        print(f"  ! cannot open folder {folder!r}: {e}")
        return {}
    status, data = imap.uid("SEARCH", None, f'SINCE {since.strftime("%d-%b-%Y")}')
    uids = data[0].split() if status == "OK" and data and data[0] else []
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for i in range(0, len(uids), 200):
        chunk = b",".join(uids[i:i + 200]).decode()
        status, rows = imap.uid(
            "FETCH", chunk, "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT MESSAGE-ID)])"
        )
        if status != "OK":
            continue
        for row in rows:
            if not isinstance(row, tuple):
                continue
            uid_m = re.search(rb"UID (\d+)", row[0])
            tt = imaplib.Internaldate2tuple(row[0])
            if not uid_m or not tt:
                continue
            headers = email_lib.message_from_bytes(row[1])
            index[_decode_subject(row[1])[:60]].append({
                "uid": uid_m.group(1).decode(),
                "arrived": datetime.utcfromtimestamp(time.mktime(tt)),
                "message_id": (headers.get("Message-ID") or "").strip(),
            })
    return index


def fetch_full(imap, uid: str) -> Optional[Dict[str, Any]]:
    from fetch_emails import parse_email_message
    status, rows = imap.uid("FETCH", uid, "(BODY.PEEK[])")
    if status != "OK":
        return None
    for row in rows:
        if isinstance(row, tuple):
            return parse_email_message(row[1], uid)
    return None


# ── Interview emails the failed runs never recorded ─────────────────────────

def folder_from_labels(fetch_header: str) -> str:
    """Current Gmail location from an ``X-GM-LABELS (...)`` FETCH response."""
    m = re.search(r"X-GM-LABELS \((.*?)\)", fetch_header)
    # Labels are quoted ("Needs Review", "\\Inbox") or bare atoms (\Important).
    tokens = re.findall(r'"([^"]*)"|(\S+)', m.group(1)) if m else []
    names = [(q or a).replace("\\\\", "\\") for q, a in tokens]
    if any(n.lower() == "\\inbox" for n in names):
        return "INBOX"
    user = [n for n in names if not n.startswith("\\")]
    return user[0] if user else "Archive"


def subject_search_words(subject: str, n: int = 3) -> str:
    """First ``n`` plain words of a subject, for Gmail's IMAP SUBJECT search."""
    return " ".join(re.findall(r"[A-Za-z0-9]+", subject)[:n])


def same_subject(full_subject: str, logged60: str) -> bool:
    """True if ``full_subject`` is the email the log printed (first 60 chars)."""
    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    return norm(full_subject[:60]) == norm(logged60)


def backfill_interviews(pia, db, runs, apply: bool) -> Dict[str, int]:
    """Record interview emails the failed runs kept in INBOX but never saved.

    Healthy runs pick these up automatically while they stay UNSEEN in INBOX;
    this covers the ones someone opened or moved in the meantime, so it
    searches All Mail by subject. Each candidate not already in the DB is
    re-classified (the interview pipeline needs extracted fields the logs
    don't carry); only genuine interview requests then go through the
    pipeline's own import_email_to_db() + process_interview_email().
    Dry run lists candidates without GPT calls.
    """
    import imaplib
    import time
    from fetch_emails import connect_to_imap
    from models import Email

    subjects = list(dict.fromkeys(s.strip() for _, p in runs for s in p["interview_subjects"]))
    since = min(run_datetime(p["timestamp"]) for _, p in runs) - timedelta(days=2)
    print(f"  {len(subjects)} distinct interview subjects; All Mail since {since:%d-%b}")

    counts: Dict[str, int] = defaultdict(int)
    seen_uids: set = set()
    imap = connect_to_imap(os.getenv("EMAIL_SERVER"), int(os.getenv("EMAIL_PORT", "993")),
                           os.getenv("EMAIL_ADDRESS"), os.getenv("EMAIL_PASSWORD"))
    try:
        # Read-only (EXAMINE): cannot change flags or labels.
        imap.select('"[Gmail]/All Mail"', readonly=True)
        for subj in subjects:
            # Gmail's SUBJECT search silently returns nothing for queries with
            # "&" or "–", so search on the first plain words and then require
            # an exact subject-prefix match on what comes back.
            imap.literal = subject_search_words(subj).encode("utf-8")
            status, data = imap.uid("SEARCH", "CHARSET", "UTF-8",
                                    "SINCE", since.strftime("%d-%b-%Y"), "SUBJECT")
            uids = data[0].split() if status == "OK" and data and data[0] else []
            for uid_b in uids:
                uid = uid_b.decode()
                if uid in seen_uids:
                    continue
                status, rows = imap.uid(
                    "FETCH", uid,
                    "(X-GM-LABELS INTERNALDATE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT)])")
                row = next((r for r in rows if isinstance(r, tuple)), None)
                if status != "OK" or row is None:
                    counts["fetch_failed"] += 1
                    continue
                if not same_subject(_decode_subject(row[1]), subj):
                    continue
                seen_uids.add(uid)
                header = row[0].decode(errors="replace")
                mid = (email_lib.message_from_bytes(row[1]).get("Message-ID") or "").strip()
                if mid and db.query(Email).filter(Email.message_id == mid).first():
                    counts["already_in_db"] += 1
                    continue
                folder = folder_from_labels(header)
                tt = imaplib.Internaldate2tuple(row[0])
                arrived = datetime.utcfromtimestamp(time.mktime(tt)) if tt else datetime.utcnow()
                if not apply:
                    print(f"    would check: {subj[:55]}  [{folder}, arrived {arrived:%m-%d %H:%M} UTC]")
                    counts["would_check"] += 1
                    continue
                data = fetch_full(imap, uid)
                if not data:
                    counts["fetch_failed"] += 1
                    continue
                cls = pia.classify_email(data, validate_only=False)
                if not (pia.is_genuine_interview_request(cls) or pia.is_from_known_company(data, cls)):
                    print(f"    skip (re-classified as {cls.get('category')}): {subj[:55]}")
                    counts["not_interview"] += 1
                    continue
                email_db_id = pia.import_email_to_db(data, cls, folder)
                if email_db_id is None:
                    counts["import_failed"] += 1
                    continue
                # Attribute to when it arrived, not to the moment of the backfill.
                db.get(Email, email_db_id).fetch_timestamp = arrived
                db.commit()
                ok = pia.process_interview_email(data, email_db_id, cls)
                company = (cls.get("extracted_data") or {}).get("company_name")
                print(f"    {'event created' if ok else 'EVENT FAILED'}: [{cls.get('category')}] "
                      f"{company} — {subj[:55]}  [{folder}]")
                counts["event_created" if ok else "event_failed"] += 1
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return counts


# ── Orchestration of one backfill ────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--logs-dir", required=True, type=Path)
    ap.add_argument("--db-url-env", required=True,
                    help="Name of the env var (from .env) holding the target DB URL, e.g. NEON_DATABASE_URL")
    ap.add_argument("--apply", action="store_true", help="Write to the DB (default: dry run)")
    ap.add_argument("--skip-emails", action="store_true", help="Only backfill ProcessRun rows")
    ap.add_argument("--interviews", action="store_true",
                    help="Only backfill interview emails still in INBOX (re-classifies with GPT on --apply)")
    args = ap.parse_args()
    # Subjects contain emoji/arrows; Windows consoles default to cp1252.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from dotenv import load_dotenv
    load_dotenv(_EXECUTION_DIR.parent / ".env")
    db_url = os.getenv(args.db_url_env)
    if not db_url:
        print(f"ERROR: {args.db_url_env} is not set")
        return 1
    # process_inbox_auto's importer reads DATABASE_URL; point it at the target.
    os.environ["DATABASE_URL"] = db_url

    import process_inbox_auto as pia
    from models import Email, ProcessRun

    runs = []
    for log_file in sorted(args.logs_dir.glob("*.log")):
        parsed = parse_run_log(log_file.read_text(encoding="utf-8", errors="replace"))
        if not parsed["timestamp"]:
            print(f"  ! {log_file.name}: no Timestamp line, skipped")
            continue
        runs.append((log_file.stem, parsed))
    runs.sort(key=lambda r: r[1]["timestamp"])
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'} | target env var: {args.db_url_env} | runs: {len(runs)}")

    db = pia.get_db_session()
    if db is None:
        print(f"ERROR: could not open DB: {pia._db_error}")
        return 1

    if args.interviews:
        try:
            counts = backfill_interviews(pia, db, runs, args.apply)
        finally:
            pia.close_db_session()
        print(f"Done. interviews: {dict(counts)}")
        return 0

    # ── ProcessRun rows ──────────────────────────────────────────────────────
    runs_added = 0
    for run_id, p in runs:
        ts = run_datetime(p["timestamp"])
        exists = db.query(ProcessRun).filter(ProcessRun.run_timestamp == ts).first()
        tag = "exists, skip" if exists else ("insert" if args.apply else "would insert")
        print(f"  run {run_id} @ {ts} total={p['total_emails']} interview={p['interview_requests']} "
              f"organized={p['organized']} spam={p['spam_deleted']} moved-entries={len(p['entries'])} → {tag}")
        if exists or not args.apply:
            continue
        db.add(ProcessRun(
            run_timestamp=ts, total_emails=p["total_emails"],
            interview_requests=p["interview_requests"], organized=p["organized"],
            spam_deleted=p["spam_deleted"], categories_breakdown=p["categories"],
            duration_seconds=p["duration_seconds"], gpt_cost_usd=p["gpt_cost_usd"],
            status="success",
        ))
        db.commit()
        runs_added += 1

    if args.skip_emails:
        print(f"Done. ProcessRun inserted: {runs_added}")
        return 0

    # ── Email rows (moved-out-of-INBOX mail only) ────────────────────────────
    # Each run processed mail that arrived after the previous run started.
    # The first missed run's predecessor is the last ProcessRun already in the DB.
    first_run = min((run_datetime(p["timestamp"]) for _, p in runs), default=datetime.utcnow())
    prev_in_db = (db.query(ProcessRun.run_timestamp)
                  .filter(ProcessRun.run_timestamp < first_run)
                  .order_by(ProcessRun.run_timestamp.desc()).first())
    prev_ts = prev_in_db[0] if prev_in_db else first_run - timedelta(hours=3)
    print(f"  matching mail that arrived after last recorded run: {prev_ts}")
    by_folder: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for run_id, p in runs:
        run_ts = run_datetime(p["timestamp"])
        for e in p["entries"]:
            by_folder[e["folder"]].append({
                **e, "run_id": run_id, "run_ts": run_ts,
                "window": (prev_ts, run_ts + _FETCH_SLACK),
            })
        prev_ts = run_ts
    # IMAP SINCE is date-granular; one day back covers the first window.
    since = first_run - timedelta(days=1)
    known_mids = {mid for (mid,) in db.query(Email.message_id)
                  .filter(Email.fetch_timestamp >= since - timedelta(days=1)) if mid}
    used_uids: set = set()

    from fetch_emails import connect_to_imap
    imap = connect_to_imap(os.getenv("EMAIL_SERVER"), int(os.getenv("EMAIL_PORT", "993")),
                           os.getenv("EMAIL_ADDRESS"), os.getenv("EMAIL_PASSWORD"))
    counts = defaultdict(int)
    try:
        for folder, entries in sorted(by_folder.items()):
            index = index_folder(imap, folder, since)
            print(f"  folder {folder!r}: {len(entries)} logged, {sum(map(len, index.values()))} in Gmail since {since:%d-%b}")
            for e in entries:
                cand = pick_candidate(index.get(e["subject60"]) or [], *e["window"],
                                      known_mids, used_uids)
                if cand is None:
                    counts["unmatched"] += 1
                    if folder != "Spam Review":
                        print(f"    ? no match in arrival window: {e['subject60']}")
                    continue
                used_uids.add(cand["uid"])
                if cand["message_id"]:
                    known_mids.add(cand["message_id"])
                if not args.apply:
                    counts["would_insert"] += 1
                    continue
                data = fetch_full(imap, cand["uid"])
                if not data:
                    counts["fetch_failed"] += 1
                    continue
                if not args.apply:
                    counts["would_insert"] += 1
                    continue
                classification = {
                    "category": e["category"], "confidence": e["confidence"],
                    "extracted_data": {},
                    "backfill": {"source": "gh-actions-log", "run_id": e["run_id"]},
                }
                email_db_id = pia.import_email_to_db(data, classification, folder)
                if email_db_id is None:
                    counts["insert_failed"] += 1
                    continue
                # Stamp the original run time, not "now", so today/week stats
                # attribute the email to the run that actually processed it.
                row = db.get(Email, email_db_id)
                row.fetch_timestamp = e["run_ts"]
                db.commit()
                counts["inserted"] += 1
    finally:
        try:
            imap.logout()
        except Exception:
            pass
        pia.close_db_session()

    print(f"Done. ProcessRun inserted: {runs_added} | emails: {dict(counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
