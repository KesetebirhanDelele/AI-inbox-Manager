"""
Test infrastructure for the dashboard API.

Sets up:
  - In-memory SQLite test database (StaticPool, shared across connections)
  - FastAPI TestClient with get_db overridden to use test DB
  - Auth session fixture (bypasses bcrypt login for speed)
  - Data factory helpers used by individual test modules
"""

import os
import sys
import uuid
from datetime import datetime, timedelta

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── 1. Env vars MUST be set before any app module is imported ──────────────
_TEST_PASSWORD = "testpass123"
_TEST_HASH = bcrypt.hashpw(_TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()

os.environ.setdefault("ADMIN_PASSWORD_HASH", _TEST_HASH)
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SESSION_SECRET", "test-secret-key")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_inbox_api_tmp.db")

# ── 2. Add API directory to path ───────────────────────────────────────────
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# ── 3. Import app modules AFTER env vars are set ──────────────────────────
from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models import (  # noqa: E402
    Approval,
    ChecklistCompletion,
    Classification,
    Email,
    InterviewEvent,
    NotificationDraft,
    ProcessRun,
    Student,
    SystemConfig,
    UserSession,
    WhitelistCompany,
)

# ── 4. Test engine (in-memory SQLite, shared via StaticPool) ───────────────
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


# ── 5. Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db():
    """Fresh DB for each test: create all tables, yield session, drop all."""
    Base.metadata.create_all(bind=_test_engine)
    session = _TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
    Base.metadata.drop_all(bind=_test_engine)


@pytest.fixture(scope="function")
def client(db):
    """TestClient sharing the same DB session as the test."""
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_token(db):
    """Insert a valid admin session and return its token."""
    token = str(uuid.uuid4())
    session = UserSession(
        session_token=token,
        username="testadmin",
        role="admin",
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=24),
        last_activity=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    return token


@pytest.fixture
def auth_cookies(auth_token):
    """Cookie dict for authenticated requests."""
    return {"session_token": auth_token}


# ── 6. Data factory helpers (imported by test modules) ────────────────────

def make_email(
    db,
    email_id="msg001",
    subject="Test Email",
    from_address="recruiter@example.com",
    folder="INBOX",
    received_date=None,
):
    email = Email(
        email_id=email_id,
        subject=subject,
        from_address=from_address,
        received_date=received_date or datetime.utcnow(),
        body_preview="This is a test email preview.",
        current_folder=folder,
        is_read=False,
    )
    db.add(email)
    db.commit()
    db.refresh(email)
    return email


def make_classification(db, email, category="Job Alert", confidence=0.95, company="Acme Corp"):
    clf = Classification(
        email_id=email.id,
        category=category,
        confidence=confidence,
        company_name=company,
        position="Data Analyst",
        classification_timestamp=datetime.utcnow(),
    )
    db.add(clf)
    db.commit()
    db.refresh(clf)
    return clf


def make_approval(db, email, classification, status="pending"):
    approval = Approval(
        email_id=email.id,
        classification_id=classification.id,
        status=status,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def make_process_run(db, total_emails=50, status="success", run_timestamp=None, gpt_cost=0.01):
    run = ProcessRun(
        run_timestamp=run_timestamp or datetime.utcnow(),
        total_emails=total_emails,
        interview_requests=2,
        organized=20,
        spam_deleted=5,
        categories_breakdown={"Job Alert": 10, "Interview Request": 2},
        duration_seconds=45.0,
        gpt_cost_usd=gpt_cost,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def make_student(db, username="jdoe", full_name="John Doe", personal_email="john@example.com"):
    student = Student(
        username=username,
        full_name=full_name,
        personal_email=personal_email,
        assigned_gmail=f"{username}@gmail.com",
        is_active=True,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def make_interview_event(
    db,
    email,
    student=None,
    sub_type="Phone Screen",
    company="Acme Corp",
    interview_date="2099-04-15",
):
    event = InterviewEvent(
        email_id=email.id,
        student_id=student.id if student else None,
        sub_type=sub_type,
        company_name=company,
        position_title="Data Analyst",
        interview_date=interview_date,
        interview_time="14:00",
        interview_timezone="CST",
        interview_format="video",
        confidence=0.92,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def make_whitelist_entry(db, company="Acme Corp", added_by="system"):
    entry = WhitelistCompany(
        company_name=company.lower(),
        added_by=added_by,
        notes="Test entry",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def make_notification_draft(
    db,
    interview_event,
    email_status="draft",
    recipient_email="student@example.com",
    subject="Interview Notification",
    body="You have an interview.",
    auto_send_eligible=False,
):
    draft = NotificationDraft(
        interview_event_id=interview_event.id,
        template_id="phone_screen_v1",
        email_subject=subject,
        email_body=body,
        recipient_email=recipient_email,
        email_status=email_status,
        auto_send_eligible=auto_send_eligible,
        missing_fields=[],
        created_at=datetime.utcnow(),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def make_system_config(db, key, value, updated_by="system"):
    config = SystemConfig(
        key=key,
        value=str(value),
        updated_at=datetime.utcnow(),
        updated_by=updated_by,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


# --- tests must never send real email -----------------------------------------------------------------------------------------------
# send_notification.py loads the developer's real SMTP login from .env, so any test that reaches an unmocked send would email a real
# address (it did: "Interview Notification / You have an interview." to student@example.com, 2026-10-09). send_email swallows every
# exception, so the guard records the attempt and fails the TEST afterwards.
@pytest.fixture(autouse=True)
def _never_open_a_real_smtp_connection(monkeypatch):
    import smtplib

    attempts = []

    def _record(*args, **kwargs):
        attempts.append(args[:1])
        raise ConnectionError("blocked: tests must not open a real SMTP connection")

    monkeypatch.setattr(smtplib, "SMTP", _record)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _record)
    yield
    assert not attempts, "This test tried to open a real SMTP connection (it would have emailed a real address): mock send_email in it"
