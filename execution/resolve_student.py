"""
Student resolution execution script.

Identifies which student an incoming interview email is about by examining
email headers to find the original recipient (the student's assigned Gmail).

All student Gmail accounts forward/route their emails to c_interviews@colaberry.com.
This script reverses that routing to identify the student.

Design principles:
- Pure logic separated from I/O for testability
- Deterministic header parsing (no AI)
- Multiple fallback strategies for student identification
"""

import logging
import re
from typing import Dict, Any, Optional, List

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Headers that may contain the original recipient email (in priority order)
RECIPIENT_HEADERS = [
    "Delivered-To",
    "X-Forwarded-To",
    "X-Original-To",
    "Envelope-To",
    "X-Delivered-To",
    "X-Forwarded-For",
    "X-Gm-Original-To",
]

# The central inbox that receives all forwarded emails
CENTRAL_INBOX = "c_interviews@colaberry.com"

# Email pattern for extracting addresses
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_username_from_email(email_address: str) -> str:
    """
    Extract the username (local part) from an email address.

    Args:
        email_address: Full email address (e.g., "john.doe@gmail.com")

    Returns:
        Username part (e.g., "john.doe")
    """
    if not email_address or "@" not in email_address:
        return ""
    return email_address.split("@")[0].strip().lower()


def find_student_email_from_headers(
    headers: Dict[str, str],
) -> Optional[str]:
    """
    Find the student's assigned Gmail from email headers.

    When emails are forwarded from student Gmail accounts to c_interviews@,
    the original recipient is preserved in certain headers.

    Args:
        headers: Dictionary of email headers (case-insensitive keys)

    Returns:
        Student's email address if found, None otherwise
    """
    # Normalize header keys to handle case variations
    normalized = {k.lower().strip(): v for k, v in headers.items()}

    for header_name in RECIPIENT_HEADERS:
        header_key = header_name.lower()
        value = normalized.get(header_key)
        if not value:
            continue

        # Extract email addresses from header value
        emails = EMAIL_PATTERN.findall(value)
        for email in emails:
            email_lower = email.lower()
            # Skip the central inbox — we want the student's email
            if email_lower == CENTRAL_INBOX:
                continue
            # Found a non-central-inbox email in forwarding headers
            logger.info(
                f"Found student email in {header_name} header: {email_lower}"
            )
            return email_lower

    return None


def find_student_email_from_to_field(
    to_addresses: List[str],
) -> Optional[str]:
    """
    Find the student's email from the To/CC fields.

    In some forwarding setups, the original To address is preserved.

    Args:
        to_addresses: List of To/CC email addresses

    Returns:
        Student's email if a non-central address is found, None otherwise
    """
    for addr in to_addresses:
        addr_lower = addr.strip().lower()
        if addr_lower and addr_lower != CENTRAL_INBOX:
            # Check if it looks like a Gmail address (student accounts are Gmail)
            if "@gmail.com" in addr_lower:
                logger.info(f"Found student Gmail in To/CC: {addr_lower}")
                return addr_lower

    return None


def find_student_name_in_body(body_content: str) -> Optional[str]:
    """
    Attempt to find a student name mentioned in the email body.

    This is a fallback method — less reliable than header-based detection.

    Args:
        body_content: Email body text

    Returns:
        Extracted name string if found, None otherwise
    """
    if not body_content:
        return None

    # Common patterns where the candidate name appears
    # Name capture group: one or two capitalized words (e.g., "John Smith")
    name_group = r"([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)?)"
    name_patterns = [
        r"(?:[Dd]ear|[Hh]i|[Hh]ello|[Aa]ttention)\s+" + name_group,
        r"(?:[Ii]nterview\s+(?:for|with)\s+)" + name_group,
        r"(?:[Cc]andidate|[Aa]pplicant)\s*:?\s*" + name_group,
    ]

    for pattern in name_patterns:
        match = re.search(pattern, body_content)
        if match:
            name = match.group(1).strip()
            if name.isupper():
                name = name.title()          # "Hi OMOLOLA," -> "Omolola"
            # Basic validation: name should be 2+ characters, not common words.
            # 2026-09-18: this list was too thin -- "Ok" (ordinary conversational
            # prose, not a name) slipped through and got auto-persisted as a
            # fake student in config/students.py. add_new_student() now also
            # refuses anything without a real email, but keep this list
            # reasonably wide too rather than relying on a single guardrail.
            common_words = {
                "Dear", "The", "This", "Your", "Our", "Team", "All",
                "Ok", "Okay", "Hi", "Hello", "Hey", "Thanks", "Thank",
                "Please", "Sure", "Best", "Regards", "Sincerely", "Yes", "No",
                "Sorry", "Just", "Hope", "Great", "Good", "Kind", "Warm",
                "There", "Everyone", "Candidate", "Applicant", "Sir", "Madam", "User", "Friend", "Folks", "Greetings",
                "Recruiter", "Manager", "Hiring",
            }
            if len(name) >= 2 and name not in common_words:
                logger.info(f"Found potential student name in body: {name}")
                return name

    return None


def resolve_student(
    email_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Resolve which student an interview email is about.

    Tries multiple strategies in order:
    1. Email forwarding headers (most reliable)
    2. To/CC fields with Gmail addresses
    3. Name extraction from body (least reliable, fallback only)

    Args:
        email_data: Dictionary with email data. Expected keys:
            - headers: Dict of email headers (optional)
            - to_addresses: List of To/CC addresses (optional)
            - body_content: Email body text (optional)
            - sender_email: Sender's email (optional)

    Returns:
        Dictionary with:
            - student_gmail: str | None (the student's assigned Gmail)
            - student_username: str | None (derived from Gmail, matches Drive folder)
            - resolution_method: str (how the student was identified)
            - confidence: str ("high", "medium", "low")
            - student_name_hint: str | None (name found in body, if any)
    """
    result = {
        "student_gmail": None,
        "student_username": None,
        "resolution_method": "none",
        "confidence": "low",
        "student_name_hint": None,
    }

    # Strategy 1: Check forwarding headers
    headers = email_data.get("headers", {})
    if headers:
        student_email = find_student_email_from_headers(headers)
        if student_email:
            result["student_gmail"] = student_email
            result["student_username"] = extract_username_from_email(student_email)
            result["resolution_method"] = "email_headers"
            result["confidence"] = "high"
            logger.info(
                f"Resolved student via headers: {result['student_username']}"
            )
            return result

    # Strategy 2: Check To/CC fields
    to_addresses = email_data.get("to_addresses", [])
    if to_addresses:
        student_email = find_student_email_from_to_field(to_addresses)
        if student_email:
            result["student_gmail"] = student_email
            result["student_username"] = extract_username_from_email(student_email)
            result["resolution_method"] = "to_field"
            result["confidence"] = "medium"
            logger.info(
                f"Resolved student via To field: {result['student_username']}"
            )
            return result

    # Strategy 3: Extract name from body (fallback)
    body_content = email_data.get("body_content", "")
    if body_content:
        name_hint = find_student_name_in_body(body_content)
        if name_hint:
            result["student_name_hint"] = name_hint
            result["resolution_method"] = "body_name_extraction"
            result["confidence"] = "low"
            logger.info(
                f"Found name hint in body: {name_hint} (requires manual matching)"
            )
            return result

    logger.warning("Could not resolve student from email data")
    return result
