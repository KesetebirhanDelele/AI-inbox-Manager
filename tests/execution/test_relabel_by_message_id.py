"""Manual moves from the dashboard: find the mail by Message-ID wherever Gmail has it, label it, drop our other folder labels, never delete."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import fetch_emails as fe  # noqa: E402


def test_parse_labels_keeps_names_with_spaces_and_system_labels():
    line = '505163 (X-GM-LABELS ("Spam Review" Quarantine \\Inbox "Job Alerts") UID 1381225)'
    assert fe._parse_gm_labels(line) == ["Spam Review", "Quarantine", "\\Inbox", "Job Alerts"]
    assert fe._parse_gm_labels("1 (X-GM-LABELS () UID 5)") == []
    assert fe._parse_gm_labels("nothing here") == []


class FakeImap:
    """Just enough IMAP: one message, in All Mail, carrying `labels`; records every STORE/EXPUNGE."""

    def __init__(self, labels, found=True):
        self.labels, self.found, self.calls, self.selected = list(labels), found, [], None

    def select(self, name):
        self.selected = name
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        self.calls.append((self.selected, cmd) + args)
        if cmd == "SEARCH":
            return "OK", [b"77" if self.found else b""]
        if cmd == "STORE" and args[1] == "+X-GM-LABELS":
            self.labels.append(args[2].strip('()"'))
        if cmd == "STORE" and args[1] == "-X-GM-LABELS":
            self.labels.remove(args[2].strip('()"'))
        if cmd == "FETCH":
            atoms = " ".join(l if l.startswith("\\") else '"%s"' % l for l in self.labels)
            return "OK", [("77 (X-GM-LABELS (%s) UID 77)" % atoms).encode()]
        return "OK", [b""]

    def logout(self):
        pass


def _run(monkeypatch, imap, target="Spam Review"):
    monkeypatch.setattr(fe, "connect_to_imap", lambda *a, **k: imap)
    return fe.relabel_by_message_id("s", 993, "a", "p", "<m@x>", target, {"Quarantine", "Spam Review", "Job Alerts", "INBOX"})


def test_moves_from_a_stale_folder_to_the_target(monkeypatch):
    imap = FakeImap(["Quarantine"])                      # the database said Spam Review; Gmail has it in Quarantine
    assert _run(monkeypatch, imap, target="Job Alerts") is True
    assert imap.labels == ["Job Alerts"]
    assert not any(c[1] == "EXPUNGE" for c in imap.calls)    # not in the inbox: nothing is expunged


def test_takes_the_inbox_copy_out_with_a_scoped_expunge(monkeypatch):
    imap = FakeImap(["\\Inbox"])
    assert _run(monkeypatch, imap, target="Job Alerts") is True
    expunges = [c for c in imap.calls if c[1] == "EXPUNGE"]
    assert len(expunges) == 1 and expunges[0][0] == "INBOX"        # scoped to INBOX, by UID
    assert "Job Alerts" in imap.labels


def test_a_message_gmail_cannot_find_is_reported_not_guessed(monkeypatch):
    imap = FakeImap([], found=False)
    assert _run(monkeypatch, imap) is False
    assert not any(c[1] == "STORE" for c in imap.calls)
