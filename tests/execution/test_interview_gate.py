"""The third interview screen: prompt, parsing, decision and flag rules (pure; the model is never called)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))
import interview_gate as g  # noqa: E402


def _answer(**kw):
    base = {"verdict": "new_interview", "round": "2nd", "format": "phone", "refers_to": None, "confidence": 0.9, "reason": "r"}
    return json.dumps({**base, **kw})


def test_a_good_answer_is_parsed():
    r = g.parse_response(_answer(refers_to=1), history_size=3)
    assert r == {"verdict": "new_interview", "round": "2nd", "format": "phone", "refers_to": 1, "confidence": 0.9, "reason": "r"}


def test_garbage_unknown_verdicts_and_bad_json_are_refused():
    assert g.parse_response("not json") is None
    assert g.parse_response(None) is None
    assert g.parse_response(_answer(verdict="maybe")) is None
    assert g.parse_response("[1,2]") is None


def test_out_of_range_fields_are_cleaned_not_trusted():
    r = g.parse_response(_answer(round="7th", format="telepathy", refers_to=9, confidence="high"), history_size=2)
    assert (r["round"], r["format"], r["refers_to"], r["confidence"]) == ("unknown", "unknown", None, 0.0)
    assert g.parse_response(_answer(confidence=5))["confidence"] == 1.0


def test_only_a_confident_no_news_verdict_hides_a_card():
    assert g.would_hide_card({"verdict": "not_interview", "confidence": 0.9})
    assert g.would_hide_card({"verdict": "follow_up", "confidence": 0.7})
    assert not g.would_hide_card({"verdict": "not_interview", "confidence": 0.69})      # unsure: show the card
    assert not g.would_hide_card({"verdict": "new_interview", "confidence": 0.99})
    assert not g.would_hide_card({"verdict": "reschedule", "confidence": 0.99})
    assert not g.would_hide_card({"verdict": "cancellation", "confidence": 0.99})
    assert not g.would_hide_card(None)                                                  # the gate failed: never hide


def test_flags_show_round_and_format():
    assert g.label({"verdict": "new_interview", "round": "2nd", "format": "phone"}) == "2nd round · Phone"
    assert g.label({"verdict": "new_interview", "round": "final", "format": "in-person"}) == "Final round · In-person"
    assert g.label({"verdict": "new_interview", "round": "unknown", "format": "unknown"}) == "Interview"
    assert g.label({"verdict": "reschedule", "round": "unknown", "format": "video"}) == "Rescheduled · Video"
    assert g.label({"verdict": "cancellation", "round": "unknown", "format": "unknown"}) == "Cancelled"
    assert g.label({"verdict": "not_interview"}) is None and g.label(None) is None


def test_prompt_carries_new_text_history_and_the_rules():
    history = [{"received": "2026-10-23 13:34", "subject": "In-Person Interview Request", "sub_type": "Client Screen",
                "date": "2026-10-29", "time": "10:30", "company": "FWISD", "status": "sent", "snippet": "Interview Date Confirmation"}]
    p = g.build_prompt("Re: In-Person Interview Request", "lorena.ortiz@fwisd.org", "I've attached the job description.", history)
    assert "I've attached the job description." in p
    assert "[1] 2026-10-23 13:34" in p and "event=Client Screen 2026-10-29 10:30 at FWISD" in p and "notice=sent" in p
    assert "Judge ONLY the NEW text" in p


def test_prompt_without_history_says_so():
    assert "(no earlier related emails)" in g.build_prompt("s", "a@b.com", "hello", [])


def test_new_text_is_capped():
    assert len(g.build_prompt("s", "a@b.com", "x" * 20000, [])) < 6000


def test_subject_normalisation_ignores_reply_prefixes():
    assert g.normalize_subject("RE: Fwd: In-Person Interview Request!") == g.normalize_subject("In-Person Interview Request")


def test_mode_defaults_to_off_and_rejects_nonsense(monkeypatch):
    monkeypatch.delenv("INTERVIEW_GATE_MODE", raising=False)
    assert g.gate_mode() == "off"
    monkeypatch.setenv("INTERVIEW_GATE_MODE", "LIVE")
    assert g.gate_mode() == "live"
    monkeypatch.setenv("INTERVIEW_GATE_MODE", "yes please")
    assert g.gate_mode() == "off"


# --- the pipeline hook (process_inbox_auto.process_interview_email) --------------------------------------------------------

import process_inbox_auto as pia  # noqa: E402
import interview_followup  # noqa: E402
import log_interview  # noqa: E402


def _pipeline(monkeypatch, mode, result, error=None, quoted=0):
    """Wire process_interview_email with fakes. Returns (calls, classification)."""
    calls = {"reviews": [], "events": [], "links": [], "sub_input": []}
    out = {"result": result, "error": error, "new_text": "NEW ONLY", "quoted_chars": quoted, "history": [], "cost_usd": 0.0}
    monkeypatch.setenv("INTERVIEW_GATE_MODE", mode)
    monkeypatch.setattr(pia, "get_db_session", lambda: object())
    monkeypatch.setattr(g, "assess", lambda *a, **k: out)
    monkeypatch.setattr(g, "record_review", lambda db, o, email_id, event_id, m, source="live": calls["reviews"].append((event_id, m)))
    monkeypatch.setattr(pia, "_build_sub_classification", lambda e, c: calls["sub_input"].append(e) or {"interview_sub_type": "Phone Screen", "sub_type_source": "subclassifier"})
    monkeypatch.setattr(pia, "_identify_student", lambda db, e, c: (None, None))
    monkeypatch.setattr(log_interview, "log_interview_event", lambda **k: calls["events"].append(k) or {"id": 55})
    monkeypatch.setattr(interview_followup, "find_scheduled_interview", lambda *a, **k: None)
    monkeypatch.setattr(interview_followup, "record_follow_up", lambda db, ev, orig, reason="": calls["links"].append((ev, orig, reason)))
    return calls, {"category": "Phone Screen", "confidence": 0.9, "extracted_data": {}}


EMAIL = {"subject": "Re: Interview", "sender_email": "a@b.com", "body_content": "FULL BODY WITH THREAD"}
NOT_INTERVIEW = {"verdict": "not_interview", "round": "unknown", "format": "unknown", "refers_to": None, "refers_to_event_id": None, "confidence": 0.95, "reason": "courtesy"}


def test_gate_off_changes_nothing_and_never_calls_the_model(monkeypatch):
    calls, cls = _pipeline(monkeypatch, "off", NOT_INTERVIEW)
    monkeypatch.setattr(g, "assess", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")))
    assert pia.process_interview_email(dict(EMAIL), 1, cls) is True
    assert calls["reviews"] == [] and len(calls["events"]) == 1


def test_shadow_records_the_verdict_but_still_creates_the_event(monkeypatch):
    calls, cls = _pipeline(monkeypatch, "shadow", NOT_INTERVIEW, quoted=500)
    assert pia.process_interview_email(dict(EMAIL), 1, cls) is True
    assert calls["reviews"] == [(55, "shadow")] and len(calls["events"]) == 1 and not cls.get("_not_an_interview")
    assert calls["sub_input"][0]["body_content"] == "FULL BODY WITH THREAD"          # shadow reads exactly what it always read


def test_live_no_news_makes_no_event_and_is_recorded(monkeypatch):
    calls, cls = _pipeline(monkeypatch, "live", NOT_INTERVIEW, quoted=500)
    assert pia.process_interview_email(dict(EMAIL), 1, cls) is False
    assert cls["_not_an_interview"] is True and calls["events"] == [] and calls["reviews"] == [(None, "live")]
    assert calls["sub_input"][0]["body_content"] == "NEW ONLY"                           # live reads the sender's new text, not the thread


def test_live_a_new_round_still_makes_the_event(monkeypatch):
    calls, cls = _pipeline(monkeypatch, "live", {**NOT_INTERVIEW, "verdict": "new_interview", "round": "2nd", "format": "phone"})
    assert pia.process_interview_email(dict(EMAIL), 1, cls) is True
    assert len(calls["events"]) == 1 and calls["links"] == []


def test_live_a_follow_up_with_an_original_is_linked_and_gets_no_notice(monkeypatch):
    calls, cls = _pipeline(monkeypatch, "live", {**NOT_INTERVIEW, "verdict": "follow_up", "refers_to": 1, "refers_to_event_id": 12})
    assert pia.process_interview_email(dict(EMAIL), 1, cls) is True
    assert calls["links"] == [(55, 12, "gate: follow_up")]


def test_live_a_follow_up_with_no_original_makes_no_event(monkeypatch):
    calls, cls = _pipeline(monkeypatch, "live", {**NOT_INTERVIEW, "verdict": "follow_up"})
    assert pia.process_interview_email(dict(EMAIL), 1, cls) is False and calls["events"] == []


def test_live_an_unsure_or_failed_gate_never_hides_a_card(monkeypatch):
    calls, cls = _pipeline(monkeypatch, "live", {**NOT_INTERVIEW, "confidence": 0.5})
    assert pia.process_interview_email(dict(EMAIL), 1, cls) is True and len(calls["events"]) == 1
    calls, cls = _pipeline(monkeypatch, "live", None, error="openai down")
    assert pia.process_interview_email(dict(EMAIL), 1, cls) is True and len(calls["events"]) == 1


def test_the_sender_check_goes_into_the_prompt_as_facts():
    check = {"verdict": "likely_job_board", "against": ["Uses wording typical of job-board mailers: \"confirm your availability\"."], "for": []}
    p = g.build_prompt("Confirm interview availability", "jobs@talent-hub.com", "Please confirm your availability.", [], check)
    assert "SENDER CHECK: likely_job_board" in p and "job-board mailers" in p
    assert "(not available)" in g.build_prompt("s", "a@b.com", "x", [])


def test_a_closed_position_is_not_an_interview_cancellation_in_the_prompt():
    p = g.build_prompt("Update on your application", "hr@acme.com", "The position has been cancelled.", [])
    assert "requisition or application that is closed, filled or cancelled is NOT a cancellation" in p


def test_the_pipeline_tells_the_gate_the_category(monkeypatch):
    seen = {}
    calls, cls = _pipeline(monkeypatch, "shadow", NOT_INTERVIEW)
    monkeypatch.setattr(g, "assess", lambda *a, **k: seen.update(k) or {"result": None, "error": "x", "new_text": "", "quoted_chars": 0, "history": [], "cost_usd": 0})
    pia.process_interview_email(dict(EMAIL), 1, cls)
    assert seen["category"] == "Phone Screen"


VIZIENT = "Dear Binoy, Thank you for your interest in our Sr Analyst position at Vizient. At this time, the role has been cancelled. We hope you remain enthusiastic."
USAA = "Thank you for your interest in the Business Intelligence Analyst position at USAA. This position has been cancelled and is no longer available."


def test_a_cancelled_position_is_not_an_interview_cancellation():
    assert g.closes_a_position_not_an_interview("An update on your recent application", VIZIENT)
    assert g.closes_a_position_not_an_interview("Thank You for Applying", USAA)
    assert g.closes_a_position_not_an_interview("Update", "The requisition has been closed and filled.")


def test_a_real_interview_cancellation_is_kept():
    assert not g.closes_a_position_not_an_interview("RE: Representation Mail", "the position has been cancelled, so the interview will no longer be scheduled.")
    assert not g.closes_a_position_not_an_interview("Canceled: Sehrish Khan: 15-30 Minutes Meeting", "Thank you for scheduling a phone screen!")
    assert not g.closes_a_position_not_an_interview("Cancelled", "Your call on Friday has been cancelled.")
    assert not g.closes_a_position_not_an_interview("Hello", "Thanks for your time.")
