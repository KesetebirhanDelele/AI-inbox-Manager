"""Interview gate with a database: history, assess (model mocked), saved reviews, the review API, and the replay of past mail."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from conftest import make_email, make_student, make_interview_event, make_notification_draft

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "execution"))
import interview_gate as g  # noqa: E402
import interview_gate_replay as replay_mod  # noqa: E402
from models import InterviewGateReview  # noqa: E402

LORENA = """Hi Rutendo,

I've attached the job description as you requested. Please let me know if I can assist with anything else.

Lorena Ortiz
Executive Support | Technology

________________________________
From: Rutendo Bwerazuva <rbwerazuva@gmail.com>
Sent: Friday, October 23, 2026 5:40 PM
To: Ortiz, Lorena <lorena.ortiz@fwisd.org>
Subject: Re: In-Person Interview Request

On Fri, Oct 23, 2026 at 1:34 PM Ortiz, Lorena <lorena.ortiz@fwisd.org> wrote:
Interview Date Confirmation: Thursday, October 29, 2026
Interview Time: 10:30 AM
"""
NOW = datetime(2026, 10, 26, 15, 28)
THREAD = "Re: In-Person Interview Request: Senior BI Developer"


def fake_model(**answer):
    base = {"verdict": "not_interview", "round": "unknown", "format": "unknown", "refers_to": None, "confidence": 0.95, "reason": "courtesy reply"}
    seen = {}

    def call(prompt):
        seen["prompt"] = prompt
        return {"text": json.dumps({**base, **answer}), "input_tokens": 3000, "output_tokens": 100}
    call.seen = seen
    return call


def seed_thread(db):
    """The earlier, announced interview email of the same thread, from the same person."""
    student = make_student(db)
    first = make_email(db, email_id="first", subject="In-Person Interview Request: Senior BI Developer",
                       from_address="Ortiz, Lorena <lorena.ortiz@fwisd.org>", received_date=NOW - timedelta(days=3))
    event = make_interview_event(db, first, student=student, sub_type="Client Screen", company="Fort Worth ISD", interview_date="2026-10-29")
    make_notification_draft(db, event, email_status="sent")
    return first, event


def seed_lorena(db):
    lorena = make_email(db, email_id="lorena", subject=THREAD, from_address="lorena.ortiz@fwisd.org", received_date=NOW)
    lorena.full_body = LORENA
    db.commit()
    ev = make_interview_event(db, lorena, sub_type="Client Screen", company="Fort Worth ISD", interview_date="2026-10-29")
    make_notification_draft(db, ev, email_status="draft")
    return lorena, ev


def test_the_quoted_thread_never_reaches_the_model_and_the_history_does(db):
    seed_thread(db)
    call = fake_model()
    out = g.assess(db, THREAD, "lorena.ortiz@fwisd.org", LORENA, received=NOW, call=call)
    prompt = call.seen["prompt"]
    assert "job description" in prompt
    assert "10:30 AM" not in prompt.split("NEW TEXT:")[1]                    # the old date is only in the history, not in the new text
    assert "event=Client Screen 2026-10-29 14:00" in prompt and "notice=sent" in prompt
    assert out["quoted_chars"] > 0 and out["result"]["verdict"] == "not_interview"
    assert g.would_hide_card(out["result"])
    assert out["cost_usd"] == round(3000 * 0.15 / 1e6 + 100 * 0.60 / 1e6, 6)


def test_history_is_limited_to_ten_newest_and_to_older_mail(db):
    for i in range(14):
        make_email(db, email_id=f"e{i}", subject=f"Other {i}", from_address="hr@fwisd.org", received_date=NOW - timedelta(days=20 - i))
    later = make_email(db, email_id="later", subject="Later", from_address="hr@fwisd.org", received_date=NOW + timedelta(days=1))
    rows = g.load_history(db, "x", "someone@fwisd.org", before=NOW)
    assert len(rows) == 10 and rows[0]["received"] > rows[-1]["received"]
    assert later.id not in {r["email_id"] for r in rows}


def test_free_mail_matches_the_exact_address_only(db):
    make_email(db, email_id="a", subject="A", from_address="Bob <bob@gmail.com>", received_date=NOW - timedelta(days=2))
    make_email(db, email_id="b", subject="B", from_address="carol@gmail.com", received_date=NOW - timedelta(days=1))
    assert [r["subject"] for r in g.load_history(db, "zz", "bob@gmail.com", before=NOW)] == ["A"]


def test_a_failing_model_never_raises_and_gives_no_result(db):
    def boom(prompt):
        raise RuntimeError("openai down")
    out = g.assess(db, "s", "a@b.com", "hello", call=boom)
    assert out["result"] is None and "openai down" in out["error"] and not g.would_hide_card(out["result"])


def test_an_unreadable_answer_gives_no_result(db):
    out = g.assess(db, "s", "a@b.com", "hello", call=lambda p: {"text": "sure!", "input_tokens": 1, "output_tokens": 1})
    assert out["result"] is None and out["error"] == "unreadable answer"


def test_refers_to_maps_to_the_event_in_the_history(db):
    first, event = seed_thread(db)
    out = g.assess(db, THREAD, "lorena.ortiz@fwisd.org", LORENA, received=NOW, call=fake_model(verdict="follow_up", refers_to=1))
    assert out["result"]["refers_to_event_id"] == event.id


def test_record_review_saves_once_and_keeps_a_persons_decision(db):
    email = make_email(db, email_id="x")
    out = g.assess(db, "s", "a@b.com", "Phone screen tomorrow at 3 PM", call=fake_model(verdict="new_interview", round="2nd", format="phone"))
    g.record_review(db, out, email.id, None, "shadow")
    row = db.query(InterviewGateReview).one()
    row.human_decision, row.decided_by = "real", "kes"
    db.commit()
    g.record_review(db, g.assess(db, "s", "a@b.com", "x", call=fake_model()), email.id, None, "shadow", source="replay")
    row = db.query(InterviewGateReview).one()
    assert row.verdict == "not_interview" and row.source == "replay" and row.human_decision == "real" and row.decided_by == "kes"


def test_review_api_summary_and_decisions(client, db, auth_cookies):
    seed_thread(db)
    lorena, ev2 = seed_lorena(db)
    g.record_review(db, g.assess(db, lorena.subject, lorena.from_address, LORENA, received=NOW, exclude_email_id=lorena.id, call=fake_model()),
                    lorena.id, ev2.id, "shadow")
    items = client.get("/api/interview-gate/reviews", cookies=auth_cookies).json()
    assert len(items) == 1 and items[0]["gate_says"] == "not_real" and items[0]["notice_status"] == "draft"
    assert "10:30 AM" not in items[0]["new_text"] and items[0]["quoted_chars"] > 0
    rid = items[0]["id"]
    assert client.post(f"/api/interview-gate/reviews/{rid}/decision", json={"decision": "not_real"}, cookies=auth_cookies).status_code == 200
    assert client.get("/api/interview-gate/reviews", cookies=auth_cookies).json() == []                 # decided: off the undecided list
    s = client.get("/api/interview-gate/summary", cookies=auth_cookies).json()
    assert (s["total"], s["decided"], s["agree"], s["hid_a_real_one"]) == (1, 1, 1, 0)
    client.post(f"/api/interview-gate/reviews/{rid}/decision", json={"decision": "real", "note": "was actually a reschedule"}, cookies=auth_cookies)
    s = client.get("/api/interview-gate/summary", cookies=auth_cookies).json()
    assert (s["agree"], s["hid_a_real_one"]) == (0, 1)                                                  # the dangerous disagreement is counted
    assert [i["id"] for i in client.get("/api/interview-gate/reviews?show=disagree", cookies=auth_cookies).json()] == [rid]
    assert client.post(f"/api/interview-gate/reviews/{rid}/decision", json={"decision": "maybe"}, cookies=auth_cookies).status_code == 422
    assert client.post("/api/interview-gate/reviews/9999/decision", json={"decision": "real"}, cookies=auth_cookies).status_code == 404


def test_review_api_needs_a_login(client):
    assert client.get("/api/interview-gate/reviews").status_code in (401, 403)


def test_replay_judges_past_mail_with_only_older_history_and_changes_nothing_else(db):
    first, event = seed_thread(db)
    lorena, ev2 = seed_lorena(db)

    pairs = replay_mod.candidates(db)
    assert [e.id for e, _ in pairs] == [ev2.id, event.id]                                                # newest first

    def assess(db_, subject, from_address, body, received=None, exclude_email_id=None, **kw):
        return g.assess(db_, subject, from_address, body, received=received, exclude_email_id=exclude_email_id, call=fake_model(), **kw)

    replay_mod.replay(db, pairs, assess=assess)
    rows = {r.email_id: r for r in db.query(InterviewGateReview).all()}
    assert set(rows) == {first.id, lorena.id} and all(r.source == "replay" for r in rows.values())
    assert rows[lorena.id].history and rows[first.id].history == []                                      # the first email had no older mail
    assert replay_mod.candidates(db) == []                                                              # run twice = nothing new
    assert db.get(type(ev2), ev2.id).sub_type == "Client Screen"                                         # events untouched


def test_history_finds_the_original_interview_even_from_a_different_sender(db):
    """A Calendly reminder and the recruiter's invite share no sender and no subject; the company and the date/time still link them."""
    student = make_student(db)
    invite = make_email(db, email_id="inv", subject="Technical interview invitation", from_address="recruiter@solutionsbytext.com",
                        received_date=NOW - timedelta(days=2))
    event = make_interview_event(db, invite, student=student, sub_type="Technical Interview", company="Solutions by Text", interview_date="2026-10-29")
    make_notification_draft(db, event, email_status="sent")
    make_email(db, email_id="noise", subject="Other", from_address="hr@elsewhere.com", received_date=NOW - timedelta(days=1))
    rows = g.load_history(db, "Reminder: SBT session", "notifications@calendly.com", before=NOW, company="Solutions by Text", student_id=student.id,
                          interview_date="2026-10-29", interview_time="14:00")
    assert invite.id in {r["email_id"] for r in rows}
    by_moment = g.load_history(db, "Reminder", "notifications@calendly.com", before=NOW, student_id=student.id, interview_date="2026-10-29", interview_time="14:00")
    assert invite.id in {r["email_id"] for r in by_moment}                                              # no company needed: same date and time
    assert invite.id not in {r["email_id"] for r in g.load_history(db, "Reminder", "notifications@calendly.com", before=NOW)}   # nothing to link on


def test_another_students_interview_at_the_same_company_is_not_history(db):
    mine, other = make_student(db), make_student(db, username="asmith", full_name="A Smith", personal_email="a@example.com")
    theirs = make_email(db, email_id="theirs", subject="Interview", from_address="hr@acme.com", received_date=NOW - timedelta(days=2))
    make_interview_event(db, theirs, student=other, company="Acme Corp", interview_date="2026-10-29")
    rows = g.load_history(db, "x", "someone@else.com", before=NOW, company="Acme Corp", student_id=mine.id)
    assert theirs.id not in {r["email_id"] for r in rows}


def test_assess_passes_the_sender_check_to_the_model(db):
    call = fake_model()
    out = g.assess(db, "Confirm interview availability", "jobs@talent-hub.com",
                   "Please confirm your availability for an interview. Unsubscribe", call=call)
    assert "SENDER CHECK: " in call.seen["prompt"] and out["sender_check"] is not None
