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


def test_every_mapped_folder_is_a_workbook_folder():
    unknown = set(pia.CATEGORY_TO_FOLDER.values()) - WORKBOOK_FOLDERS - UNTIL_REFILED
    assert not unknown, f"folders not in the workbook: {sorted(unknown)}"


def test_renamed_folders():
    m = pia.CATEGORY_TO_FOLDER
    assert m["Offer"] == "Offers"
    assert m["Rejection"] == "Rejections"
    assert m["More Information Request"] == "More Information Needed"
    assert m["Background Check"] == "More Information Needed"
    assert m["Interview Schedule"] == "Interview Request"
