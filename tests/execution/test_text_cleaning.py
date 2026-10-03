import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))
import text_cleaning as tc  # noqa: E402

MARKETING = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Your Email Title</title><style>@import url(https://fonts.googleapis.com/css2?family=Open+Sans);'
    "body{font-size:14px} .ql-container{box-sizing:border-box}</style></head><body><div><p>Hi Sehrish,</p><p>We would like to schedule an "
    "interview &amp; call you on <b>Tuesday</b> at 2&nbsp;PM.</p><br>Thanks<!-- tracking pixel --></div><script>var x=1;</script></body></html>"
)


def test_css_head_title_script_and_comments_are_dropped():
    text = tc.clean_email_text(MARKETING)
    assert "font-size" not in text and "ql-container" not in text and "Your Email Title" not in text and "var x" not in text
    assert "tracking pixel" not in text and "<" not in text


def test_text_content_and_line_breaks_survive_and_entities_are_decoded():
    text = tc.clean_email_text(MARKETING)
    assert text.splitlines()[0] == "Hi Sehrish,"
    assert "interview & call you on Tuesday at 2 PM." in text and text.endswith("Thanks")


def test_plain_text_passes_through_tidied():
    assert tc.clean_email_text("Hello   there\r\n\r\n\r\nSecond  line  ") == "Hello there\n\nSecond line"
    assert tc.clean_email_text("") == "" and tc.clean_email_text(None) == ""


def test_a_plain_text_email_containing_a_less_than_sign_is_not_mangled():
    assert tc.clean_email_text("if a < b and c > d then call me") == "if a < b and c > d then call me"


def test_clean_preview_keeps_good_previews_and_rebuilds_html_ones_from_the_full_body():
    assert tc.clean_preview("Hi there", "ignored") == "Hi there"
    rebuilt = tc.clean_preview("<!DOCTYPE html><html><head><style>x{}</style>", MARKETING)
    assert rebuilt.startswith("Hi Sehrish,") and len(rebuilt) <= 500
