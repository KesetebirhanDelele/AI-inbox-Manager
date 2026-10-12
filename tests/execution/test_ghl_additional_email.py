"""A student can be found by a primary OR an additional email; an additional email is added only after a person confirms and never replaces the primary."""
import sys
from pathlib import Path

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import ghl_client as gc  # noqa: E402
import ghl_add_additional_email as tool  # noqa: E402


def cfg(live):
    return gc.GhlConfig(api_key="tok", location_id="loc", write_mode="live" if live else "shadow",
                        shadow_log_only=not live, write_notify_fields=live)


class FakeGhl(gc.GhlClient):
    """A GHL location in memory: contacts by id; `_request` serves search, get and put like the real API (shape of additionalEmails assumed)."""
    def __init__(self, contacts, live=False, store_additional=True, change_primary=False):
        super().__init__(cfg(live), session=object(), sleep=lambda s: None)
        self.contacts = {c["id"]: dict(c) for c in contacts}
        self.puts, self.store_additional, self.change_primary = [], store_additional, change_primary

    def _request(self, method, path, **kw):
        if method == "GET" and path == "/contacts/":
            q = kw["params"]["query"].lower()
            hits = [c for c in self.contacts.values() if q in " ".join(gc.contact_emails(c)) or q in str(c.get("firstName", "")).lower()]
            return {"contacts": hits}
        cid = path.rsplit("/", 1)[-1]
        if method == "GET":
            return {"contact": self.contacts[cid]}
        if method == "PUT":
            self.puts.append((cid, kw["json"]))
            if self.store_additional:
                self.contacts[cid]["additionalEmails"] = kw["json"]["additionalEmails"]
            if self.change_primary:
                self.contacts[cid]["email"] = "oops@example.com"
            return {"contact": self.contacts[cid]}
        raise AssertionError(path)


ISAAC = {"id": "c1", "firstName": "kwadjossan", "email": "isaackpakpavi@gmail.com", "additionalEmails": []}
GMAIL = "kwadjossanisaackpakpavi@gmail.com"


def test_contact_emails_reads_primary_then_additional_in_any_known_shape():
    assert gc.contact_emails({"email": "A@x.com"}) == ["a@x.com"]
    assert gc.contact_emails({"email": "a@x.com", "additionalEmails": ["B@x.com", "a@x.com"]}) == ["a@x.com", "b@x.com"]
    assert gc.contact_emails({"email": "a@x.com", "additionalEmails": [{"email": "c@x.com"}, {"value": "d@x.com"}]}) == ["a@x.com", "c@x.com", "d@x.com"]
    assert gc.contact_emails({"email": None, "emails": "e@x.com"}) == ["e@x.com"]
    assert gc.contact_emails({}) == []


def test_a_student_is_found_by_the_primary_or_the_additional_email():
    g = FakeGhl([{**ISAAC, "additionalEmails": [GMAIL]}])
    assert g.search_contact_by_email("isaackpakpavi@gmail.com")["id"] == "c1"
    assert g.search_contact_by_email(GMAIL.upper())["id"] == "c1"                    # additional, any case
    assert g.search_contact_by_email("nobody@example.com") is None


def test_two_contacts_sharing_an_address_are_still_refused():
    g = FakeGhl([{**ISAAC, "additionalEmails": [GMAIL]}, {"id": "c2", "firstName": "other", "email": GMAIL}])
    with pytest.raises(gc.GhlError):
        g.search_contact_by_email(GMAIL)


def test_nothing_is_added_without_a_persons_confirmation():
    g = FakeGhl([ISAAC], live=True)
    with pytest.raises(gc.GhlError):
        g.add_additional_email("c1", GMAIL, confirmed_by="")
    assert g.puts == []


def test_shadow_mode_only_logs():
    g = FakeGhl([ISAAC], live=False)
    out = g.add_additional_email("c1", GMAIL, confirmed_by="Kes")
    assert out["live"] is False and out["changed"] is False and g.puts == []


def test_live_adds_to_the_additional_list_and_never_sends_the_primary():
    g = FakeGhl([{**ISAAC, "additionalEmails": ["old@example.com"]}], live=True)
    out = g.add_additional_email("c1", GMAIL, confirmed_by="Kes")
    assert out == {"live": True, "changed": True}
    cid, payload = g.puts[0]
    assert payload == {"additionalEmails": ["old@example.com", GMAIL]} and "email" not in payload        # the primary is never in the payload
    assert g.contacts["c1"]["email"] == "isaackpakpavi@gmail.com"                                         # and is unchanged
    assert g.search_contact_by_email(GMAIL)["id"] == "c1"                                                  # now found by the new address


def test_an_address_that_is_already_there_is_a_no_op():
    g = FakeGhl([{**ISAAC, "additionalEmails": [GMAIL]}], live=True)
    assert g.add_additional_email("c1", GMAIL, confirmed_by="Kes")["changed"] is False and g.puts == []
    assert g.add_additional_email("c1", "ISAACKPAKPAVI@gmail.com", confirmed_by="Kes")["changed"] is False


def test_an_address_owned_by_another_contact_is_refused():
    g = FakeGhl([ISAAC, {"id": "c2", "firstName": "other", "email": GMAIL}], live=True)
    with pytest.raises(gc.GhlError):
        g.add_additional_email("c1", GMAIL, confirmed_by="Kes")
    assert g.puts == []


def test_a_write_that_did_not_stick_or_moved_the_primary_fails_loudly():
    with pytest.raises(gc.GhlError, match="did not store"):
        FakeGhl([ISAAC], live=True, store_additional=False).add_additional_email("c1", GMAIL, confirmed_by="Kes")
    with pytest.raises(gc.GhlError, match="primary email changed"):
        FakeGhl([ISAAC], live=True, change_primary=True).add_additional_email("c1", GMAIL, confirmed_by="Kes")


def test_the_command_line_tool_dry_runs_by_default_and_needs_a_confirmer(monkeypatch):
    monkeypatch.setattr(tool, "load_env", lambda: {"GHL_API_KEY": "k", "GHL_LOCATION_ID": "l"})
    holder = {}

    def factory(config):
        holder["g"] = FakeGhl([ISAAC], live=config.is_live)
        return holder["g"]
    lines = []
    assert tool.run(["--contact-id", "c1", "--email", GMAIL, "--confirmed-by", "Kes"], client_factory=factory, out=lines.append) == 0
    assert holder["g"].puts == [] and any("DRY RUN" in l for l in lines)
    lines.clear()
    assert tool.run(["--contact-id", "c1", "--email", GMAIL, "--confirmed-by", "Kes", "--apply"], client_factory=factory, out=lines.append) == 0
    assert holder["g"].puts and any("WRITTEN" in l for l in lines)
    with pytest.raises(SystemExit):                                               # --confirmed-by is required
        tool.run(["--contact-id", "c1", "--email", GMAIL], client_factory=factory, out=lines.append)
