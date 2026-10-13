"""
Shared pytest configuration and fixtures.

This file is automatically loaded by pytest and provides common fixtures
for all test files.
"""

import os
import pytest
from pathlib import Path


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for tests."""
    return tmp_path


@pytest.fixture
def mock_env(monkeypatch):
    """Fixture to easily mock environment variables."""
    def _set_env(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setenv(key, str(value))
    return _set_env


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    """Ensure tests run in dev mode by default."""
    monkeypatch.setenv("ENVIRONMENT", "test")

    # Prevent accidental production access
    if os.getenv("ENVIRONMENT") == "production":
        raise RuntimeError("Tests must never run against production!")


@pytest.fixture
def sample_data():
    """Provide sample test data."""
    return {
        "test_key": "test_value",
        "items": [1, 2, 3],
        "nested": {
            "value": "example"
        }
    }


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


# --- tests must never read the live roster sheet or GHL --------------------------------------------------------------------------------
# student_flags / student_roster read the real settings from .env; empty values stop that (load_dotenv never overrides a variable that is set).
@pytest.fixture(autouse=True)
def _never_reach_the_roster_sheet_or_ghl(monkeypatch):
    for key in ("STUDENT_ROSTER_SHEET_ID", "GHL_API_KEY", "GHL_LOCATION_ID"):
        monkeypatch.setenv(key, "")
    try:
        import student_roster, student_flags
        student_roster._CACHE.update(at=0.0, rows=None)
        student_flags._GHL_CACHE.clear()
    except ImportError:
        pass
