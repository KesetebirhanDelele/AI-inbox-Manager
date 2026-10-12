"""
The wording of the interview notification, for the text and the email (the voice agent's wording lives in
docs/voice-agent-outbound-interview-prompt.md). Pure functions: facts in, text out.

Rules (Kes, 2026-10-12, after an automated content audit flagged the old wording):
  * Colaberry does not offer the position, the employer does: never written as if Colaberry were hiring.
  * The job title is NEVER named ("the position you applied for"), because titles such as "Data Analyst" or "SQL Developer"
    are on the audit's flagged list. An employer name that itself contains a flagged word is replaced by "the employer".
  * The text begins exactly "[Interview Notification]" and is 320 characters or fewer; the email's first line is exactly
    "[Interview Notification]". Neutral wording, no promises, no marketing. No link in a text in a text or an email.
  * No phone number and no link anywhere (Kes, 2026-10-12): the candidate confirms by replying YES to the text or the email, or by
    saying yes on the call. The meeting link is in the employer's own invitation email.
"""
from datetime import datetime
from typing import Any, Dict, Optional

import content_audit as audit

TAG = audit.REQUIRED_START


def safe_employer(name: Optional[str]) -> str:
    """The employer's name, or "the employer" when it is missing or would trip the audit (for example "Excel Staffing")."""
    n = " ".join((name or "").split())
    if not n or audit.contains_flagged(n):
        return "the employer"
    return n[:60]


def nice_date(iso: Optional[str]) -> str:
    """'2026-10-08' -> 'Thu Oct 8'. Anything that is not an ISO date is returned as it is."""
    if not iso:
        return ""
    try:
        d = datetime.strptime(str(iso)[:10], "%Y-%m-%d")
        return f"{d.strftime('%a %b')} {d.day}"
    except ValueError:
        return str(iso)


def facts_from_event(event: Any, student: Any = None, status: str = "") -> Dict[str, str]:
    """Plain facts for the builders from an InterviewEvent (or anything with the same attributes) and the student."""
    def g(name):
        v = getattr(event, name, None)
        return str(v).strip() if v not in (None, "") else ""
    full = (getattr(student, "full_name", None) or "").strip()
    sub = g("sub_type")
    state = status or ("cancelled" if sub == "Interview Cancelled" else "rescheduled" if sub == "Interview Rescheduled"
                       else "assessment" if sub == "Assessment" else "")
    return {
        "first_name": full.split()[0] if full else "there",
        "employer": safe_employer(g("company_name")),
        "date": nice_date(g("interview_date")),
        "time": " ".join(x for x in (g("interview_time"), g("interview_timezone")) if x),
        "format": g("interview_format"),
        "link": g("meeting_link"),
        "employer_contact": g("contact_name"),
        "status": state,
    }


def facts_from_dict(classification: Dict[str, Any], student_info: Dict[str, Any], sub_type: str = "") -> Dict[str, str]:
    """The same facts from the sub-classifier's result and the student record (used when the draft is created)."""
    def g(name):
        v = classification.get(name)
        return str(v).strip() if v not in (None, "") else ""
    full = (student_info.get("full_name") or "").strip()
    state = ("cancelled" if sub_type == "Interview Cancelled" else "rescheduled" if sub_type == "Interview Rescheduled"
             else "assessment" if sub_type == "Assessment" else "")
    return {
        "first_name": full.split()[0] if full else "there",
        "employer": safe_employer(g("company_name")),
        "date": nice_date(g("interview_date")),
        "time": " ".join(x for x in (g("interview_time"), g("interview_timezone")) if x),
        "format": g("interview_format"),
        "link": g("meeting_link"),
        "employer_contact": g("contact_name"),
        "status": state,
    }


def _is_online(f: Dict[str, str]) -> bool:
    """A video or online interview: there is a meeting link in the employer's own invitation, so we point to it and never repeat it."""
    text = f"{f.get('format', '')} {f.get('link', '')}".lower()
    return bool(f.get("link")) or any(w in text for w in ("video", "online", "virtual", "zoom", "teams", "meet"))


def _when(f: Dict[str, str]) -> str:
    if f.get("date"):
        return f"on {f['date']}" + (f" at {f['time']}" if f.get("time") else "")
    return ""


