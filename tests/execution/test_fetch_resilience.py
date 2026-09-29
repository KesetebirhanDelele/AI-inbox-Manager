"""
Regression tests for the 2026-09-29 22:00 UTC incident.

While a deploy was hogging the server, Gmail dropped the IMAP connection
mid-fetch. fetch_emails() then failed *every remaining UID* instantly
("socket error: EOF"), only 2 emails were processed, and the run was still
recorded as "success" with no alert.

Fixed by (1) reconnecting and resuming when the connection is lost, and
(2) reporting a partly failed fetch: FetchedEmails.skipped/abandoned/reconnects,
run status "partial_failure", and a failure alert.

Everything uses in-memory fakes -- nothing touches a real IMAP server, the
network, the database or real email.
"""

import imaplib
import socket
import ssl
import sys
from pathlib import Path

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import fetch_emails  # noqa: E402
from fetch_emails import (  # noqa: E402
    EmailConnectionError,
    EmailConnectionLost,
    EmailFetchError,
    FetchedEmails,
    fetch_email_by_uid,
)


# ── fakes ────────────────────────────────────────────────────────────────────

class ScriptedIMAP:
    """One fake connection. Optionally dies after N successful FETCHes."""

    def __init__(self, uids=(), fail_after=None, error=None):
        self.uids = [str(u) for u in uids]
        self.fail_after = fail_after
        self.error = error or ssl.SSLError("EOF occurred in violation of protocol")
        self.fetched = []

    def uid(self, command, *args):
        cmd = command.upper()
        if cmd == "SEARCH":
            return ("OK", [" ".join(self.uids).encode()])
        if cmd == "FETCH":
            if self.fail_after is not None and len(self.fetched) >= self.fail_after:
                raise self.error
            uid = str(args[0])
            self.fetched.append(uid)
            return ("OK", [(b"hdr", f"raw-{uid}".encode())])
        return ("OK", [b""])

    def select(self, mailbox, readonly=False):
        return ("OK", [b"1"])

    def close(self):
        pass

    def logout(self):
        return ("BYE", [b""])


@pytest.fixture
def harness(monkeypatch):
    """Patch connect_to_imap to hand out scripted connections in order."""
    state = {"conns": [], "connect_calls": 0, "sleeps": []}

    def fake_connect(*_a, **_k):
        i = state["connect_calls"]
        state["connect_calls"] += 1
        item = state["conns"][i]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(fetch_emails, "connect_to_imap", fake_connect)
    monkeypatch.setattr(fetch_emails, "select_folder", lambda imap, folder: 1)
    monkeypatch.setattr(
        fetch_emails, "parse_email_message",
        lambda raw, uid: {"email_id": uid, "raw": raw},
    )
    monkeypatch.setattr(fetch_emails.time, "sleep", lambda s: state["sleeps"].append(s))
    return state


def _run(harness):
    return fetch_emails.fetch_emails(
        server="imap.test", port=993, email_address="a@test", password="x",
    )


# ── fetch_emails(): reconnect and resume ─────────────────────────────────────

def test_reconnects_and_completes_after_connection_drop(harness):
    uids = [1, 2, 3, 4, 5, 6]
    first = ScriptedIMAP(uids, fail_after=2)      # dies before fetching UID 3
    second = ScriptedIMAP(uids)
    harness["conns"] = [first, second]

    result = _run(harness)

    assert [e["email_id"] for e in result] == ["1", "2", "3", "4", "5", "6"]
    assert first.fetched == ["1", "2"]
    assert second.fetched == ["3", "4", "5", "6"]   # resumed at the failed UID
    assert (result.skipped, result.abandoned, result.reconnects) == (0, 0, 1)
    assert harness["connect_calls"] == 2
    assert harness["sleeps"] == [2]                 # first backoff step


def test_abandons_remaining_after_reconnect_budget_exhausted(harness):
    uids = [1, 2, 3]
    # Initial connection + 3 reconnects, every one dead on arrival.
    harness["conns"] = [
        ScriptedIMAP(uids, fail_after=0, error=socket.timeout("timed out"))
        for _ in range(4)
    ]

    result = _run(harness)

    assert list(result) == []
    assert result.reconnects == fetch_emails._MAX_RECONNECTS == 3
    assert result.abandoned == 3 and result.skipped == 3
    assert harness["connect_calls"] == 4
    assert harness["sleeps"] == [2, 5, 10]          # backoff grows


def test_failed_reconnect_abandons_remaining(harness):
    uids = [1, 2, 3, 4]
    harness["conns"] = [
        ScriptedIMAP(uids, fail_after=1),
        EmailConnectionError("Connection failed: gmail down"),
    ]

    result = _run(harness)

    assert [e["email_id"] for e in result] == ["1"]
    assert result.abandoned == 3 and result.skipped == 3
    assert result.reconnects == 1


def test_bad_single_message_is_skipped_without_reconnecting(harness, monkeypatch):
    uids = [1, 2, 3]
    conn = ScriptedIMAP(uids)
    harness["conns"] = [conn]

    def parse(raw, uid):
        if uid == "2":
            raise EmailFetchError("Email parsing failed: corrupt")
        return {"email_id": uid}

    monkeypatch.setattr(fetch_emails, "parse_email_message", parse)

    result = _run(harness)

    assert [e["email_id"] for e in result] == ["1", "3"]
    assert (result.skipped, result.abandoned, result.reconnects) == (1, 0, 0)
    assert harness["connect_calls"] == 1            # never reconnected
    assert harness["sleeps"] == []


def test_empty_search_returns_plain_compatible_empty_result(harness):
    harness["conns"] = [ScriptedIMAP([])]
    result = _run(harness)
    assert isinstance(result, list) and not result
    assert (result.skipped, result.abandoned, result.reconnects) == (0, 0, 0)


def test_fetched_emails_is_a_real_list():
    r = FetchedEmails([{"a": 1}], skipped=2)
    assert isinstance(r, list) and len(r) == 1 and r.skipped == 2
    assert r[:1] == [{"a": 1}]                      # slicing (used by the pipeline) works


# ── fetch_email_by_uid(): which errors mean "connection dead" ────────────────

class _RaisingIMAP:
    def __init__(self, exc):
        self.exc = exc

    def uid(self, *a, **k):
        raise self.exc


@pytest.mark.parametrize("exc", [
    ssl.SSLError("EOF occurred in violation of protocol (_ssl.c:2437)"),
    imaplib.IMAP4.abort("socket error: EOF"),
    socket.timeout("timed out"),
    ConnectionResetError("reset by peer"),
    BrokenPipeError("broken pipe"),
    EOFError(),
])
def test_connection_level_errors_become_connection_lost(exc):
    with pytest.raises(EmailConnectionLost):
        fetch_email_by_uid(_RaisingIMAP(exc), "7")


@pytest.mark.parametrize("exc", [
    imaplib.IMAP4.error("BAD parse"),
    ValueError("weird"),
])
def test_other_errors_stay_per_message_failures(exc):
    with pytest.raises(EmailFetchError) as info:
        fetch_email_by_uid(_RaisingIMAP(exc), "7")
    assert not isinstance(info.value, EmailConnectionLost)


def test_connection_lost_is_a_fetch_error():
    """Existing `except EmailFetchError` handlers keep working."""
    assert issubclass(EmailConnectionLost, EmailFetchError)
