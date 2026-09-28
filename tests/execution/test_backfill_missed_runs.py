"""
Unit tests for execution/backfill_missed_runs.parse_run_log().

The backfill rebuilds ProcessRun rows from GitHub Actions job logs after the
2026-09-24 SQLAlchemy 2.1 incident, so the parser must reproduce exactly the
totals the pipeline itself printed. Pure parsing -- no I/O.
"""

import sys
from pathlib import Path

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

from backfill_missed_runs import parse_run_log, run_datetime  # noqa: E402

_P = "process\tRun inbox processing\t2026-09-25T16:13:37.3128439Z "


def _line(t: str, msg: str, logger: str = "__main__", level: str = "INFO") -> str:
    return f"{_P}2026-09-25 {t},308 - {logger} - {level} - {msg}"


SAMPLE_LOG = "\n".join([
    _line("16:13:37", "Timestamp: 20260925_161337"),
    _line("16:14:12", "GPT usage: 5 calls | 1,000 input tokens | 10 output tokens | estimated cost: $0.1234"),
    _line("16:14:12", "[1/5] [Job Alert] (95%) → Job Alerts — Job Openings: New roles you’ll love!"),
    _line("16:14:12", "[2/5] [POSSIBLE SPAM → Spam Review] - Ready for the Self Card?"),
    _line("16:14:12", "[3/5] ** INTERVIEW REQUEST (NEW) ** - Remote: Data Engineer"),
    _line("16:14:12", "              Company: InstantServe LLC"),
    _line("16:14:12", "              [KEPT IN INBOX - NEEDS REVIEW]"),
    _line("16:14:12", "[4/5] ** SAFETY PROTECTED (NEW) ** - Power BI Developer"),
    _line("16:14:12", "              Company: Excelon"),
    _line("16:14:12", "              Category: Phone Screen (confidence: 88%)"),
    _line("16:14:12", "[5/5] [Rejection] (62%) → Needs Review — Update on your application"),
    _line("16:14:12", "Could not initialize database: No module named 'psycopg'", level="WARNING"),
    _line("16:15:14", "Total Processed: 5"),
    _line("16:15:14", "Interview Requests (kept in inbox): 2"),
    _line("16:15:14", "Organized to folders: 2"),
    _line("16:15:14", "Quarantined to Spam Review: 1"),
    _line("16:15:14", "Summary saved to: tmp/auto_process_20260925_161337/summary.json"),
    "process\tSet up job\t2026-09-25T16:13:15Z unrelated runner noise",
])


def test_summary_totals():
    p = parse_run_log(SAMPLE_LOG)
    assert p["timestamp"] == "20260925_161337"
    assert (p["total_emails"], p["interview_requests"], p["organized"], p["spam_deleted"]) == (5, 2, 2, 1)
    assert p["gpt_cost_usd"] == 0.1234
    assert p["duration_seconds"] == 97.0


def test_moved_entries_exclude_inbox_interviews():
    entries = parse_run_log(SAMPLE_LOG)["entries"]
    assert entries == [
        {"category": "Job Alert", "confidence": 0.95, "folder": "Job Alerts",
         "subject60": "Job Openings: New roles you’ll love!"},
        {"category": "Other", "confidence": 0.0, "folder": "Spam Review",
         "subject60": "Ready for the Self Card?"},
        {"category": "Rejection", "confidence": 0.62, "folder": "Needs Review",
         "subject60": "Update on your application"},
    ]


def test_interview_subjects_recorded():
    assert parse_run_log(SAMPLE_LOG)["interview_subjects"] == [
        "Remote: Data Engineer", "Power BI Developer",
    ]


def test_categories_breakdown_matches_pipeline_counting():
    # Pipeline counts interview + organized emails (not spam) in categories.
    cats = parse_run_log(SAMPLE_LOG)["categories"]
    assert cats == {"Job Alert": 1, "Interview Request": 1, "Phone Screen": 1, "Rejection": 1}


def test_log_without_timestamp_yields_none():
    assert parse_run_log("nothing useful here")["timestamp"] is None


def test_run_datetime():
    assert run_datetime("20260925_161337").isoformat() == "2026-09-25T16:13:37"


# ── pick_candidate ───────────────────────────────────────────────────────────

from datetime import datetime  # noqa: E402

from backfill_missed_runs import pick_candidate  # noqa: E402

_W = (datetime(2026, 9, 25, 14, 12), datetime(2026, 9, 25, 16, 15))


def _c(uid, hh, mm, mid=None):
    return {"uid": uid, "arrived": datetime(2026, 9, 25, hh, mm), "message_id": mid or f"<{uid}@x>"}


def test_pick_candidate_ignores_mail_outside_arrival_window():
    # Same daily subject: yesterday's copy must not be picked.
    cands = [_c("1", 9, 0), _c("2", 15, 30)]
    assert pick_candidate(cands, *_W, set(), set())["uid"] == "2"


def test_pick_candidate_skips_known_message_ids_and_used_uids():
    cands = [_c("1", 15, 0), _c("2", 15, 30), _c("3", 16, 0)]
    assert pick_candidate(cands, *_W, {"<3@x>"}, {"2"})["uid"] == "1"


def test_pick_candidate_none_when_nothing_eligible():
    assert pick_candidate([_c("1", 9, 0)], *_W, set(), set()) is None


# ── folder_from_labels ───────────────────────────────────────────────────────

from backfill_missed_runs import folder_from_labels  # noqa: E402


def test_folder_from_labels():
    assert folder_from_labels(r'1 (UID 5 X-GM-LABELS ("\Inbox" "Job Alerts") FLAGS ()') == "INBOX"
    assert folder_from_labels(r'1 (X-GM-LABELS (\Important "Instant Interview") INTERNALDATE') == "Instant Interview"
    assert folder_from_labels('1 (X-GM-LABELS () FLAGS ()') == "Archive"


from backfill_missed_runs import same_subject, subject_search_words  # noqa: E402


def test_subject_search_words_drops_symbols_gmail_cannot_search():
    assert subject_search_words("Remote: Data Engineer – U.S. Mortgage & Snowflake") == "Remote Data Engineer"


def test_same_subject_matches_log_truncation_and_whitespace():
    full = "REMOTE|| AMI DATA ANALYST|| REMOTE|| IMMEDIATE INTERVIEW || only W2"
    assert same_subject(full, full[:60].rstrip())
    assert not same_subject("Great Opportunity || AMI Data Analyst || Remote", full[:60])
