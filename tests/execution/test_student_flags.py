"""student_flags and the roster helpers: wording, caching, fail-soft behaviour, and GHL lookup by the roster's emails. No network."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import notify_channels as nc  # noqa: E402
import student_flags as sf  # noqa: E402
import student_roster as sr  # noqa: E402

ROWS = sr.parse_rows([["Name", "STATUS", "New Email Address", "Personal Email Address"]] + [
    [f"{n} Surname", "Active", f"app{i}@x.com", f"pers{i}@x.com"] for i, n in enumerate(["Ada", "Bea", "Cyd", "Dov", "Eli", "Fay"])])


def test_warning_words_cover_each_case_and_stay_quiet_when_all_is_well():
    assert sf.warnings_for("listed", "found") == []
    assert sf.warnings_for("unknown", "unknown") == []
    both = sf.warnings_for("unlisted", "not_found")
    assert both[0].startswith("NOT ON THE ROSTER") and both[1].startswith("NOT IN GHL")
    assert sf.warnings_for("name_only", "found")[0].startswith("On the roster by NAME only")
    assert sf.warnings_for("listed", "check")[0].startswith("GHL lookup needs a person")


def test_the_roster_is_cached_fails_soft_and_ignores_a_near_empty_sheet():
    sr._CACHE.update(at=0.0, rows=None)
    calls = []

    def good():
        calls.append(1)
        return ROWS
    t = [1000.0]
    assert sr.cached_roster(fetch=good, clock=lambda: t[0]) == ROWS
    t[0] += 60
    assert sr.cached_roster(fetch=good, clock=lambda: t[0]) == ROWS and len(calls) == 1          # cached
    t[0] += 3600

    def down():
        raise RuntimeError("sheet down")
    assert sr.cached_roster(fetch=down, clock=lambda: t[0]) == ROWS                               # last good copy kept
    sr._CACHE.update(at=0.0, rows=None)
    assert sr.cached_roster(fetch=down, clock=lambda: 5.0) is None
    assert sr.cached_roster(fetch=lambda: ROWS[:2], clock=lambda: 5.0) is None                    # a near-empty sheet is not trusted
    sr._CACHE.update(at=0.0, rows=None)


def test_standing_and_roster_emails_for_the_ghl_lookup():
    s = {"id": 1, "full_name": "Someone Else", "personal_email": "pers2@x.com"}
    assert sr.standing(s, ROWS) == "listed" and sr.roster_emails_for(s, ROWS) == ["app2@x.com", "pers2@x.com"]
    assert sr.standing({"id": 2, "full_name": "Nobody Known"}, ROWS) == "unlisted"
    assert sr.standing({"id": 3, "full_name": "Dov Surname"}, ROWS) == "name_only"                    # exact name, no email known to us
    assert sr.roster_emails_for({"id": 3, "full_name": "Dov Surname"}, ROWS) == ["app3@x.com", "pers3@x.com"]
    assert sr.roster_emails_for({"id": 4, "full_name": "Surname"}, ROWS) == []                      # a partial name never lends its emails
    assert sr.standing({"id": 5}, None) == "unknown"


class FakeGhl:
    def __init__(self, known):
        self.known, self.asked = known, []

    def search_contact_by_email(self, email):
        self.asked.append(email)
        return {"id": "c1", "firstName": "Person"} if email in self.known else None

    def search_contact_by_phone(self, phone):
        return None

    def search_contacts_by_name(self, *a, **k):
        return []


def test_ghl_is_searched_by_the_roster_personal_email_too(monkeypatch):
    sr._CACHE.update(at=1e12, rows=ROWS)                                  # a fresh cached roster
    student = SimpleNamespace(id=7, full_name="Dov Surname", personal_email="old3@x.com", assigned_gmail=None, phone_number=None)
    client = FakeGhl(known={"pers3@x.com"})
    contact, how, problem = nc.find_ghl_contact(client, student)
    assert contact and not problem and "pers3@x.com" in client.asked and "old3@x.com" in client.asked
    sr._CACHE.update(at=0.0, rows=None)


def test_ghl_status_words_and_caching():
    sf._GHL_CACHE.clear()
    student = SimpleNamespace(id=9, full_name="Zed Nobody", personal_email="zed@x.com", assigned_gmail=None, phone_number=None)
    assert sf.ghl_status(student, client=FakeGhl(known={"zed@x.com"})) == "found"
    again = FakeGhl(known=set())
    assert sf.ghl_status(student, client=again) == "found" and again.asked == []                    # cached: no second lookup
    sf._GHL_CACHE.clear()
    assert sf.ghl_status(student, client=FakeGhl(known=set())) == "not_found"
    sf._GHL_CACHE.clear()
