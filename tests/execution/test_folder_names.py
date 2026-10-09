"""The Gmail folder names the pipeline files mail into must exist in Ali's 'Email Management - Labels' workbook."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))

import process_inbox_auto as pia  # noqa: E402

# The 22 folders of the workbook (tab "Labels and Functions").
WORKBOOK_FOLDERS = {
    "Account Recovery", "Application Notification", "Assessment", "Basecamp", "Client Screen", "Forwarded Emails",
    "Gmail Notification", "Google Sheet Request", "Instant Interview", "Interview Cancelled", "Interview follow up",
    "Interview Request", "Interview Rescheduled", "Job Alerts", "Job Invite", "Job Machine", "LinkedIn Notification",
    "More Information Needed", "Offers", "Phone Screen (HR or Recruiter)", "Rejections", "Technical Interview",
}
# Folders that stay until the interview categories are re-filed by type (plan step 3); not in the workbook.
UNTIL_REFILED = {"Interview Confirmation", "Final Interview Scheduled"}
# Kept on purpose: 3,000+ mails already sit in "More Information Request" and moving them is not worth it (Kes, 2026-10-09).
KEPT_NAME = {"More Information Request"}


def test_every_mapped_folder_is_a_workbook_folder():
    unknown = set(pia.CATEGORY_TO_FOLDER.values()) - WORKBOOK_FOLDERS - UNTIL_REFILED - KEPT_NAME
    assert not unknown, f"folders not in the workbook: {sorted(unknown)}"


def test_renamed_folders():
    m = pia.CATEGORY_TO_FOLDER
    assert m["Offer"] == "Offers"
    assert m["Rejection"] == "Rejections"
    assert m["More Information Request"] == "More Information Request"
    assert m["Background Check"] == "More Information Request"
    assert m["Interview Schedule"] == "Interview Request"


# --- sender rules: subdomains match, look-alikes do not -----------------------------------------------------------

def _pre(sender, subject="Hello"):
    return pia.pre_classify_by_sender({"sender_email": sender, "subject": subject, "body_content": ""})


def test_job_board_subdomains_are_job_alerts():
    assert _pre("Indeed <no-reply@alert.indeed.com>") == "Job Alert"
    assert _pre("jobs@jobalert.indeed.com") == "Job Alert"
    assert _pre("x@alert.refer.io") == "Job Alert"
    assert _pre("x@my.theladders.com") == "Job Alert"


def test_linkedin_and_basecamp_subdomains():
    assert _pre("LinkedIn <messages-noreply@linkedin.com>") == "LinkedIn Notification"
    assert _pre("jobs-listings@mail.linkedin.com") == "LinkedIn Notification"
    assert _pre("x@3.basecamp.com") == "Basecamp"
    assert _pre("x@basecamp.com") == "Basecamp"


def test_lookalike_domains_do_not_match():
    assert _pre("x@fakeindeed.com") is None
    assert _pre("x@indeed.com.evil.net") is None
    assert _pre("Indeed Jobs <recruiter@acme-staffing.com>") is None
    assert _pre("x@notlinkedin.com") is None
    assert _pre("x@mybasecamp.com") is None
