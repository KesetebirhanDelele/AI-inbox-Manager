"""
Normalize a DATABASE_URL into a SQLAlchemy URL with an explicit driver.

Why: SQLAlchemy 2.1 changed the default DBAPI for bare ``postgresql://`` URLs
from psycopg2 to psycopg (v3). We only install ``psycopg2-binary``, so an
unpinned upgrade (2026-09-24) made every DB write fail with
``No module named 'psycopg'``. Naming the driver explicitly keeps the pipeline
working regardless of the SQLAlchemy version installed.
"""

from typing import Optional

_PSYCOPG2_SCHEME = "postgresql+psycopg2://"


def normalize_db_url(url: Optional[str]) -> Optional[str]:
    """Return ``url`` with ``postgres://`` / ``postgresql://`` pinned to psycopg2.

    URLs that already name a driver (``postgresql+...://``) and non-Postgres
    URLs (e.g. ``sqlite:///...``) are returned unchanged. ``None``/empty
    passes through so callers can keep their own fallback logic.
    """
    if not url:
        return url
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return _PSYCOPG2_SCHEME + url[len(prefix):]
    return url
