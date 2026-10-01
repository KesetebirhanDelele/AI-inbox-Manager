"""
Student interview notification orchestrator.

When an interview request is detected, this script:
1. Looks up the student in the Google Sheet by name
2. Drafts the notification email using the existing template system
3. Sends the email from c_interviews@colaberry.com signed by the assigned assistant
4. CC's Shemika (mika@colaberry.com) and Jackie (jackie@colaberry.com)

Design principles:
- Deterministic orchestration (no AI)
- Sends via c_interviews@colaberry.com (Option A)
- Graceful failure — logs errors but never crashes the main pipeline
"""

import logging
import os
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load env
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

logger = logging.getLogger(__name__)

# CC always included on every notification
ALWAYS_CC = ["mika@colaberry.com", "jackie@colaberry.com"]

# Sender display name (emails come FROM c_interviews but signed by assistant)
FROM_EMAIL = os.getenv("EMAIL_ADDRESS", "c_interviews@colaberry.com")
FROM_NAME = "Colaberry Interview Support"


def _extract_student_email(email_data: Dict[str, Any]) -> str:
    """Try to find the student's personal email from email headers or CC fields."""
    import re
    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    central = "c_interviews@colaberry.com"

    # Check forwarding headers
    headers = email_data.get("headers", {}) or {}
    for key in ["Delivered-To", "X-Forwarded-To", "X-Original-To"]:
        val = headers.get(key, "")
        emails = EMAIL_RE.findall(val)
        for e in emails:
            if e.lower() != central:
                return e

    # Check To/CC addresses
    for addr in (email_data.get("to_addresses", []) or []):
        if addr.lower().strip() != central and "@" in addr:
            return addr.strip()

    return ""


def _get_student_info(classification: Dict[str, Any], email_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Look up student by name. If not found, auto-add them using extracted email.
    """
    from fetch_students_sheet import find_student_by_name, add_new_student

    # Try name from GPT classification first
    extracted = classification.get("extracted_data", {}) or {}
    candidate_name = (
        extracted.get("candidate_name")
        or extracted.get("student_name")
        or classification.get("candidate_name")
    )

    if candidate_name:
        student = find_student_by_name(candidate_name)
        if student:
            return student

    # Fallback: try extracting name from email body/subject
    from resolve_student import find_student_name_in_body
    body = email_data.get("body", "") or email_data.get("body_content", "") or ""
    subject = email_data.get("subject", "") or ""
    name_hint = find_student_name_in_body(body) or find_student_name_in_body(subject)

    if name_hint:
        student = find_student_by_name(name_hint)
        if student:
            return student

    # Student not found — auto-add if we have enough info
    final_name = candidate_name or name_hint
    if final_name:
        student_email = _extract_student_email(email_data)
        logger.info(f"New student detected: '{final_name}' — auto-adding to config")
        return add_new_student(name=final_name, personal_email=student_email)

    logger.warning("Could not identify student for notification")
    return None


def _build_student_info_for_draft(student: Dict[str, Any]) -> Dict[str, Any]:
    """Convert sheet student dict to the format expected by draft_notification."""
    return {
        "full_name": student["name"],
        "personal_email": student["personal_email"],
        "phone_number": student["phone"],
        "assigned_gmail": None,  # students use personal email for notifications
        "student_gmail": None,
    }


def _build_classification_for_draft(
    classification: Dict[str, Any],
    email_data: Dict[str, Any],
    sub_classification: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a classification dict compatible with draft_notification.

    When the interview sub-classifier ran, its type and flags pick the template.
    Without it the draft falls back to the first-interview template.
    """
    extracted = classification.get("extracted_data", {}) or {}
    sub = sub_classification or {}
    return {
        "interview_sub_type": sub.get("interview_sub_type") or "Interview Request",
        "job_machine_sub_type": sub.get("job_machine_sub_type"),
        "is_job_machine": bool(sub.get("is_job_machine", False)),
        "is_next_round": bool(sub.get("is_next_round", False)),
        "company_name": extracted.get("company_name") or classification.get("company_name") or "",
        "position_title": extracted.get("position_title") or extracted.get("job_title") or "",
        "contact_name": extracted.get("contact_name") or extracted.get("sender_name") or "",
        "contact_title": extracted.get("contact_title") or "",
        "contact_email": extracted.get("contact_email") or email_data.get("from_email") or "",
        "contact_phone": extracted.get("contact_phone") or "",
        "interview_date": extracted.get("interview_date"),
        "interview_time": extracted.get("interview_time"),
        "interview_timezone": extracted.get("interview_timezone"),
        "job_description_url": extracted.get("job_description_url") or "",
        "num_interviewers": None,
    }


def send_interview_notification(
    email_data: Dict[str, Any],
    classification: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Send an interview notification email to the identified student.

    Args:
        email_data: Raw email dict from fetch_emails (has subject, body, from, etc.)
        classification: Classification result from classify_email

    Returns:
        Dict with keys: success (bool), student_name, error (str|None)
    """
    result = {"success": False, "student_name": None, "error": None}

    try:
        # Step 1: Find student
        student = _get_student_info(classification, email_data)
        if not student:
            result["error"] = "Student name could not be extracted from email"
            logger.warning(f"Notification skipped — no student name found. Email: {email_data.get('subject')}")
            return result

        result["student_name"] = student["name"]
        logger.info(f"Sending interview notification to: {student['name']} ({student['personal_email']})")

        # Step 2: Draft notification using existing template system
        from draft_notification import draft_notification

        student_info = _build_student_info_for_draft(student)
        draft_classification = _build_classification_for_draft(classification, email_data)

        draft = draft_notification(
            classification=draft_classification,
            student_info=student_info,
            assistant_name=student["assigned_to"],  # "Karthik" or "Vivek"
        )

        if draft["draft_status"] == "no_template":
            result["error"] = "No email template found for this interview type"
            logger.warning(result["error"])
            return result

        # Step 3: Send email
        from send_notification import send_email

        to_email = student["personal_email"]
        cc_list = list(set(ALWAYS_CC + student.get("cc_emails", [])))

        # BCC Shemika and Jackie on every notification
        bcc_str = ", ".join(ALWAYS_CC)

        send_result = send_email(
            recipient_email=to_email,
            subject=draft["email_subject"],
            body=draft["email_body"],
            from_name=f"{student['assigned_to']} at Colaberry",
            bcc=bcc_str,
        )

        if send_result.get("status") == "sent":
            logger.info(
                f"Notification sent to {student['name']} ({to_email}) "
                f"BCC: {bcc_str}"
            )
            result["success"] = True
        else:
            result["error"] = send_result.get("error", "Unknown send error")
            logger.error(f"Failed to send notification: {result['error']}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Notification failed unexpectedly: {e}", exc_info=True)

    return result
