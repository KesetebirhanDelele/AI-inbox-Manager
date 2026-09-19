"""
Unit tests for fetch_students_sheet.add_new_student's validation guardrail.

2026-09-18: a body-text regex false-positive ("Ok", from ordinary prose, not
a real candidate name) got auto-persisted into config/students.py with no
email at all, because add_new_student() had no validation. These tests cover
only the rejection path (no name / no email / not enough info) -- it returns
before touching the filesystem, so no config file I/O is needed here. The
existing (pre-existing, unchanged) success path that writes to
config/students.py is intentionally not exercised by this file.
"""

from execution.fetch_students_sheet import add_new_student


class TestAddNewStudentValidation:
    """add_new_student must refuse to persist anything that doesn't look
    like a real, contactable person."""

    def test_rejects_missing_email(self):
        assert add_new_student(name="Ok", personal_email="") is None

    def test_rejects_email_without_at_sign(self):
        assert add_new_student(name="Jordan Smith", personal_email="not-an-email") is None

    def test_rejects_empty_name(self):
        assert add_new_student(name="", personal_email="jordan@example.com") is None

    def test_rejects_single_character_name(self):
        assert add_new_student(name="X", personal_email="jordan@example.com") is None

    def test_rejects_whitespace_only_name(self):
        assert add_new_student(name="   ", personal_email="jordan@example.com") is None

    def test_rejects_common_word_with_no_email(self):
        # The exact real-world case that created the bad "Ok" entry.
        assert add_new_student(name="Ok", personal_email="") is None
