"""
Interview sub-classification execution script.

This script takes emails already classified as interview-related by classify_email.py
and sub-classifies them into specific interview types with detailed data extraction.

Design principles:
- Pure logic separated from I/O for testability
- Deterministic validation and business rules
- Follows the same pattern as classify_email.py
- Second-pass classifier: only runs on interview-related emails
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Interview sub-types (must match exactly)
INTERVIEW_SUB_TYPES = [
    "Interview Request",
    "Phone Screen",
    "Client Screen",
    "Technical Interview",
    "Interview Cancelled",
    "Interview Rescheduled",
    "Job Machine",
]

# Categories from classify_email.py that are interview-related
# and should be processed by this sub-classifier
INTERVIEW_RELATED_CATEGORIES = [
    "Interview Request",
    "Interview Schedule",
    "Interview Reschedule",
    "Interview Cancelled",
    "Final Interview Scheduled",
    "Phone Screen",
    "Assessment",
    "Technical Interview",
    "Client Screen",
    "Job Machine",
]

# Job Machine sub-types (for emails originating from Job Machine platform)
JOB_MACHINE_SUB_TYPES = [
    "interview",
    "reschedule",
    "cancellation",
]

# Sub-classification prompt
SUBCLASSIFICATION_PROMPT = """# Interview Email Sub-Classification System

You are a second-pass classifier for interview-related emails at Colaberry, a career
placement program. The email has already been identified as interview-related. Your job
is to determine the SPECIFIC type of interview communication and extract detailed data.

## YOUR TASK

Classify this email into exactly ONE interview sub-type and extract all relevant details.

---

## INTERVIEW SUB-TYPES (7 Total)

**1. Interview Request**
- Initial invitation to schedule or participate in an interview
- No confirmed date/time yet — they are ASKING the candidate to schedule
- Key signals: "Interview Invitation", "Schedule Your Interview", time slot options
- Sender: Recruiters or HR
- Could be phone, client, or technical interview — but the date is NOT yet confirmed

**2. Phone Screen**
- Scheduled initial phone interview or screening call with HR/recruiter
- Date and time ARE confirmed or being provided
- Key signals: "Phone Interview Scheduled", "Initial Screening Call", dial-in instructions
- Sender: HR or recruiters
- Typically 1-on-1 with a recruiter or HR representative

**3. Client Screen**
- Second round or next round interview with the actual client/hiring manager
- Date and time ARE confirmed or being provided
- Key signals: "Client Interview", "Second Round Interview", "Next Round Interview"
- Sender: Recruitment agencies or internal HR teams
- Typically involves 2+ people: client representative AND HR
- This is NOT a phone screen — it's a more formal interview with decision-makers

**4. Technical Interview**
- Technical assessment or interview (coding, system design, etc.)
- Date and time ARE confirmed or being provided
- Key signals: "Technical Interview Scheduled", "Coding Test", "System Design Interview"
- Sender: HR, recruiters, or technical team leads
- Typically involves a panel of 2+ interviewers
- Tests specific technical skills or knowledge

**5. Interview Cancelled**
- Previously scheduled interview will not occur
- Key signals: "Your Interview Has Been Cancelled", "Schedule Change Notification"
- Sender: HR, recruiters, or hiring managers
- May or may not include a reason
- May suggest rescheduling

**6. Interview Rescheduled**
- Previously scheduled interview has been moved to a new date/time
- Key signals: "Your Interview Has Been Rescheduled", new time/date details
- Sender: Recruiters, HR, or hiring platforms
- Must include new date/time information (or instructions to coordinate new time)

**7. Job Machine**
- Email originates from the Job Machine platform
- Key signals: sender is Job Machine, "Job Machine" in email, platform notifications
- These emails can contain interview notifications, reschedules, or cancellations
- You must also determine the job_machine_sub_type: "interview", "reschedule", or "cancellation"

---

## DISAMBIGUATION RULES

- **Interview Request vs Phone Screen**: Interview Request = no date confirmed yet (asking to schedule).
  Phone Screen = date/time confirmed for initial screening.
- **Phone Screen vs Client Screen**: Phone Screen = initial screening with HR/recruiter only.
  Client Screen = second/later round with the actual client or hiring manager (2+ people).
- **Client Screen vs Technical Interview**: Client Screen = business/behavioral with client.
  Technical Interview = tests technical skills (coding, system design) with technical panel.
