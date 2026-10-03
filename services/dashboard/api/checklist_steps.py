"""
Interview process checklist step definitions.

Defines the rubric steps and sub-steps for each interview sub_type.
Step keys use dotted notation:
  - Main steps: "{sub_type}.{step_num}"
  - Sub-steps:  "{sub_type}.{step_num}.{sub_step_num}"

These are business process constants derived from the interview
processing rubric. Only completion state is stored in the database.
"""

# Every interview type follows the same three steps; only the wording of the first two sub-steps differs.
#   1. Check the email          (is it a real interview? the check is shown in Review > Student notifications)
#   2. Notify the student       (call, text and email start when the notification is approved in Review)
#   3. Make sure the student knows (follow-up status; contact them directly when the system cannot)
# The sub-step "Approve the notification" is ticked automatically when the notification is approved (see approve_step_key).

APPROVE_SUB_STEP = 3   # position of the auto-ticked sub-step inside step 2

_REAL_CHECK = "Check it is a real interview, not a job-board mailer (see the check in Review > Student notifications)"
_CONTACT_CHECK = "Check the student's phone and email are right"
_APPROVE = "Approve the notification in Review > Student notifications"
_FOLLOW_UP = "Check the follow-up status; the student's confirmation shows there"
_DIRECT = "If the student cannot be reached or has not answered, contact them directly"


def _definition(sub_type: str, label: str, verify: str, content: str) -> dict:
    def sub(step: int, n: int, text: str) -> dict:
        return {"key": f"{sub_type}.{step}.{n}", "label": text}

    return {
        "sub_type": sub_type,
        "label": label,
        "steps": [
            {"key": f"{sub_type}.1", "label": "Check the email",
             "sub_steps": [sub(1, 1, verify), sub(1, 2, _REAL_CHECK)]},
            {"key": f"{sub_type}.2", "label": "Notify the student (call, text and email)",
             "sub_steps": [sub(2, 1, _CONTACT_CHECK), sub(2, 2, content), sub(2, APPROVE_SUB_STEP, _APPROVE)]},
            {"key": f"{sub_type}.3", "label": "Make sure the student knows",
             "sub_steps": [sub(3, 1, _FOLLOW_UP), sub(3, 2, _DIRECT)]},
        ],
    }


CHECKLIST_DEFINITIONS = {d["sub_type"]: d for d in [
    _definition("interview_request", "Interview Request",
                "Verify key details: interview type, sender, time slot options",
                "Check the notification says the student has an interview and where to find the details"),
    _definition("phone_screen", "Phone Screen",
                "Verify details: type, sender, date, dial-in/phone number",
                "Check the notification gives the date/time and dial-in instructions"),
    _definition("client_screen", "Client Screen",
                "Verify details: second round, sender/HR team, date, attendees, materials needed",
                "Check the notification mentions the attendees and any preparation materials"),
    _definition("technical_interview", "Technical Interview",
                "Verify: type, sender/tech team lead, date, format/assessment type",
                "Check the notification includes preparation guidance"),
    _definition("interview_schedule", "Interview Scheduled",
                "Verify the date, time, platform and who the student will meet",
                "Check the notification gives the date, time and how to join"),
    _definition("confirmed", "Interview Confirmed",
                "Verify the confirmed date, time and platform",
                "Check the notification confirms the date, time and how to join"),
    _definition("assessment", "Assessment",
                "Verify the assessment type, deadline and link",
                "Check the notification gives the deadline and how to start"),
    _definition("final_round", "Final Round",
                "Verify the date, attendees and format of the final round",
                "Check the notification mentions the attendees and format"),
    _definition("cancelled", "Interview Cancelled",
                "Verify cancellation details and reason",
                "Check the notification explains the cancellation and suggests rescheduling if applicable"),
    _definition("rescheduled", "Interview Rescheduled",
                "Verify new date/time/platform",
                "Check the notification gives the new date/time/platform and leaves enough time to prepare"),
    _definition("job_machine", "Job Machine",
                "Identify the Job Machine sub-type (interview/reschedule/cancellation) and the real interview details",
                "Check the notification includes the Job Machine-specific instructions"),
    _definition("other", "Interview-related email",
                "Verify what the email is asking and who sent it",
                "Check the notification tells the student what they need to do"),
]}


# Map DB sub_type values (title case from AI, or snake_case from the pipeline) to the definition keys above
_SUB_TYPE_NORMALIZE = {
    "Interview Request": "interview_request",
    "Phone Screen": "phone_screen",
    "Client Screen": "client_screen",
    "Technical Interview": "technical_interview",
    "Interview Schedule": "interview_schedule",
    "Interview Confirmation": "confirmed",
    "Assessment": "assessment",
    "Final Interview Scheduled": "final_round",
    "Interview Cancelled": "cancelled",
    "Interview Rescheduled": "rescheduled",
    "Interview Reschedule": "rescheduled",
    "Job Machine": "job_machine",
    "reschedule": "rescheduled",
}
for _key in list(CHECKLIST_DEFINITIONS):
    _SUB_TYPE_NORMALIZE.setdefault(_key, _key)       # identity mappings for values already in snake_case


def normalize_sub_type(sub_type: str) -> str:
    """Normalize a sub_type value to the snake_case key used in definitions.

    Handles both title case values from the AI pipeline and
    snake_case values that may already be normalized.

    Returns the original value if no mapping is found.
    """
    return _SUB_TYPE_NORMALIZE.get(sub_type, sub_type)


def definition_key(sub_type: str) -> str:
    """The checklist definition for a sub_type; anything unknown uses the generic "other" checklist."""
    normalized = normalize_sub_type(sub_type)
    return normalized if normalized in CHECKLIST_DEFINITIONS else "other"


def approve_step_key(sub_type: str) -> str:
    """The sub-step that is ticked automatically when the student notification is approved."""
    return f"{definition_key(sub_type)}.2.{APPROVE_SUB_STEP}"


def get_all_step_keys(sub_type: str) -> list:
    """Return all valid step keys for a given sub_type."""
    defn = CHECKLIST_DEFINITIONS.get(definition_key(sub_type))
    if not defn:
        return []
    keys = []
    for step in defn["steps"]:
        keys.append(step["key"])
        for sub in step["sub_steps"]:
            keys.append(sub["key"])
    return keys
