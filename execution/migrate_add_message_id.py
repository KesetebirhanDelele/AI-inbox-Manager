"""
One-off, idempotent migration for the dashboard `emails` table.

Context
-------
`emails.email_id` was used as the dedup key when importing classified emails,
but it stores the IMAP *message sequence number* (1, 2, 3 ...), which every IMAP
session re-assigns. New emails collided with old rows, so `import_email_to_db()`
kept hitting its "already exists" branch (or, after the unique constraint was in
play, failed outright) and nothing was inserted after 2026-06-29.

This migration:
  1. adds `emails.message_id` (the RFC 5322 Message-ID header — stable, unique),
  2. makes the message_id index UNIQUE, and
  3. drops the bogus UNIQUE constraint on `emails.email_id`.

The same logic runs automatically on every processing run via
`process_inbox_auto._ensure_schema()`; this script just lets you apply it now,
by hand, against production.

Safe to run repeatedly. Works on PostgreSQL (Neon) and SQLite.

Usage
-----
    python execution/migrate_add_message_id.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")
sys.path.insert(0, str(project_root / "execution"))

from db_url import normalize_db_url  # noqa: E402
from process_inbox_auto import _ensure_schema  # noqa: E402


def _database_url() -> str:
    url = normalize_db_url(os.getenv("DATABASE_URL"))
    if url:
        return url
    db_path = project_root / "services" / "dashboard" / "api" / "email_dashboard.db"
    return f"sqlite:///{db_path}"


if __name__ == "__main__":
    engine = create_engine(_database_url())
    _ensure_schema(engine)
    engine.dispose()
    print("Migration complete.")
    sys.exit(0)