- **Interview Cancelled vs Interview Rescheduled**: Cancelled = interview won't happen, no new time.
  Rescheduled = interview moved to a different time.
- **Any type vs Job Machine**: If the email is FROM Job Machine platform, classify as Job Machine
  AND set job_machine_sub_type to indicate the actual interview action.

## NEXT ROUND DETECTION

Determine if this is a first interview or a subsequent round:
- First interview: no mention of previous rounds, initial outreach
- Next round: mentions "second round", "next round", "technical round",
  "you made it to the next stage", congratulatory language about advancing

Set `is_next_round: true` if this is a second, third, or later interview round.

---

## DATA EXTRACTION RULES

Extract ALL of the following fields. Use null for missing/uncertain data.

- interview_sub_type: one of the 7 sub-types above (required)
- job_machine_sub_type: "interview" | "reschedule" | "cancellation" | null (required if Job Machine)
- company_name: string | null (the hiring company)
- position_title: string | null (job title/role)
- contact_name: string | null (HR/recruiter/interviewer name)
- contact_title: string | null (their job title)
- contact_email: string | null (their email)
- contact_phone: string | null (their phone number)
- interview_date: YYYY-MM-DD | null (scheduled date, ISO 8601)
- interview_time: HH:MM | null (scheduled time, 24-hour format)
- interview_timezone: string | null (e.g., "EST", "CST", "PST")
- interview_format: "phone" | "video" | "in-person" | "panel" | null
- meeting_link_or_dial_in: string | null (Zoom link, phone number, etc.)
- num_interviewers: integer | null (how many interviewers)
- interviewer_names_roles: list of objects [{{name, role}}] | null
- cancellation_reason: string | null (reason if cancelled)
- original_date: YYYY-MM-DD | null (previous date if rescheduled)
- original_time: HH:MM | null (previous time if rescheduled)
- new_date: YYYY-MM-DD | null (new date if rescheduled)
- new_time: HH:MM | null (new time if rescheduled)
- is_job_machine: boolean (true if from Job Machine platform)
- is_next_round: boolean (true if second/third/subsequent interview round)
- job_description_url: string | null (URL to job posting if present)
- confidence: float 0.0-1.0 (your confidence in this sub-classification)
- reasoning: string (1-3 sentences explaining your classification)

---

## CONFIDENCE CALIBRATION

- 0.95-1.0: Clear sub-type with explicit signals, all key data present
- 0.85-0.94: Strong signals, minor ambiguity, most data present
- 0.70-0.84: Moderate signals, some ambiguity, partial data
- 0.50-0.69: Weak signals, significant ambiguity
- 0.00-0.49: Very unclear, requires human review

---

## OUTPUT FORMAT

Return ONLY valid JSON with the extracted fields above. No additional text.

---

## EMAIL TO CLASSIFY

