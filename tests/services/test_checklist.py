"""
Tests for checklist step definitions and checklist API logic.

Tests the checklist_steps.py definitions for correctness,
and the checklist router logic using an in-memory SQLite database
with test-local model definitions.
"""

import sys
import types
import pytest
from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Boolean,
    Float,
    DateTime,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Create a test-local Base for model definitions
TestBase = declarative_base()


# ============================================================================
# Test-local model definitions (mirror the dashboard models)
# ============================================================================


class Email(TestBase):
    __tablename__ = "emails"
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(String(255), unique=True, nullable=False)
    subject = Column(String(500), nullable=False)
    from_address = Column(String(255), nullable=False)
    received_date = Column(DateTime, nullable=False)
    body_preview = Column(String(500))
    full_body = Column(Text)
    current_folder = Column(String(100), default="INBOX")
    is_read = Column(Boolean, default=False)
    fetch_timestamp = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow)


class InterviewEvent(TestBase):
    __tablename__ = "interview_events"
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False)
    student_id = Column(Integer, nullable=True)
    sub_type = Column(String(100), nullable=False)
    company_name = Column(String(255))
    position_title = Column(String(255))
    contact_name = Column(String(255))
    contact_email = Column(String(255))
    contact_phone = Column(String(100))
    interview_date = Column(String(20))
    interview_time = Column(String(10))
    interview_timezone = Column(String(20))
    interview_format = Column(String(50))
    meeting_link = Column(Text)
    num_interviewers = Column(Integer)
    is_job_machine = Column(Boolean, default=False)
    is_next_round = Column(Boolean, default=False)
    confidence = Column(Float, nullable=False)
    raw_extraction = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    checklist_completions = relationship(
        "ChecklistCompletion", back_populates="interview_event",
        cascade="all, delete-orphan"
    )


class ChecklistCompletion(TestBase):
    __tablename__ = "checklist_completions"
    id = Column(Integer, primary_key=True, index=True)
    interview_event_id = Column(
        Integer, ForeignKey("interview_events.id"), nullable=False
    )
    step_key = Column(String(100), nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_by = Column(String(100))
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    interview_event = relationship(
        "InterviewEvent", back_populates="checklist_completions"
    )
    __table_args__ = (
        Index(
            "idx_checklist_event_step",
            "interview_event_id",
            "step_key",
            unique=True,
        ),
    )


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    TestBase.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_email(db_session):
    """Create a sample email record."""
    email = Email(
        email_id="test-email-001",
        subject="Interview with Acme Corp",
        from_address="hr@acme.com",
        received_date=datetime(2026, 1, 28, 10, 0, 0),
        body_preview="We'd like to schedule a phone screen...",
        current_folder="INBOX",
    )
    db_session.add(email)
    db_session.commit()
    return email


@pytest.fixture
def sample_interview_event(db_session, sample_email):
    """Create a sample interview event."""
    event = InterviewEvent(
        email_id=sample_email.id,
        sub_type="phone_screen",
        company_name="Acme Corp",
        position_title="Data Analyst",
        confidence=0.95,
    )
    db_session.add(event)
    db_session.commit()
    return event


# ============================================================================
# Import checklist_steps.py (add dashboard API to path)
# ============================================================================

import os

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "services",
        "dashboard",
        "api",
    ),
)

from checklist_steps import CHECKLIST_DEFINITIONS, get_all_step_keys, normalize_sub_type


# ============================================================================
# Tests: Step Definitions Config
# ============================================================================


class TestNormalizeSubType:
    """Tests for the normalize_sub_type helper."""

    def test_title_case_to_snake_case(self):
        """Title case DB values map to snake_case keys."""
        assert normalize_sub_type("Interview Request") == "interview_request"
        assert normalize_sub_type("Phone Screen") == "phone_screen"
        assert normalize_sub_type("Client Screen") == "client_screen"
        assert normalize_sub_type("Technical Interview") == "technical_interview"
        assert normalize_sub_type("Interview Cancelled") == "cancelled"
        assert normalize_sub_type("Interview Rescheduled") == "rescheduled"
        assert normalize_sub_type("Job Machine") == "job_machine"

    def test_snake_case_identity(self):
        """Snake_case values map to themselves."""
        assert normalize_sub_type("interview_request") == "interview_request"
        assert normalize_sub_type("phone_screen") == "phone_screen"
        assert normalize_sub_type("cancelled") == "cancelled"

    def test_unknown_returns_original(self):
        """Unknown values are returned as-is."""
        assert normalize_sub_type("SomeUnknownType") == "SomeUnknownType"

    def test_normalized_values_exist_in_definitions(self):
        """All normalized title case values exist as keys in CHECKLIST_DEFINITIONS."""
        title_case_types = [
            "Interview Request",
            "Phone Screen",
            "Client Screen",
            "Technical Interview",
            "Interview Cancelled",
            "Interview Rescheduled",
            "Job Machine",
        ]
        for tc in title_case_types:
            normalized = normalize_sub_type(tc)
            assert normalized in CHECKLIST_DEFINITIONS, (
                f"Normalized '{tc}' -> '{normalized}' not found in definitions"
            )


