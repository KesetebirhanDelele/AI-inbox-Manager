"""Readable email text for the API. The cleaning itself lives in execution/text_cleaning.py (shared with the mail pipeline)."""
import sys
from pathlib import Path

_EXEC_DIR = str(Path(__file__).resolve().parents[3] / "execution")
if _EXEC_DIR not in sys.path:
    sys.path.insert(0, _EXEC_DIR)

from text_cleaning import clean_email_text, clean_preview, looks_like_html  # noqa: E402,F401