Subject: {subject}
From: {sender_email}
Sender Name: {sender_name}
Date: {email_date}
Content:
{body_content}
"""


def format_email_for_subclassification(email_data: Dict[str, Any]) -> str:
    """
    Format email data into the sub-classification prompt.

    Args:
        email_data: Dictionary with keys: subject, sender_email, sender_name,
                   email_date, body_content

    Returns:
        Formatted prompt string ready for OpenAI API
    """
    return SUBCLASSIFICATION_PROMPT.format(
        subject=email_data.get("subject", ""),
        sender_email=email_data.get("sender_email", ""),
        sender_name=email_data.get("sender_name", ""),
        email_date=email_data.get("email_date", ""),
        body_content=email_data.get("body_content", ""),
    )


def call_openai_api(
    prompt: str,
    api_key: Optional[str] = None,
    model: str = "gpt-4o",
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> Dict[str, Any]:
    """
    Call OpenAI API with the sub-classification prompt.

    Args:
        prompt: Formatted sub-classification prompt
        api_key: OpenAI API key (reads from OPENAI_API_KEY env var if not provided)
        model: OpenAI model to use
        max_tokens: Maximum tokens in response
        temperature: Temperature for generation (0.0 for deterministic)

    Returns:
        Dictionary containing the API response

    Raises:
        RuntimeError: If API call fails
        ValueError: If API key is missing
    """
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not found. Set environment variable or pass api_key parameter."
        )

    try:
        try:
            import openai
        except ImportError:
            raise RuntimeError(
                "openai library not installed. Install with: pip install openai"
            )

        client = openai.OpenAI(api_key=api_key)

        logger.info(f"Calling OpenAI API for sub-classification with model: {model}")
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an interview email sub-classification system for Colaberry. "
                        "Always respond with valid JSON containing all requested fields."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )

        response_text = response.choices[0].message.content
        logger.info("Successfully received sub-classification response from OpenAI API")

        return {
            "response": response_text,
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            },
        }

    except Exception as e:
        logger.error(f"OpenAI API call failed during sub-classification: {e}")
        raise RuntimeError(f"Failed to call OpenAI API: {str(e)}")


def parse_subclassification_response(response_text: str) -> Dict[str, Any]:
    """
    Parse JSON response from AI API.

    Args:
        response_text: Raw text response from the API

    Returns:
        Parsed JSON sub-classification result

    Raises:
        json.JSONDecodeError: If response is not valid JSON
    """
    response_text = response_text.strip()

    # Remove markdown code blocks if present
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]

    response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse sub-classification JSON response: {e}")
        logger.error(f"Response text: {response_text[:500]}")
        raise


def apply_business_rules(classification: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply business rules to the sub-classification result.

    Pure deterministic logic — no API calls, easily testable.

    Args:
        classification: Raw sub-classification result from AI

    Returns:
        Classification with business rules applied
    """
    result = classification.copy()

    confidence = result.get("confidence", 0)

    # Rule 1: Determine auto-send eligibility based on confidence
    if confidence >= 0.95:
        result["auto_send_eligible"] = True
        result["requires_human_review"] = False
        result["confidence_tier"] = "high"
    elif confidence >= 0.80:
        result["auto_send_eligible"] = True
        result["requires_human_review"] = False
        result["confidence_tier"] = "medium_high"
        result["flag_for_audit"] = True
    elif confidence >= 0.70:
        result["auto_send_eligible"] = False
        result["requires_human_review"] = True
        result["confidence_tier"] = "medium"
    else:
        result["auto_send_eligible"] = False
        result["requires_human_review"] = True
        result["confidence_tier"] = "low"

    # Rule 2: Validate sub-type is in approved list
    sub_type = result.get("interview_sub_type")
    if sub_type not in INTERVIEW_SUB_TYPES:
        logger.warning(
            f"Unknown interview sub-type: {sub_type}. Flagging for review."
        )
        result["requires_human_review"] = True
        result["auto_send_eligible"] = False

    # Rule 3: Job Machine emails must have a job_machine_sub_type
    if sub_type == "Job Machine":
        jm_sub = result.get("job_machine_sub_type")
        if jm_sub not in JOB_MACHINE_SUB_TYPES:
            logger.warning(
                f"Job Machine email missing valid sub-type: {jm_sub}. Flagging for review."
            )
            result["requires_human_review"] = True
            result["auto_send_eligible"] = False

    # Rule 4: Cancelled/rescheduled emails with no reason should be flagged
    if sub_type == "Interview Cancelled" and not result.get("cancellation_reason"):
        result["flag_for_audit"] = True

    # Rule 5: If interview date is present, validate it's not in the past
    # (This is a safety check — let the human decide if needed)
    interview_date = result.get("interview_date")
    if interview_date:
        try:
            parsed_date = datetime.strptime(interview_date, "%Y-%m-%d").date()
            if parsed_date < datetime.utcnow().date():
                result["flag_for_audit"] = True
                logger.info(
                    f"Interview date {interview_date} is in the past. Flagging for audit."
                )
        except ValueError:
            logger.warning(f"Invalid interview date format: {interview_date}")
            result["flag_for_audit"] = True

    # Rule 6: Add processing timestamp
    result["processing_timestamp"] = datetime.utcnow().isoformat() + "Z"

    return result


def is_interview_related(primary_category: str) -> bool:
    """
    Check if the primary classification category warrants sub-classification.

    Args:
        primary_category: Category from classify_email.py

    Returns:
        True if this email should be sub-classified
    """
    return primary_category in INTERVIEW_RELATED_CATEGORIES


