"""
Unit tests for email_templates.py and draft_notification.py

Tests template selection, placeholder population, WhatsApp message
generation, and the full drafting pipeline.
"""

import pytest
from execution.email_templates import (
    select_template,
    get_template_by_id,
    list_all_templates,
    TEMPLATES,
)
from execution.draft_notification import (
    format_interview_datetime,
    build_template_data,
    populate_template,
    draft_notification,
)


# --- Helpers ---

SAMPLE_CLASSIFICATION = {
    "interview_sub_type": "Phone Screen",
    "job_machine_sub_type": None,
    "company_name": "TechCorp",
    "position_title": "Data Analyst",
    "contact_name": "Jane Smith",
    "contact_title": "HR Manager",
    "contact_email": "jane@techcorp.com",
    "contact_phone": "555-1234",
    "interview_date": "2026-03-01",
    "interview_time": "14:00",
    "interview_timezone": "CST",
    "interview_format": "phone",
    "num_interviewers": 1,
    "is_job_machine": False,
    "is_next_round": False,
    "confidence": 0.95,
}

SAMPLE_STUDENT = {
    "full_name": "John Doe",
    "personal_email": "john.personal@hotmail.com",
    "assigned_gmail": "john.doe@gmail.com",
    "phone_number": "555-9999",
    "student_gmail": "john.doe@gmail.com",
}


# ============================================================================
# Template Selection Tests
# ============================================================================


class TestTemplateRegistry:
    """Test template constants."""

    def test_templates_not_empty(self):
        assert len(TEMPLATES) > 0

    def test_all_templates_have_required_fields(self):
        for tid, template in TEMPLATES.items():
            assert template.template_id, f"Missing template_id for {tid}"
            assert template.template_name, f"Missing template_name for {tid}"
            assert template.subject_template, f"Missing subject for {tid}"
            assert template.body_template, f"Missing body for {tid}"

    def test_get_template_by_id(self):
        template = get_template_by_id("interview_request_first")
        assert template is not None
        assert template.template_name == "Interview Request (First)"

    def test_get_nonexistent_template(self):
        assert get_template_by_id("nonexistent") is None

    def test_list_all_templates(self):
        templates = list_all_templates()
        assert len(templates) == len(TEMPLATES)


class TestSelectTemplate:
    """Test deterministic template selection."""

    def test_interview_request_first(self):
        t = select_template("Interview Request")
        assert t.template_id == "interview_request_first"

    def test_interview_request_first_jm(self):
        t = select_template("Interview Request", is_job_machine=True)
        assert t.template_id == "interview_request_first_jm"

    def test_interview_request_next_round(self):
        t = select_template("Interview Request", is_next_round=True)
        assert t.template_id == "next_round_request"

    def test_phone_screen(self):
        t = select_template("Phone Screen")
        assert t.template_id == "phone_screening_scheduled"

    def test_phone_screen_jm(self):
        t = select_template("Phone Screen", is_job_machine=True)
        assert t.template_id == "phone_screening_scheduled_jm"

    def test_client_screen(self):
        t = select_template("Client Screen")
        assert t.template_id == "client_screening_scheduled"

    def test_client_screen_jm(self):
        t = select_template("Client Screen", is_job_machine=True)
        assert t.template_id == "client_screening_scheduled_jm"

    def test_technical_interview(self):
        t = select_template("Technical Interview")
        assert t.template_id == "technical_round_scheduled"

    def test_technical_interview_jm(self):
        t = select_template("Technical Interview", is_job_machine=True)
        assert t.template_id == "technical_round_scheduled_jm"

    def test_cancelled(self):
        t = select_template("Interview Cancelled")
        assert t.template_id == "interview_reschedule_request"

    def test_rescheduled(self):
        t = select_template("Interview Rescheduled")
        assert t.template_id == "interview_rescheduled"

    def test_assessment(self):
        t = select_template("Interview Request", is_assessment=True)
        assert t.template_id == "next_round_assessment"

    def test_job_machine_unresolved(self):
        """Job Machine without resolved sub-type returns None."""
        t = select_template("Job Machine")
        assert t is None

    def test_unknown_sub_type(self):
        t = select_template("Unknown Type")
        assert t is None


