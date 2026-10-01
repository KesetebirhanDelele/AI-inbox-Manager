"""Pure-logic tests for backfill_sub_types (no database, no OpenAI)."""
import sys
from pathlib import Path

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import backfill_sub_types as bf  # noqa: E402


def test_needs_backfill_only_for_interview_categories_not_yet_relabelled():
    assert bf.needs_backfill({}, "Interview Request") is True
    assert bf.needs_backfill(None, "Phone Screen") is True
    assert bf.needs_backfill({"sub_type_source": "subclassifier"}, "Interview Request") is False
    assert bf.needs_backfill({}, "Job Invite") is False
    assert bf.needs_backfill({}, None) is False


def test_relabel_keeps_audit_trail_and_does_not_wipe_fields_with_none():
    raw = {"company_name": "Acme", "interview_date": "2026-10-05"}
    out = bf.relabel(raw, "interview_request",
                     {"interview_sub_type": "Phone Screen", "company_name": None, "confidence": 0.9})
    assert out["previous_sub_type"] == "interview_request"
    assert out["sub_type_source"] == "subclassifier"
    assert out["interview_sub_type"] == "Phone Screen"
    assert out["company_name"] == "Acme" and out["interview_date"] == "2026-10-05"
    assert "previous_sub_type" not in raw          # input is not mutated