def subclassify_interview(
    email_data: Dict[str, Any],
    api_key: Optional[str] = None,
    validate_only: bool = False,
) -> Dict[str, Any]:
    """
    Sub-classify an interview-related email into a specific interview type.

    Main entry point for interview sub-classification.

    Args:
        email_data: Dictionary with email fields (subject, sender_email,
                   sender_name, email_date, body_content)
        api_key: Optional API key (uses env var if not provided)
        validate_only: If True, skip API call and return mock result (for testing)

    Returns:
        Dictionary with sub-classification result and metadata

    Raises:
        ValueError: If required email fields are missing
        RuntimeError: If API call or parsing fails
    """
    # Validate required fields
    required_fields = ["subject", "body_content"]
    missing_fields = [f for f in required_fields if f not in email_data]
    if missing_fields:
        raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

    logger.info(
        f"Starting sub-classification for email: '{email_data.get('subject', 'No subject')}'"
    )

    # Format prompt
    prompt = format_email_for_subclassification(email_data)

    # Call API or return mock
    if validate_only:
        logger.info("Validation-only mode: skipping API call")
        classification = {
            "interview_sub_type": "Interview Request",
            "job_machine_sub_type": None,
            "company_name": None,
            "position_title": None,
            "contact_name": None,
            "contact_title": None,
            "contact_email": None,
            "contact_phone": None,
            "interview_date": None,
            "interview_time": None,
            "interview_timezone": None,
            "interview_format": None,
            "meeting_link_or_dial_in": None,
            "num_interviewers": None,
            "interviewer_names_roles": None,
            "cancellation_reason": None,
            "original_date": None,
            "original_time": None,
            "new_date": None,
            "new_time": None,
            "is_job_machine": False,
            "is_next_round": False,
            "job_description_url": None,
            "confidence": 0.5,
            "reasoning": "Validation-only mode",
        }
    else:
        api_response = call_openai_api(prompt, api_key=api_key)
        classification = parse_subclassification_response(api_response["response"])

    # Apply business rules
    result = apply_business_rules(classification)

    # Add metadata
    result["email_metadata"] = {
        "subject": email_data.get("subject"),
        "sender_email": email_data.get("sender_email"),
        "email_date": email_data.get("email_date"),
    }

    logger.info(
        f"Sub-classification complete: {result.get('interview_sub_type')} "
        f"(confidence: {result.get('confidence')}, "
        f"auto_send: {result.get('auto_send_eligible')}, "
        f"review: {result.get('requires_human_review')})"
    )

    return result


def load_email_from_file(file_path: Path) -> Dict[str, Any]:
    """
    Load email data from JSON file.

    Args:
        file_path: Path to JSON file with email data

    Returns:
        Email data dictionary
    """
    logger.info(f"Loading email from {file_path}")

    if not file_path.exists():
        raise FileNotFoundError(f"Email file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        email_data = json.load(f)

    logger.info("Email loaded successfully")
    return email_data


def save_subclassification_result(
    result: Dict[str, Any], output_path: Path
) -> None:
    """
    Save sub-classification result to JSON file.

    Args:
        result: Sub-classification result dictionary
        output_path: Path to save result
    """
    logger.info(f"Saving sub-classification result to {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    logger.info("Sub-classification result saved successfully")


def main() -> None:
    """
    CLI entry point for interview sub-classification.

    Usage:
        python subclassify_interview.py <input_file> <output_file> [--validate-only]
    """
    import sys

    if len(sys.argv) < 3:
        print(
            "Usage: python subclassify_interview.py <input_file> <output_file> [--validate-only]"
        )
        print("\nInput file should be JSON with fields:")
        print("  - subject: Email subject")
        print("  - sender_email: Sender email address")
        print("  - sender_name: Sender name (optional)")
        print("  - email_date: Email date (optional)")
        print("  - body_content: Email body text")
        sys.exit(1)

    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2])
    validate_only = "--validate-only" in sys.argv

    env = os.getenv("ENVIRONMENT", "development")
    if env == "production" and validate_only:
        print("Warning: validate-only mode should not be used in production")

    try:
        email_data = load_email_from_file(input_file)
        result = subclassify_interview(email_data, validate_only=validate_only)
        save_subclassification_result(result, output_file)

        print(f"\nSub-classification complete:")
        print(f"  Sub-type: {result.get('interview_sub_type')}")
        print(f"  Confidence: {result.get('confidence', 0):.2f}")
        print(f"  Auto-send eligible: {result.get('auto_send_eligible')}")
        print(f"  Requires review: {result.get('requires_human_review')}")
        print(f"  Company: {result.get('company_name', 'Unknown')}")

        if result.get("is_job_machine"):
            print(f"  Job Machine sub-type: {result.get('job_machine_sub_type')}")

        sys.exit(1 if result.get("requires_human_review") else 0)

    except Exception as e:
        logger.error(f"Sub-classification failed: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
