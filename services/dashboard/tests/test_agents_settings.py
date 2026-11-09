"""Settings page: the email for each student's agent (names come from the roster sheet)."""
import sys
from pathlib import Path

import pytest

_EXEC = str(Path(__file__).resolve().parents[3] / "execution")
if _EXEC not in sys.path:
    sys.path.insert(0, _EXEC)

import student_roster as sr  # noqa: E402


@pytest.fixture
def roster(monkeypatch):
    rows = [sr.RosterRow(name=f"S{i}", status="Active", agent="Karthik", emails=[f"s{i}@x.com"]) for i in range(3)]
    rows.append(sr.RosterRow(name="Old", status="Withdrawn", agent="Gone", emails=["o@x.com"]))
    rows.append(sr.RosterRow(name="Dee", status="Active", agent="Priya", emails=["d@x.com"]))
    monkeypatch.setattr(sr, "cached_roster", lambda *a, **k: rows)


def test_lists_agents_from_the_roster_with_active_student_counts(client, db, auth_cookies, roster):
    data = client.get("/api/roles/agents", cookies=auth_cookies).json()
    assert data["roster_readable"] is True
    assert data["agents"] == [{"agent": "Karthik", "students": 3, "email": ""}, {"agent": "Priya", "students": 1, "email": ""}]   # withdrawn-only agent not listed


def test_save_and_clear_an_agent_email(client, db, auth_cookies, roster):
    assert client.put("/api/roles/agents", json={"agent": "Karthik", "email": "k@example.com"}, cookies=auth_cookies).status_code == 200
    agents = client.get("/api/roles/agents", cookies=auth_cookies).json()["agents"]
    assert {a["agent"]: a["email"] for a in agents}["Karthik"] == "k@example.com"
    client.put("/api/roles/agents", json={"agent": "Karthik", "email": ""}, cookies=auth_cookies)
    agents = client.get("/api/roles/agents", cookies=auth_cookies).json()["agents"]
    assert {a["agent"]: a["email"] for a in agents}["Karthik"] == ""


def test_bad_email_and_empty_name_are_refused(client, db, auth_cookies, roster):
    assert client.put("/api/roles/agents", json={"agent": "Karthik", "email": "nope"}, cookies=auth_cookies).status_code == 422
    assert client.put("/api/roles/agents", json={"agent": " ", "email": "k@example.com"}, cookies=auth_cookies).status_code == 422


def test_agents_do_not_appear_among_the_single_roles(client, db, auth_cookies, roster):
    client.put("/api/roles/agents", json={"agent": "Karthik", "email": "k@example.com"}, cookies=auth_cookies)
    roles = client.get("/api/roles", cookies=auth_cookies).json()["roles"]
    assert "agent" not in {r["role"] for r in roles}


def test_needs_login(client, db):
    assert client.get("/api/roles/agents").status_code == 401
    assert client.put("/api/roles/agents", json={"agent": "K", "email": ""}).status_code == 401
