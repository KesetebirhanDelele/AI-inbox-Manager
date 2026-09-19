"""
Fetch student data from the Colaberry students Google Sheet.

Reads the public Google Sheet as CSV and provides lookup by student name
or email. Used to resolve which student an interview email is for and
find their assigned assistant contact details.

Design principles:
- Fetches sheet as CSV (no API keys required — sheet is public)
- Caches results to avoid repeated HTTP requests per run
- Deterministic matching logic (no AI)
"""

import importlib.util
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Load students directly from config/students.py by file path to avoid
# sys.path collisions with same-named modules in other service directories.
_students_path = Path(__file__).parent.parent / "config" / "students.py"
_spec = importlib.util.spec_from_file_location("_students_config", _students_path)
_students_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_students_mod)
STUDENTS = _students_mod.STUDENTS
CC_EMAILS = _students_mod.CC_EMAILS


def get_all_students(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Return all students from the config file."""
    return STUDENTS


def _normalize_name(name: str) -> str:
    """Lowercase, strip, remove extra spaces."""
    return re.sub(r"\s+", " ", name.lower().strip())


def find_student_by_name(name_hint: str) -> Optional[Dict[str, Any]]:
    """
    Find a student by approximate name match.

    Tries exact match first, then partial match (first name or last name).

    Args:
        name_hint: Name extracted from email body

    Returns:
        Matching student dict or None
    """
    if not name_hint:
        return None

    students = get_all_students()
    normalized_hint = _normalize_name(name_hint)

    # 1. Exact full name match
    for s in students:
        if _normalize_name(s["name"]) == normalized_hint:
            logger.info(f"Exact name match: {s['name']}")
            return s

    # 2. Partial match — hint is contained in student name or vice versa
    hint_parts = set(normalized_hint.split())
    for s in students:
        student_parts = set(_normalize_name(s["name"]).split())
        # If all hint words appear in the student name
        if hint_parts and hint_parts.issubset(student_parts):
            logger.info(f"Partial name match: {s['name']} (hint: {name_hint})")
            return s

    # 3. First name only match
    hint_first = normalized_hint.split()[0] if normalized_hint else ""
    if hint_first:
        for s in students:
            student_first = _normalize_name(s["name"]).split()[0]
            if student_first == hint_first:
                logger.info(f"First-name match: {s['name']} (hint: {name_hint})")
                return s

    logger.warning(f"No student match found for name hint: '{name_hint}'")
    return None


def find_student_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Find a student by their personal email address.

    Args:
        email: Email address to look up

    Returns:
        Matching student dict or None
    """
    if not email:
        return None

    students = get_all_students()
    email_lower = email.lower().strip()

    for s in students:
        if s["personal_email"].lower().strip() == email_lower:
            logger.info(f"Email match: {s['name']} ({email})")
            return s

    logger.warning(f"No student found for email: {email}")
    return None


def add_new_student(name: str, personal_email: str, phone: str = "") -> Optional[Dict[str, Any]]:
    """
    Add a new student to config/students.py and return their record.

    New students default to Karthik as assigned assistant.
    An admin can manually update the assignment in config/students.py later.

    Args:
        name: Student full name
        personal_email: Student's personal email address
        phone: Student's phone number (optional)

    Returns:
        The new student dict, or None if name/email don't look real enough to
        persist (caller already treats None as "student not found" and skips
        the notification — see notify_student.py).
    """
    # 2026-09-18: a body-text regex false-positive ("Ok" from ordinary prose,
    # not a real candidate name) got auto-persisted into config/students.py
    # with no email at all, because this function had no validation. Refuse
    # anything that doesn't look like a real, contactable person rather than
    # writing garbage into the source of truth for notification routing.
    if not name or len(name.strip()) < 2 or not personal_email or "@" not in personal_email:
        logger.warning(
            f"Refusing to auto-add student with insufficient info: "
            f"name={name!r} personal_email={personal_email!r}"
        )
        return None
    new_student = {
        "name": name,
        "personal_email": personal_email,
        "phone": phone,
        "assigned_to": "Karthik",
        "assistant_email": "karthik@colaberry.com",
        "cc_emails": CC_EMAILS,
    }

    # Append to in-memory list immediately
    STUDENTS.append(new_student)

    # Persist to config/students.py
    config_path = Path(__file__).parent.parent / "config" / "students.py"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        new_entry = (
            f'    {{"name": "{name}", "personal_email": "{personal_email}", '
            f'"phone": "{phone}", "assigned_to": "Karthik", '
            f'"assistant_email": "karthik@colaberry.com"}},\n'
        )

        # Insert before the closing bracket of STUDENTS list
        content = content.replace(
            "]\n\n# Always CC",
            f"{new_entry}]\n\n# Always CC",
        )

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"New student added to config/students.py: {name} ({personal_email})")
    except Exception as e:
        logger.error(f"Failed to persist new student to config: {e}")

    return new_student