class TestChecklistDefinitions:
    """Tests for the hardcoded step definitions."""

    def test_all_seven_types_defined(self):
        """All 7 interview sub-types have checklist definitions."""
        expected_types = [
            "interview_request",
            "phone_screen",
            "client_screen",
            "technical_interview",
            "cancelled",
            "rescheduled",
            "job_machine",
        ]
        for sub_type in expected_types:
            assert sub_type in CHECKLIST_DEFINITIONS, (
                f"Missing definition for {sub_type}"
            )

    def test_each_type_has_steps(self):
        """Each type has at least one main step."""
        for sub_type, defn in CHECKLIST_DEFINITIONS.items():
            assert len(defn["steps"]) > 0, f"{sub_type} has no steps"

    def test_each_step_has_sub_steps(self):
        """Each main step has at least one sub-step."""
        for sub_type, defn in CHECKLIST_DEFINITIONS.items():
            for step in defn["steps"]:
                assert len(step["sub_steps"]) > 0, (
                    f"{sub_type}/{step['key']} has no sub-steps"
                )

    def test_step_keys_are_unique_within_type(self):
        """No duplicate keys within a single type."""
        for sub_type, defn in CHECKLIST_DEFINITIONS.items():
            keys = []
            for step in defn["steps"]:
                keys.append(step["key"])
                for sub in step["sub_steps"]:
                    keys.append(sub["key"])
            assert len(keys) == len(set(keys)), (
                f"Duplicate keys in {sub_type}: {keys}"
            )

    def test_step_keys_follow_convention(self):
        """All keys start with their sub_type prefix."""
        for sub_type, defn in CHECKLIST_DEFINITIONS.items():
            for step in defn["steps"]:
                assert step["key"].startswith(f"{sub_type}."), (
                    f"Key {step['key']} doesn't start with {sub_type}."
                )
                for sub in step["sub_steps"]:
                    assert sub["key"].startswith(f"{sub_type}."), (
                        f"Key {sub['key']} doesn't start with {sub_type}."
                    )

    def test_main_step_keys_match_pattern(self):
        """Main step keys follow {sub_type}.{n} pattern."""
        import re

        for sub_type, defn in CHECKLIST_DEFINITIONS.items():
            for step in defn["steps"]:
                assert re.match(
                    rf"^{re.escape(sub_type)}\.\d+$", step["key"]
                ), f"Invalid main step key format: {step['key']}"

    def test_sub_step_keys_match_pattern(self):
        """Sub-step keys follow {sub_type}.{n}.{m} pattern."""
        import re

        for sub_type, defn in CHECKLIST_DEFINITIONS.items():
            for step in defn["steps"]:
                for sub in step["sub_steps"]:
                    assert re.match(
                        rf"^{re.escape(sub_type)}\.\d+\.\d+$", sub["key"]
                    ), f"Invalid sub-step key format: {sub['key']}"

    def test_each_type_has_label(self):
        """Each definition has a human-readable label."""
        for sub_type, defn in CHECKLIST_DEFINITIONS.items():
            assert "label" in defn and len(defn["label"]) > 0, (
                f"{sub_type} missing label"
            )

    def test_each_type_has_sub_type_field(self):
        """Each definition's sub_type field matches its key."""
        for sub_type, defn in CHECKLIST_DEFINITIONS.items():
            assert defn["sub_type"] == sub_type, (
                f"Mismatched sub_type: key={sub_type}, field={defn['sub_type']}"
            )


class TestGetAllStepKeys:
    """Tests for the get_all_step_keys helper."""

    def test_returns_all_keys_for_phone_screen(self):
        """Returns main + sub-step keys for phone_screen."""
        keys = get_all_step_keys("phone_screen")
        assert "phone_screen.1" in keys
        assert "phone_screen.1.1" in keys
        assert "phone_screen.2" in keys
        assert "phone_screen.2.1" in keys
        assert "phone_screen.2.2" in keys

    def test_returns_keys_for_title_case_input(self):
        """Works with title case DB values via normalization."""
        keys = get_all_step_keys("Phone Screen")
        assert "phone_screen.1" in keys
        assert "phone_screen.1.1" in keys

    def test_unknown_type_uses_the_generic_checklist(self):
        """An unknown sub_type gets the generic "other" checklist instead of none."""
        keys = get_all_step_keys("nonexistent_type")
        assert keys == get_all_step_keys("other") and "other.2.3" in keys

    def test_key_count_matches_definitions(self):
        """Total keys equals main steps + sub-steps for each type."""
        for sub_type, defn in CHECKLIST_DEFINITIONS.items():
            expected_count = 0
            for step in defn["steps"]:
                expected_count += 1  # main step
                expected_count += len(step["sub_steps"])
            keys = get_all_step_keys(sub_type)
            assert len(keys) == expected_count, (
                f"{sub_type}: expected {expected_count} keys, got {len(keys)}"
            )


