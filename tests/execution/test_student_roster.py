"""student_roster: parsing, matching and comparison. Pure logic and a fake sheet session; no network, no real student data."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import student_roster as sr  # noqa: E402

HEADER = ["Agent", "Name", "STATUS", "New Email Address", "Personal Email Address"]
VALUES = [
    HEADER,
    ["Vivek", "Ann Example", "Active", "ann.new@x.com", "Ann.Old@x.com"],
    ["Vivek", "Bo Sample", "In Progress", "", "bo@x.com"],
    ["Karthik", "Cy Placed", "Placed", "cy@x.com", ""],
    ["Karthik", "", "Active", "ghost@x.com", ""],
    ["Karthik", "Di Roster", "active", "di@x.com, di2@x.com", ""],
]


def test_parse_is_header_driven_and_skips_nameless_rows():
    rows = sr.parse_rows(VALUES)
    assert [r.name for r in rows] == ["Ann Example", "Bo Sample", "Cy Placed", "Di Roster"]
    assert rows[0].emails == ["ann.new@x.com", "ann.old@x.com"]          # both email columns, lower-cased
    assert rows[3].emails == ["di@x.com", "di2@x.com"]                    # two addresses in one cell
    assert [r.active for r in rows] == [True, True, False, True]


def test_parse_survives_moved_columns_and_fails_loudly_when_one_is_missing():
    moved = [["STATUS", "Personal Email Address", "Name"], ["Active", "a@x.com", "Zed"]]
    assert sr.parse_rows(moved)[0].emails == ["a@x.com"]
    with pytest.raises(ValueError):
        sr.parse_rows([["Name", "STATUS"], ["Zed", "Active"]])


def student(i, name, email="", gmail=""):
    return {"id": i, "full_name": name, "personal_email": email, "assigned_gmail": gmail}


def test_matching_prefers_email_then_name_and_otherwise_none():
    roster = sr.parse_rows(VALUES)
    assert sr.match_student(student(1, "A. Example", "ANN.OLD@x.com"), roster).how == "email"
    assert sr.match_student(student(2, "bo  sample", "other@x.com"), roster).how == "name"
    assert sr.match_student(student(3, "Nobody Here", "n@x.com"), roster).how == "none"
    assert sr.match_student(student(4, "Bo"), roster).how == "name"      # one-word name that is a first word
    assert sr.match_student(student(5, "Ann Other"), roster).how == "none"   # one shared word is not enough between two-word names


def test_compare_lists_everything_and_changes_nothing():
    roster = sr.parse_rows(VALUES)
    students = [student(1, "Ann Example", "ann.new@x.com"), student(2, "Bo Sample", "diff@x.com"), student(3, "Stranger Danger", "s@x.com")]
    res = sr.compare(students, roster)
    assert [m.student_id for m in res["by_email"]] == [1]
    assert [m.student_id for m in res["by_name_only"]] == [2]
    assert [m.student_id for m in res["not_on_roster"]] == [3]
    assert [r.name for r in res["roster_without_student"]] == ["Di Roster"]      # only active rows
    assert "bo@x.com" in res["roster_emails_unknown_to_us"] and "cy@x.com" not in res["roster_emails_unknown_to_us"]


class FakeSession:
    def __init__(self, status=200, values=None):
        self.status, self.values, self.url = status, values or [], None

    def get(self, url, timeout=None):
        self.url = url
        outer = self

        class R:
            status_code = outer.status

            def json(self):
                return {"values": outer.values}
        return R()


def test_fetch_reads_the_roster_tab_and_explains_a_refusal():
    s = FakeSession(values=VALUES)
    assert len(sr.fetch_roster("SHEET1", session=s)) == 4 and s.url.endswith("/SHEET1/values/roster")
    with pytest.raises(RuntimeError, match="Viewer"):
        sr.fetch_roster("SHEET1", session=FakeSession(status=403))
    with pytest.raises(RuntimeError, match="not set"):
        sr.fetch_roster("", session=FakeSession())


def test_masking_hides_the_address_but_keeps_the_domain():
    assert sr.mask_email("kwadjossan@gmail.com") == "kw***@gmail.com"


def test_the_report_runs_against_a_database_and_masks_emails(monkeypatch):
    api_dir = _EXECUTION_DIR.parents[0] / "services" / "dashboard" / "api"
    monkeypatch.syspath_prepend(str(api_dir))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models
    import student_roster_check as chk

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(models.Student(username="ann", full_name="Ann Example", personal_email="ann.new@x.com", is_active=True))
    db.add(models.Student(username="stranger", full_name="Stranger Danger", personal_email="s@x.com", is_active=True))
    db.commit()
    lines = []
    assert chk.run(db, sr.parse_rows(VALUES), 30, out=lines.append) == 0
    text = "\n".join(lines)
    assert "MATCHED BY EMAIL (1)" in text and "NOT ON THE ROSTER (1)" in text and "Stranger Danger" in text
    assert "ann.new@x.com" not in text and "ann.old@x.com" not in text         # never printed in full
