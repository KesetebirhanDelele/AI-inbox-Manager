"""
Email template storage and selection for interview notifications.

Contains all Colaberry interview notification templates and deterministic
logic for selecting the correct template based on interview sub-type.

Design principles:
- All templates defined as data (no logic in templates)
- Template selection is purely deterministic (no AI)
- Placeholders use {field_name} format
- Missing placeholders are detectable before sending
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EmailTemplate:
    """Represents an email notification template."""

    template_id: str
    template_name: str
    subject_template: str
    body_template: str
    required_fields: List[str]
    applies_to_sub_types: List[str] = field(default_factory=list)
    is_job_machine: bool = False


# ============================================================================
# TEMPLATE DEFINITIONS
# ============================================================================

TEMPLATES: Dict[str, EmailTemplate] = {}


def _register(template: EmailTemplate) -> EmailTemplate:
    """Register a template in the global registry."""
    TEMPLATES[template.template_id] = template
    return template


# --- Interview Request (First) ---
_register(
    EmailTemplate(
        template_id="interview_request_first",
        template_name="Interview Request (First)",
        subject_template="Congrats! You got an interview request with {company_name}!",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations, you got an interview request with {company_name} "
            "for their {position_title} role!\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail}/Linkedin account "
            "and respond to {contact_name} to schedule your interview.\n\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally, ALWAYS BCC "
            "c_interviews@colaberry.com on all recruiter communications, so we can "
            "accurately track the progress of the recruitment process.\n\n\n"
            "Please let us know if you have any questions or how we can help!\n\n\n"
            "Contact Name: {contact_name}\n"
            "Contact Job Title: {contact_title}\n"
            "Contact Email: {contact_email}\n"
            "Contact Phone: {contact_phone}\n"
            "Job Description: {job_description_url}\n\n\n"
            "All the best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "position_title",
            "assigned_gmail",
            "contact_name",
            "assistant_name",
        ],
        applies_to_sub_types=["Interview Request"],
    )
)

# --- Interview Request (First) via Job Machine ---
_register(
    EmailTemplate(
        template_id="interview_request_first_jm",
        template_name="Interview Request (First) via Job Machine",
        subject_template="Congrats! You got an interview request with {company_name} via JOB MACHINE!",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations, you got an interview request with {company_name} "
            "for their {position_title} role!\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail} and respond "
            "to {contact_name} to schedule your interview.\n\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally, ALWAYS BCC "
            "c_interviews@colaberry.com on all recruiter communications, so we can "
            "accurately track the progress of the recruitment process.\n\n\n"
            "Please let us know if you have any questions or how we can help!\n\n\n"
            "Contact Name: {contact_name}\n"
            "Contact Job Title: {contact_title}\n"
            "Contact Email: {contact_email}\n"
            "Contact Phone: {contact_phone}\n"
            "Job Description: {job_description_url}\n\n\n"
            "All the best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "position_title",
            "assigned_gmail",
            "contact_name",
            "assistant_name",
        ],
        applies_to_sub_types=["Interview Request"],
        is_job_machine=True,
    )
)

# --- Phone Screening Scheduled ---
_register(
    EmailTemplate(
        template_id="phone_screening_scheduled",
        template_name="Phone Screening Scheduled",
        subject_template="PHONE SCREENING: Interview Scheduled - {company_name}",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations! Your interview for the {position_title} position at "
            "{company_name} has been scheduled and confirmed for {interview_datetime}.\n\n\n"
            "This interview is going to be a Phone Screening with {contact_name}. "
            "Please make sure that you are preparing for this interview utilizing the "
            "questions in the log dashboard.\n\n\n"
            "MANDATORY! You have been emailed the questions in a separate email. "
            "Follow the instructions on that email to draft your answers. Then click "
            "this link to schedule your auto mock interview so you can practice on "
            "your confidence.\n\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail} and respond to "
            "{contact_name} to confirm your scheduled interview.\n\n\n"
            "If at any time that your scheduled interview above has been canceled or "
            "rescheduled please notify us immediately so that we can update the log.\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally,\n\n\n"
            "ALWAYS BCC c_interviews@colaberry.com on all recruiter communications, "
            "so we can accurately track the progress of the recruitment process.\n\n\n"
            "Let us know if you have any questions or how we can help!\n\n\n"
            "All the best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "position_title",
            "interview_datetime",
            "contact_name",
            "assigned_gmail",
            "assistant_name",
        ],
        applies_to_sub_types=["Phone Screen"],
    )
)

# --- Phone Screening Scheduled via Job Machine ---
_register(
    EmailTemplate(
        template_id="phone_screening_scheduled_jm",
        template_name="Phone Screening Scheduled via Job Machine",
        subject_template="PHONE SCREENING: Interview Scheduled via JOB MACHINE - {company_name}",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations! Your interview for the {position_title} position at "
            "{company_name} has been scheduled and confirmed for {interview_datetime}.\n\n\n"
            "This interview is going to be a Phone Screening. Please make sure that "
            "you are preparing for this interview utilizing the questions in the log "
            "dashboard.\n\n\n"
            "Please log in to your Job Machine account to see the Interview details "
            "and job information.\n\n\n"
            "MANDATORY! You have been emailed the questions in a separate email. "
            "Follow the instructions on that email to draft your answers. Then click "
            "this link to schedule your auto mock interview so you can practice on "
            "your confidence.\n\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail} and respond to "
            "{contact_name} to confirm your scheduled interview.\n\n\n"
            "If at any time that your scheduled interview above has been canceled or "
            "rescheduled please notify us immediately so that we can update the log.\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally,\n\n\n"
            "ALWAYS BCC c_interviews@colaberry.com on all recruiter communications, "
            "so we can accurately track the progress of the recruitment process.\n\n\n"
            "Let us know if you have any questions or how we can help!\n\n\n"
            "All the best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "position_title",
            "interview_datetime",
            "assigned_gmail",
            "contact_name",
            "assistant_name",
        ],
        applies_to_sub_types=["Phone Screen"],
        is_job_machine=True,
    )
)

# --- Client Screening Scheduled ---
_register(
    EmailTemplate(
        template_id="client_screening_scheduled",
        template_name="Client Screening Scheduled",
        subject_template="CLIENT SCREENING: Interview Scheduled - {company_name}",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations! Your interview for the {position_title} position at "
            "{company_name} has been scheduled and confirmed for {interview_datetime}.\n\n\n"
            "This interview is going to be a Client Screening with {contact_name}. "
            "Please make sure that you are preparing for this interview by using "
            "this checklist:\n\n\n"
            "Utilize the questions in the log dashboard\n"
            "Book a one on one with your mentor\n"
            "Schedule an auto mock\n\n\n"
            "Your preparation score should not be at 0%\n\n\n"
            "MANDATORY! You have been emailed the questions in a separate email. "
            "Follow the instructions on that email to draft your answers. Then click "
            "this link to schedule your auto mock interview so you can practice on "
            "your confidence.\n\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail} and respond to "
            "{contact_name} to confirm your scheduled interview.\n\n\n"
            "If at any time that your scheduled interview above has been canceled or "
            "rescheduled please notify us immediately so that we can update the log.\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally,\n\n\n"
            "ALWAYS BCC c_interviews@colaberry.com on all recruiter communications, "
            "so we can accurately track the progress of the recruitment process.\n\n\n"
            "Let us know if you have any questions or how we can help!\n\n\n"
            "All the best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "position_title",
            "interview_datetime",
            "contact_name",
            "assigned_gmail",
            "assistant_name",
        ],
        applies_to_sub_types=["Client Screen"],
    )
)

# --- Client Screening Scheduled via Job Machine ---
_register(
    EmailTemplate(
        template_id="client_screening_scheduled_jm",
        template_name="Client Screening Scheduled via Job Machine",
        subject_template="CLIENT SCREENING: Interview Scheduled via JOB MACHINE - {company_name}",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations! Your interview for the {position_title} position at "
            "{company_name} has been scheduled and confirmed for {interview_datetime}.\n\n\n"
            "This interview is going to be a Client Screening with {contact_name}. "
            "Please make sure that you are preparing for this interview by using "
            "this checklist:\n\n\n"
            "Utilize the questions in the log dashboard\n"
            "Book a one on one with your mentor\n"
            "Schedule an auto mock\n\n\n"
            "Your preparation score should not be at 0%\n\n\n"
            "Please log in to your Job Machine account to see the Interview details "
            "and job information.\n\n\n"
            "MANDATORY! You have been emailed the questions in a separate email. "
            "Follow the instructions on that email to draft your answers. Then click "
            "this link to schedule your auto mock interview so you can practice on "
            "your confidence.\n\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail} and respond to "
            "{contact_name} to confirm your scheduled interview.\n\n\n"
            "If at any time that your scheduled interview above has been canceled or "
            "rescheduled please notify us immediately so that we can update the log.\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally,\n\n\n"
            "ALWAYS BCC c_interviews@colaberry.com on all recruiter communications, "
            "so we can accurately track the progress of the recruitment process.\n\n\n"
            "Let us know if you have any questions or how we can help!\n\n\n"
            "All the best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "position_title",
            "interview_datetime",
            "contact_name",
            "assigned_gmail",
            "assistant_name",
        ],
        applies_to_sub_types=["Client Screen"],
        is_job_machine=True,
    )
)

# --- Technical Round Scheduled ---
_register(
    EmailTemplate(
        template_id="technical_round_scheduled",
        template_name="Technical Round Scheduled",
        subject_template="AWESOME JOB! You made it to the Technical Round with {company_name}!",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations! Your Technical Round Interview has been scheduled "
            "for {company_name} for {interview_datetime}!\n\n"
            "This will be a TECHNICAL ROUND and you'll be meeting with "
            "{num_interviewers} interviewer(s).\n\n"
            "Please make sure that you are preparing for this interview by using "
            "this checklist:\n\n\n"
            "Utilize the questions in the log dashboard\n"
            "Book a one on one with your mentor\n"
            "Schedule an auto mock\n\n\n"
            "Your preparation score should not be at 0%\n\n\n"
            "MANDATORY! You have been emailed the questions in a separate email. "
            "Follow the instructions on that email to draft your answers. Then click "
            "this link to schedule your auto mock interview so you can practice on "
            "your confidence.\n\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail}/Linkedin account "
            "and respond to {contact_name} to confirm the schedule of your Technical "
            "Round Interview.\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally, ALWAYS BCC "
            "c_interviews@colaberry.com on all recruiter communications, so we can "
            "accurately track the progress of the recruitment process.\n\n\n"
            "Please don't forget to take your survey once the interview is done.\n\n"
            "Good luck! And please let us know how else we can support you!\n\n"
            "Cheers,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "interview_datetime",
            "assigned_gmail",
            "contact_name",
            "assistant_name",
        ],
        applies_to_sub_types=["Technical Interview"],
    )
)

# --- Technical Round Scheduled via Job Machine ---
_register(
    EmailTemplate(
        template_id="technical_round_scheduled_jm",
        template_name="Technical Round Scheduled via Job Machine",
        subject_template="AWESOME JOB! You made it to the Technical Round with {company_name}",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations! Your Technical Round Interview has been scheduled "
            "{company_name} and confirmed for {interview_datetime}!\n\n"
            "This will be a TECHNICAL ROUND and you'll be meeting with "
            "{num_interviewers} interviewer(s).\n\n"
            "Please make sure that you are preparing for this interview by using "
            "this checklist:\n\n\n"
            "Utilize the questions in the log dashboard\n"
            "Book a one on one with your mentor\n"
            "Schedule an auto mock\n\n\n"
            "Your preparation score should not be at 0%\n\n\n"
            "MANDATORY! You have been emailed the questions in a separate email. "
            "Follow the instructions on that email to draft your answers. Then click "
            "this link to schedule your auto mock interview so you can practice on "
            "your confidence.\n\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail}/Linkedin account "
            "and respond to {contact_name} to confirm the schedule of your Technical "
            "Round Interview.\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally, ALWAYS BCC "
            "c_interviews@colaberry.com on all recruiter communications, so we can "
            "accurately track the progress of the recruitment process.\n\n\n"
            "Please don't forget to take your survey once the interview is done.\n\n"
            "Good luck! And please let us know how else we can support you!\n\n"
            "Cheers,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "interview_datetime",
            "assigned_gmail",
            "contact_name",
            "assistant_name",
        ],
        applies_to_sub_types=["Technical Interview"],
        is_job_machine=True,
    )
)

# --- Second/Third Interview Request (Next Round) ---
_register(
    EmailTemplate(
        template_id="next_round_request",
        template_name="Next Round Interview Request",
        subject_template="AWESOME JOB! You made it to the Technical Round with {company_name}!",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations! You've made it to the next round with {company_name}!\n\n"
            "This will be a Technical Round.\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail}/Linkedin account "
            "and respond to {contact_name} regarding the schedule of your Technical "
            "round interview.\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally, ALWAYS BCC "
            "c_interviews@colaberry.com on all recruiter communications, so we can "
            "accurately track the progress of the recruitment process.\n\n"
            "Good luck! And please let us know how else we can support you!\n\n"
            "Cheers,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "assigned_gmail",
            "contact_name",
            "assistant_name",
        ],
        applies_to_sub_types=["Interview Request", "Technical Interview"],
    )
)

# --- Interview Reschedule Request (Cancelled / Needs Reschedule) ---
_register(
    EmailTemplate(
        template_id="interview_reschedule_request",
        template_name="Interview Reschedule Request",
        subject_template="Heads up - {company_name} needs to reschedule",
        body_template=(
            "Hi {student_name},\n\n"
            "Heads up -- {company_name} needs to reschedule your interview. "
            "Please reach out to {contact_name} to coordinate a new time.\n\n"
            "Please let us know if you have any questions or how we can help!\n\n"
            "All my best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "contact_name",
            "assistant_name",
        ],
        applies_to_sub_types=["Interview Cancelled"],
    )
)

# --- Interview Rescheduled ---
_register(
    EmailTemplate(
        template_id="interview_rescheduled",
        template_name="Interview Rescheduled",
        subject_template="Interview Rescheduled - {company_name}",
        body_template=(
            "Hi {student_name},\n\n"
            "Congratulations! Your interview with {contact_name} from {company_name} "
            "has been rescheduled for a new date and time for {interview_datetime}.\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail} and respond to "
            "{contact_name} to confirm the reschedule of your interview.\n\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally, ALWAYS BCC "
            "c_interviews@colaberry.com on all recruiter communications, so we can "
            "accurately track the progress of the recruitment process.\n\n"
            "Good luck! And please let us know how else we can support you!\n\n\n"
            "All the best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "contact_name",
            "interview_datetime",
            "assigned_gmail",
            "assistant_name",
        ],
        applies_to_sub_types=["Interview Rescheduled"],
    )
)

# --- Next Round Assessment ---
_register(
    EmailTemplate(
        template_id="next_round_assessment",
        template_name="Next Round - Assessment",
        subject_template="Action needed: complete your assessment for {company_name}",
        body_template=(
            "Hi {student_name},\n\n\n"
            "Congratulations! {company_name} has asked you to complete an assessment "
            "for their {position_title} opportunity. This is a test, not an interview.\n\n"
            "Please see {contact_name}'s email for the details and the deadline, and complete it "
            "as soon as you can. When it is done, reply to this message with \"done\" so we know.\n\n"
            "Good luck! And please let us know how else we can support you!\n\n\n"
            "Cheers,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "position_title",
            "contact_name",
            "assistant_name",
        ],
        applies_to_sub_types=["Interview Request"],
    )
)

# --- Job Invitation ---
_register(
    EmailTemplate(
        template_id="job_invitation",
        template_name="Job Invitation",
        subject_template="{contact_name} from {company_name} reached out for a {position_title} opportunity",
        body_template=(
            "Hi {student_name},\n\n"
            "You received a request from {contact_name} for a {position_title} "
            "opportunity at {company_name}.\n\n"
            "Kindly log in to your Gmail account - {assigned_gmail}/LinkedIn account "
            "and respond to {contact_name} to confirm your opportunity interest.\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally, ALWAYS BCC "
            "c_interviews@colaberry.com on all recruiter communications, so we can "
            "accurately track the progress of the recruitment process.\n\n"
            "Note that no legitimate position will ask you for personal financial "
            "information (credit card, Social Security number, etc.) or require you "
            "to pay for a home office setup. If a recruiter contacts you by making "
            "such requests, the position is a scam, and you should not pursue it "
            "further.\n\n"
            "Please let me know if you have any questions or how else we can help!\n\n"
            "Best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "position_title",
            "contact_name",
            "assigned_gmail",
            "assistant_name",
        ],
        applies_to_sub_types=[],
    )
)

# --- More Information Request ---
_register(
    EmailTemplate(
        template_id="more_info_request",
        template_name="More Information Request",
        subject_template="More Information Request from {company_name}",
        body_template=(
            "Hi {student_name},\n\n"
            "{contact_name} from {company_name} asks for more information. "
            "Kindly log in to your Gmail account - {assigned_gmail}/LinkedIn "
            "account/Indeed account and respond to {contact_name} by EOD.\n\n"
            "REMINDER: Always communicate with your new email address for all "
            "recruitment-related matters. Additionally, ALWAYS BCC "
            "c_interviews@colaberry.com on all recruiter communications, so we can "
            "accurately track the progress of the recruitment process.\n\n"
            "Note that no legitimate position will ask you for personal financial "
            "information (credit card, Social Security number, etc.) or require you "
            "to pay for a home office setup. If a recruiter contacts you by making "
            "such requests, the position is a scam, and you should not pursue it "
            "further.\n\n"
            "Please let me know if you have any questions or how else we can help!\n\n"
            "Best,\n"
            "{assistant_name}"
        ),
        required_fields=[
            "student_name",
            "company_name",
            "contact_name",
            "assigned_gmail",
            "assistant_name",
        ],
        applies_to_sub_types=[],
    )
)


# ============================================================================
# TEMPLATE SELECTION LOGIC
# ============================================================================


def select_template(
    sub_type: str,
    is_job_machine: bool = False,
    is_next_round: bool = False,
    has_confirmed_date: bool = False,
    is_assessment: bool = False,
) -> Optional[EmailTemplate]:
    """
    Select the appropriate email template based on interview sub-type and flags.

    This is purely deterministic — no AI involved.

    Args:
        sub_type: Interview sub-type from subclassify_interview.py
        is_job_machine: Whether the email is from Job Machine platform
        is_next_round: Whether this is a second/third/subsequent round
        has_confirmed_date: Whether a confirmed date/time is present
        is_assessment: Whether this is an assessment/exercise round

    Returns:
        The matching EmailTemplate, or None if no match found
    """
    # Handle Job Machine emails with sub-types
    if sub_type == "Job Machine":
        # Job Machine emails are routed based on their actual action
        # The caller should resolve job_machine_sub_type and call again
        # with the resolved sub_type and is_job_machine=True
        logger.warning(
            "Job Machine sub-type not resolved. Caller should resolve "
            "job_machine_sub_type before selecting template."
        )
        return None

    # Interview Cancelled → Reschedule Request template
    if sub_type == "Interview Cancelled":
        return TEMPLATES["interview_reschedule_request"]

    # Interview Rescheduled
    if sub_type == "Interview Rescheduled":
        return TEMPLATES["interview_rescheduled"]

    # Assessment (next round)
    if is_assessment:
        return TEMPLATES["next_round_assessment"]

    # Interview Request (no confirmed date)
    if sub_type == "Interview Request":
        if is_next_round:
            return TEMPLATES["next_round_request"]
        if is_job_machine:
            return TEMPLATES["interview_request_first_jm"]
        return TEMPLATES["interview_request_first"]

    # Phone Screen (confirmed date)
    if sub_type == "Phone Screen":
        if is_job_machine:
            return TEMPLATES["phone_screening_scheduled_jm"]
        return TEMPLATES["phone_screening_scheduled"]

    # Client Screen (confirmed date)
    if sub_type == "Client Screen":
        if is_job_machine:
            return TEMPLATES["client_screening_scheduled_jm"]
        return TEMPLATES["client_screening_scheduled"]

    # Technical Interview (confirmed date)
    if sub_type == "Technical Interview":
        if is_job_machine:
            return TEMPLATES["technical_round_scheduled_jm"]
        return TEMPLATES["technical_round_scheduled"]

    logger.warning(f"No template found for sub-type: {sub_type}")
    return None


def get_template_by_id(template_id: str) -> Optional[EmailTemplate]:
    """
    Get a template by its ID.

    Args:
        template_id: Template identifier string

    Returns:
        The EmailTemplate or None if not found
    """
    return TEMPLATES.get(template_id)


def list_all_templates() -> List[EmailTemplate]:
    """Return all registered templates."""
    return list(TEMPLATES.values())