# ============================================================================
# Tests: Checklist Completion (Database Layer)
# ============================================================================


class TestChecklistCompletion:
    """Tests for checklist completion persistence."""

    def test_create_completion(self, db_session, sample_interview_event):
        """Can create a completion record."""
        comp = ChecklistCompletion(
            interview_event_id=sample_interview_event.id,
            step_key="phone_screen.1",
            is_completed=True,
            completed_by="admin",
            completed_at=datetime.utcnow(),
        )
        db_session.add(comp)
        db_session.commit()

        result = (
            db_session.query(ChecklistCompletion)
            .filter_by(interview_event_id=sample_interview_event.id)
            .first()
        )
        assert result is not None
        assert result.step_key == "phone_screen.1"
        assert result.is_completed is True
        assert result.completed_by == "admin"

    def test_toggle_completion_off(self, db_session, sample_interview_event):
        """Can toggle a completion record from True to False."""
        comp = ChecklistCompletion(
            interview_event_id=sample_interview_event.id,
            step_key="phone_screen.1",
            is_completed=True,
            completed_by="admin",
            completed_at=datetime.utcnow(),
        )
        db_session.add(comp)
        db_session.commit()

        # Toggle off
        comp.is_completed = False
        comp.completed_by = None
        comp.completed_at = None
        db_session.commit()

        result = (
            db_session.query(ChecklistCompletion)
            .filter_by(interview_event_id=sample_interview_event.id)
            .first()
        )
        assert result.is_completed is False
        assert result.completed_by is None

    def test_multiple_completions_per_event(
        self, db_session, sample_interview_event
    ):
        """Can create multiple completion records for different steps."""
        keys = ["phone_screen.1", "phone_screen.1.1", "phone_screen.2"]
        for key in keys:
            db_session.add(
                ChecklistCompletion(
                    interview_event_id=sample_interview_event.id,
                    step_key=key,
                    is_completed=True,
                    completed_by="admin",
                    completed_at=datetime.utcnow(),
                )
            )
        db_session.commit()

        results = (
            db_session.query(ChecklistCompletion)
            .filter_by(interview_event_id=sample_interview_event.id)
            .all()
        )
        assert len(results) == 3

    def test_unique_constraint(self, db_session, sample_interview_event):
        """Cannot create duplicate (interview_event_id, step_key) pairs."""
        comp1 = ChecklistCompletion(
            interview_event_id=sample_interview_event.id,
            step_key="phone_screen.1",
            is_completed=True,
        )
        db_session.add(comp1)
        db_session.commit()

        comp2 = ChecklistCompletion(
            interview_event_id=sample_interview_event.id,
            step_key="phone_screen.1",
            is_completed=False,
        )
        db_session.add(comp2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()

    def test_cascade_delete(self, db_session, sample_interview_event):
        """Deleting an interview event deletes its completions."""
        db_session.add(
            ChecklistCompletion(
                interview_event_id=sample_interview_event.id,
                step_key="phone_screen.1",
                is_completed=True,
            )
        )
        db_session.commit()

        db_session.delete(sample_interview_event)
        db_session.commit()

        results = db_session.query(ChecklistCompletion).all()
        assert len(results) == 0

    def test_progress_calculation(self, db_session, sample_interview_event):
        """Can calculate progress from completion records."""
        all_keys = get_all_step_keys("phone_screen")

        # Complete 2 out of all keys
        for key in all_keys[:2]:
            db_session.add(
                ChecklistCompletion(
                    interview_event_id=sample_interview_event.id,
                    step_key=key,
                    is_completed=True,
                    completed_by="admin",
                    completed_at=datetime.utcnow(),
                )
            )
        db_session.commit()

        completed = (
            db_session.query(ChecklistCompletion)
            .filter_by(
                interview_event_id=sample_interview_event.id,
                is_completed=True,
            )
            .count()
        )
        total = len(all_keys)
        progress = round((completed / total * 100) if total > 0 else 0, 1)

        assert completed == 2
        assert total > 2
        assert 0 < progress < 100

    def test_different_events_have_independent_checklists(
        self, db_session, sample_email
    ):
        """Two interview events have separate checklist states."""
        event1 = InterviewEvent(
            email_id=sample_email.id,
            sub_type="phone_screen",
            company_name="Company A",
            confidence=0.95,
        )
        event2 = InterviewEvent(
            email_id=sample_email.id,
            sub_type="client_screen",
            company_name="Company B",
            confidence=0.90,
        )
        db_session.add_all([event1, event2])
        db_session.commit()

        db_session.add(
            ChecklistCompletion(
                interview_event_id=event1.id,
                step_key="phone_screen.1",
                is_completed=True,
            )
        )
        db_session.commit()

        event1_completions = (
            db_session.query(ChecklistCompletion)
            .filter_by(interview_event_id=event1.id)
            .count()
        )
        event2_completions = (
            db_session.query(ChecklistCompletion)
            .filter_by(interview_event_id=event2.id)
            .count()
        )
        assert event1_completions == 1
        assert event2_completions == 0
