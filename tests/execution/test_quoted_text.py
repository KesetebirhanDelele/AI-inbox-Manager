"""Quoted-reply stripping: the new text of a reply, never the thread under it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))
import quoted_text as qt  # noqa: E402

# The Lorena Ortiz reply of 2026-10-26: one courtesy line, then the confirmed interview quoted below it.
LORENA = """Hi Rutendo,

I've attached the job description as you requested. Please let me know if I can assist with anything else.

Lorena Ortiz
Executive Support | Technology
Fort Worth Independent School District

________________________________
From: Rutendo Bwerazuva <rbwerazuva@gmail.com>
Sent: Friday, October 23, 2026 5:40 PM
To: Ortiz, Lorena <lorena.ortiz@fwisd.org>
Subject: Re: In-Person Interview Request: Senior Business Intelligence Developer

Hi Lorena
Ok I will do that

On Fri, Oct 23, 2026 at 1:34 PM Ortiz, Lorena <lorena.ortiz@fwisd.org> wrote:
Hi Rutendo!
Interview Date Confirmation: Thursday, October 29, 2026
Interview Time: 10:30 AM
"""


def test_the_thread_under_a_reply_is_cut_off():
    new, quoted = qt.split_reply(LORENA)
    assert "job description" in new
    assert "October 29" not in new and "10:30" not in new
    assert "Interview Time: 10:30 AM" in quoted


def test_on_date_wrote_marker_cuts():
    text = "Sounds good, see you then.\n\nOn Mon, Oct 26, 2026 at 9:00 AM Bob <b@x.com> wrote:\n> Interview Thursday 10:30 AM"
    assert qt.new_text_only(text) == "Sounds good, see you then."


def test_wrapped_wrote_marker_cuts():
    text = "Thanks, confirmed for Friday at 2 PM.\n\nOn Mon, Oct 26, 2026 at 9:00 AM Robert Longname <bob@example.com>\nwrote:\n> old"
    assert qt.new_text_only(text) == "Thanks, confirmed for Friday at 2 PM."


def test_outlook_header_block_without_a_rule_cuts():
    text = "Please see the attached.\n\nFrom: A B <a@x.com>\nSent: Monday, October 26, 2026 1:00 PM\nTo: C\nSubject: Interview\n\nOld text 10:30 AM"
    assert qt.new_text_only(text) == "Please see the attached."


def test_original_message_marker_cuts():
    text = "I can do that, thank you.\n\n-----Original Message-----\nFrom: x\nSent: y\nInterview Monday 9 AM"
    assert qt.new_text_only(text) == "I can do that, thank you."


def test_an_email_that_starts_with_a_header_is_a_forward_and_is_kept_whole():
    text = "From: Recruiter <r@acme.com>\nSent: Monday, October 26, 2026 1:00 PM\nTo: Student\nSubject: Interview\n\nYour interview is Thursday at 10:30 AM."
    assert qt.new_text_only(text) == text


def test_a_forwarded_message_banner_is_not_a_reply_marker():
    text = "FYI, please see below.\n\n---------- Forwarded message ---------\nFrom: r@acme.com\nSent: Monday\nTo: s\nInterview Thursday 10:30 AM"
    assert "Thursday 10:30 AM" in qt.new_text_only(text)


def test_nothing_left_after_the_cut_keeps_the_whole_text():
    text = "Ok\n\nOn Mon, Oct 26, 2026 at 9:00 AM Bob <b@x.com> wrote:\nInterview Thursday 10:30 AM"
    assert qt.new_text_only(text) == text.strip()


def test_a_plain_email_is_unchanged():
    text = "Hello, your phone screen is Tuesday at 3 PM Central."
    assert qt.split_reply(text) == (text, "")


def test_empty_input():
    assert qt.split_reply("") == ("", "")
    assert qt.split_reply(None) == ("", "")