# ============================================================================
# Datetime Formatting Tests
# ============================================================================


class TestFormatInterviewDatetime:
    """Test datetime formatting."""

    def test_full_datetime(self):
        result = format_interview_datetime("2026-03-01", "14:00", "CST")
        assert result == "2026-03-01 at 14:00 CST"

    def test_date_and_time(self):
        result = format_interview_datetime("2026-03-01", "09:30")
        assert result == "2026-03-01 at 09:30"

    def test_date_only(self):
        result = format_interview_datetime("2026-03-01", None)
        assert result == "2026-03-01"

    def test_no_date(self):
        result = format_interview_datetime(None, None)
        assert result == "TBD"

    def test_no_date_with_time(self):
        result = format_interview_datetime(None, "14:00")
        assert result == "TBD"


# ============================================================================
# Template Data Building Tests
# ============================================================================


class TestBuildTemplateData:
    """Test template data building."""

    def test_all_fields_populated(self):
        data = build_template_data(SAMPLE_CLASSIFICATION, SAMPLE_STUDENT)

        assert data["student_name"] == "John Doe"
        assert data["assigned_gmail"] == "john.doe@gmail.com"
        assert data["company_name"] == "TechCorp"
        assert data["position_title"] == "Data Analyst"
        assert data["contact_name"] == "Jane Smith"
        assert data["interview_datetime"] == "2026-03-01 at 14:00 CST"
        assert data["assistant_name"] == "Robelyn"

    def test_custom_assistant_name(self):
        data = build_template_data(
            SAMPLE_CLASSIFICATION, SAMPLE_STUDENT, assistant_name="TestAssistant"
        )
        assert data["assistant_name"] == "TestAssistant"

    def test_missing_student_name_defaults(self):
        student = {"personal_email": "test@test.com"}
        data = build_template_data(SAMPLE_CLASSIFICATION, student)
        assert data["student_name"] == "Student"

    def test_missing_fields_are_empty_strings(self):
        data = build_template_data({}, {})
        assert data["company_name"] == ""
        assert data["contact_name"] == ""


# ============================================================================
# Template Population Tests
# ============================================================================


class TestPopulateTemplate:
    """Test template placeholder population."""

    def test_all_fields_filled(self):
        template = get_template_by_id("phone_screening_scheduled")
        data = build_template_data(SAMPLE_CLASSIFICATION, SAMPLE_STUDENT)

        result = populate_template(template, data)

        assert "TechCorp" in result["subject"]
        assert "John Doe" in result["body"]
        assert "2026-03-01 at 14:00 CST" in result["body"]
        assert result["missing_fields"] == []

    def test_missing_required_field_detected(self):
        template = get_template_by_id("phone_screening_scheduled")
        data = build_template_data(
            {"company_name": "Acme"},  # Missing most fields
            {"full_name": "Bob"},
        )

        result = populate_template(template, data)

        assert len(result["missing_fields"]) > 0
        # interview_datetime should be missing since no date provided
        assert "interview_datetime" in result["missing_fields"]

    def test_unfilled_placeholders_shown_as_brackets(self):
        template = get_template_by_id("interview_request_first")
        data = {
            "student_name": "Alice",
            "company_name": "BigCo",
            "position_title": "",
            "assigned_gmail": "alice@gmail.com",
            "contact_name": "",
            "assistant_name": "Robelyn",
            "contact_title": "",
            "contact_email": "",
            "contact_phone": "",
            "job_description_url": "",
        }

        result = populate_template(template, data)

        assert "[position_title]" in result["body"]
        assert "[contact_name]" in result["body"]


# ============================================================================
# Full Draft Pipeline Tests
# ============================================================================