def _headline(f: Dict[str, str], lead: str) -> str:
    """'your interview with Acme for the position you applied for is on Thu Oct 8 at 2:00 PM CT' (or the unscheduled / changed form)."""
    if f.get("status") == "assessment":
        return (f"{lead}you have an online assessment to complete for {f['employer']} for the position you applied for. "
                "It is a test, not an interview. Open the invitation email from the employer to start it")
    base = f"your interview with {f['employer']} for the position you applied for"
    if f.get("status") == "cancelled":
        return f"{lead}{base} has been cancelled by the employer"
    when = _when(f)
    if f.get("status") == "rescheduled":
        return f"{lead}{base} has been rescheduled" + (f" and is now {when}" if when else "")
    return f"{lead}{base} is {when}" if when else f"{lead}{base} is being scheduled. The employer will confirm the date and time"


def sms(f: Dict[str, str], step_tag: str = "", ref: str = "") -> str:
    """One text, 320 characters or fewer, starting exactly '[Interview Notification]'. Reminders add their label after the tag."""
    lead = f"Hello {f['first_name']}, "
    where = ""
    if f.get("format"):
        where = f" Format: {f['format']}."
    if _is_online(f):
        where += " Use the meeting link in the employer's invitation email."
    reply = "Reply YES to confirm you got this."
    tail = f" Ref {ref}" if ref else ""

    def build(employer_f):
        return f"{TAG} {step_tag}{_headline(employer_f, lead)}.{where} From Colaberry Interview Support. {reply}{tail}"
    text = build(f)
    if len(text) > audit.SMS_MAX_CHARS:                    # drop the sender line before anything the student needs
        text = text.replace(" From Colaberry Interview Support.", "")
    if len(text) > audit.SMS_MAX_CHARS:
        text = build({**f, "employer": f["employer"][:30].rstrip()}).replace(" From Colaberry Interview Support.", "")
    return text


def email_subject(f: Dict[str, str]) -> str:
    """Plain, not scanned by the audit: 'Your interview on Thu Oct 8'."""
    if f.get("status") == "cancelled":
        return "Your interview has been cancelled"
    if f.get("status") == "assessment":
        return "Your assessment notice"
    if f.get("date"):
        return f"Your interview on {f['date']}"
    return "Your interview notification"


def email_body(f: Dict[str, str], ack_line: bool = False) -> str:
    """The email: first line exactly '[Interview Notification]', the same facts as the text, and a short preparation note."""
    if f.get("status") == "assessment":
        intro = (f"This is a notice about an assessment from {f['employer']} for the position you applied for. "
                 "The employer arranged it. Colaberry Interview Support is passing the details on to you.")
    else:
        intro = (f"This is a notice about an interview with {f['employer']} for the position you applied for. "
                 "The employer arranged this interview. Colaberry Interview Support is passing the details on to you.")
    lines = [TAG, "", f"Hello {f['first_name']},", "", intro, ""]
    if f.get("status") == "assessment":
        lines += ["The employer has asked you to complete an online assessment. It is a test, not an interview.", "",
                  "The invitation with the instructions and the deadline is in an email from the employer or its test provider. "
                  "Please open it and complete the assessment as soon as you can.", "", "How to prepare:",
                  "- Read all of the instructions before you start.",
                  "- Use a quiet place and a reliable internet connection.",
                  "- Check the deadline in the invitation and plan your time."]
    elif f.get("status") == "cancelled":
        lines += ["The employer has cancelled this interview. Please reply to the employer's email to ask for a new time, "
                  "or reply to this email if you need help."]
    else:
        headline = _headline(f, "")
        lines.append(headline[0].upper() + headline[1:] + ".")
        lines.append("")
        if f.get("date"):
            lines.append(f"Date: {f['date']}")
        if f.get("time"):
            lines.append(f"Time: {f['time']}")
        if f.get("format"):
            lines.append(f"Format: {f['format']}")
        if _is_online(f):
            lines.append("Meeting link: use the link in the employer's invitation email.")
        if f.get("employer_contact"):
            lines.append(f"Employer contact: {f['employer_contact']}")
        lines += ["", "How to prepare:",
                  "- Join five minutes early, and test your audio, video and internet connection first.",
                  "- Have your resume, a pen and paper ready.",
                  "- Read the position description again and think of questions to ask."]
    lines += ["", "Please confirm you received this message by replying YES to this email.", "", "Colaberry Interview Support"]
    return "\n".join(lines)
