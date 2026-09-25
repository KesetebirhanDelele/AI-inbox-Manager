"""
Unit tests for execution/db_url.py and process_inbox_auto's DB-error tracking.

Regression coverage for the 2026-09-24 incident: an unpinned SQLAlchemy
upgrade (2.0.54 -> 2.1.0) changed the default driver for bare
``postgresql://`` URLs to psycopg v3, which isn't installed. Every DB write
failed with ``No module named 'psycopg'``, but because DB writes are
best-effort the GitHub Actions runs stayed green and the dashboard silently
showed 0 emails for ~18 h.

The fix pins the driver explicitly in the URL and surfaces DB failures as
``stats["db_error"]`` so main() can alert on them.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

from db_url import normalize_db_url  # noqa: E402


# ── normalize_db_url ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("postgresql://u:p@host/db?sslmode=require",
         "postgresql+psycopg2://u:p@host/db?sslmode=require"),
        ("postgres://u:p@host/db", "postgresql+psycopg2://u:p@host/db"),
        # Already names a driver -> left alone
        ("postgresql+psycopg2://u:p@host/db", "postgresql+psycopg2://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        # Non-Postgres -> left alone
        ("sqlite:///some/path.db", "sqlite:///some/path.db"),
    ],
)
def test_normalize_db_url(raw, expected):
    assert normalize_db_url(raw) == expected


@pytest.mark.parametrize("empty", [None, ""])
def test_normalize_db_url_passes_empty_through(empty):
    assert normalize_db_url(empty) == empty


def test_normalized_url_resolves_to_psycopg2_driver():
    """The installed SQLAlchemy must pick psycopg2, whatever its default is."""
    url = make_url(normalize_db_url("postgresql://u:p@host/db"))
    assert url.get_dialect().driver == "psycopg2"


# ── DB error tracking in process_inbox_auto ──────────────────────────────────

@pytest.fixture
def pia(monkeypatch):
    import process_inbox_auto as mod
    monkeypatch.setattr(mod, "_db_session", None)
    monkeypatch.setattr(mod, "_db_engine", None)
    monkeypatch.setattr(mod, "_db_error", None)
    return mod


def test_get_db_session_records_init_failure(pia, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    def boom(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'psycopg'")

    monkeypatch.setattr("sqlalchemy.create_engine", boom)

    assert pia.get_db_session() is None
    assert "No module named 'psycopg'" in pia._db_error


def test_get_db_session_passes_psycopg2_url_to_engine(pia, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    seen = {}

    def fake_create_engine(url, **kwargs):
        seen["url"] = url
        raise RuntimeError("stop here")  # don't actually connect

    monkeypatch.setattr("sqlalchemy.create_engine", fake_create_engine)
    pia.get_db_session()

    assert seen["url"] == "postgresql+psycopg2://u:p@host/db"


def test_record_db_error_keeps_first_error(pia):
    pia._record_db_error("first")
    pia._record_db_error("second")
    assert pia._db_error == "first"


def test_log_process_run_records_failure(pia, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    def boom(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'psycopg'")

    monkeypatch.setattr("sqlalchemy.create_engine", boom)
    pia._log_process_run({"timestamp": "20260925_161300"})

    assert pia._db_error is not None
    assert "_log_process_run failed" in pia._db_error