class TestDraftNotification:
    """Test the full drafting pipeline."""

    def test_phone_screen_draft(self):
        result = draft_notification(SAMPLE_CLASSIFICATION, SAMPLE_STUDENT)

        assert result["template_id"] == "phone_screening_scheduled"
        assert result["email_subject"].startswith("Your interview on")        # plain subject, no company or title
        assert result["email_body"].splitlines()[0] == "[Interview Notification]"
        assert "TechCorp" in result["email_body"] and "Hello John," in result["email_body"]
        assert result["recipient_email"] == "john.personal@hotmail.com"
        assert result["bcc"] == "c_interviews@colaberry.com"
        assert result["draft_status"] == "ready"
        assert result["missing_fields"] == []

    def test_interview_request_draft(self):
        classification = {
            **SAMPLE_CLASSIFICATION,
            "interview_sub_type": "Interview Request",
            "interview_date": None,
            "is_job_machine": False,
            "is_next_round": False,
        }
        result = draft_notification(classification, SAMPLE_STUDENT)

        assert result["template_id"] == "interview_request_first"
        assert result["draft_status"] == "ready"

    def test_job_machine_interview_resolved(self):
        classification = {
            **SAMPLE_CLASSIFICATION,
            "interview_sub_type": "Job Machine",
            "job_machine_sub_type": "interview",
            "is_job_machine": True,
            "interview_date": None,
        }
        result = draft_notification(classification, SAMPLE_STUDENT)

        # Should resolve to Interview Request via JM
        assert result["template_id"] == "interview_request_first_jm"

    def test_job_machine_reschedule_resolved(self):
        classification = {
            **SAMPLE_CLASSIFICATION,
            "interview_sub_type": "Job Machine",
            "job_machine_sub_type": "reschedule",
            "is_job_machine": True,
        }
        result = draft_notification(classification, SAMPLE_STUDENT)

        assert result["template_id"] == "interview_rescheduled"

    def test_job_machine_cancellation_resolved(self):
        classification = {
            **SAMPLE_CLASSIFICATION,
            "interview_sub_type": "Job Machine",
            "job_machine_sub_type": "cancellation",
            "is_job_machine": True,
        }
        result = draft_notification(classification, SAMPLE_STUDENT)

        assert result["template_id"] == "interview_reschedule_request"

    def test_job_machine_scheduled_resolved(self):
        """Job Machine with confirmed date should use Phone Screen JM template."""
        classification = {
            **SAMPLE_CLASSIFICATION,
            "interview_sub_type": "Job Machine",
            "job_machine_sub_type": "interview",
            "is_job_machine": True,
            "interview_date": "2026-03-01",
        }
        result = draft_notification(classification, SAMPLE_STUDENT)

        assert result["template_id"] == "phone_screening_scheduled_jm"

    def test_missing_fields_triggers_needs_review(self):
        classification = {
            "interview_sub_type": "Phone Screen",
            "company_name": "Acme",
            # Missing most required fields
        }
        student = {"full_name": "Bob"}

        result = draft_notification(classification, student)

        assert result["draft_status"] == "needs_review"
        assert len(result["missing_fields"]) > 0

    def test_cancelled_draft(self):
        classification = {
            **SAMPLE_CLASSIFICATION,
            "interview_sub_type": "Interview Cancelled",
        }
        result = draft_notification(classification, SAMPLE_STUDENT)

        assert result["template_id"] == "interview_reschedule_request"
        assert "cancelled" in result["email_subject"].lower()
        assert "new time" in result["email_body"]                              # the old reschedule-request nuance is kept

    def test_rescheduled_draft(self):
        classification = {
            **SAMPLE_CLASSIFICATION,
            "interview_sub_type": "Interview Rescheduled",
        }
        result = draft_notification(classification, SAMPLE_STUDENT)

        assert result["template_id"] == "interview_rescheduled"

    def test_next_round_draft(self):
        classification = {
            **SAMPLE_CLASSIFICATION,
            "interview_sub_type": "Interview Request",
            "is_next_round": True,
        }
        result = draft_notification(classification, SAMPLE_STUDENT)

        assert result["template_id"] == "next_round_request"

    def test_custom_assistant_name(self):
        result = draft_notification(
            SAMPLE_CLASSIFICATION,
            SAMPLE_STUDENT,
            assistant_name="CustomAssistant",
        )
        assert "CustomAssistant" not in result["email_body"]                   # the notification is signed by the team, not a person
        assert result["email_body"].rstrip().endswith("Colaberry Interview Support")

    def test_no_personal_email(self):
        student = {**SAMPLE_STUDENT, "personal_email": None}
        result = draft_notification(SAMPLE_CLASSIFICATION, student)

        assert result["recipient_email"] == ""
