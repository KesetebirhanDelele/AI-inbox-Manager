"""
Email classification execution script.

This script handles email classification using OpenAI API with production-grade
error handling, validation, and structured output.

Design principles:
- Pure logic separated from I/O for testability
- Deterministic validation and business rules
- Comprehensive error handling
- Audit logging for all classification attempts
"""

import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Approved email categories (must match exactly)
APPROVED_CATEGORIES = [
    "Interview Request",
    "Interview Schedule",
    "Interview Reschedule",
    "Interview Confirmation",
    "Interview Cancelled",
    "Final Interview Scheduled",
    "Instant Interview",
    "Client Screen",
    "Technical Interview",
    "Interview Follow-up",
    "Phone Screen",
    "Rejection",
    "Offer",
    "Job Alert",
    "Job Invite",
    "Job Machine",
    "Application Notification",
    "More Information Request",
    "Background Check",
    "Assessment",
    "LinkedIn Notification",
    "Google Sheet Request",
    "Gmail Notification",
    "Forwarded Email",
    "Basecamp",
    "Account Recovery",
    "Other"
]

# Production classification prompt
CLASSIFICATION_PROMPT = """# Email Classification System - Production Prompt

You are an AI classifier for an automated inbox management system that processes interview-related emails for Colaberry career program.

## Your Responsibilities

1. Classify emails into exactly ONE category from the approved list
2. Extract all relevant structured data
3. Assign calibrated confidence scores
4. Detect edge cases requiring human review
5. Provide clear reasoning for decisions
6. Return valid, complete JSON output

---

## CLASSIFICATION CATEGORIES (27 Total; the folder list follows Colaberry's 'Email Management - Labels' workbook)

### Primary Categories

**1. Interview Request** 🔴 HIGH PRIORITY
- **Definition**: Initial outreach requesting an interview or availability, NO TIME CONFIRMED YET
- **What it means**: "They want to talk, but nothing is scheduled yet"
- **Key Signals**:
  - Asking for availability: "Are you available...", "Can you share availability?"
  - Invitation to start scheduling: "We'd like to set up...", "Would you be available for..."
  - Phone screen invites WITHOUT confirmed time
  - Recruiter outreach via LinkedIn/Indeed/email
- **Must NOT have**: Calendar invite, confirmed date/time
- **Must be a DIRECT offer of an interview**: the email itself asks to schedule or hold an interview with THIS candidate (asks for availability, offers time slots, a scheduling link, or names an interview date/time). 
  A job description, an open role, an "urgent opening", "send your resume and rate", or a job title that merely contains the word "interview" ("Immediate Interview Role") is NOT an Interview Request: it is a **Job Invite**. 
  The recruiter decides whether to pursue a candidate AFTER the candidate replies with an updated resume and shows interest; only the later message that actually offers an interview is an Interview Request.
- **Confidence**: High if asks for availability without confirming time
- **Critical**: These emails REQUIRE IMMEDIATE ACTION and must stay in inbox

**2. Interview Schedule**
- **Definition**: Back-and-forth coordination or scheduling in progress
- **What it means**: "Time negotiation is happening, not final yet"
- **Key Signals**:
  - Time negotiation: "Does Tuesday at 2pm work?"
  - Scheduling links: Calendly, Microsoft Bookings, scheduling portal
  - Availability sharing: "Here's my availability"
  - Follow-ups to lock a time
- **Status**: Still fluid, time may change
- **Confidence**: High if scheduling links or time options present
- **Note**: Different from Interview Request (which initiates) and Interview Confirmation (which finalizes)

**3. Interview Reschedule**
- Request to change existing interview time
- Signals: "reschedule", "change the time", "new time", "move our meeting"
- Confidence: High if references previous interview

**4. Interview Confirmation**
- **Definition**: Final confirmation with locked date/time
- **What it means**: "It's locked. Show up."
- **Key Signals**:
  - Final date & time confirmed: "Your interview is confirmed for..."
  - Calendar invite present/attached
  - Meeting links included (Zoom, Teams, Google Meet)
  - Confirmation language: "Looking forward to meeting you", "Interview confirmed"
  - Location/link details provided
- **Must have**: Confirmed date AND time
- **No more**: Negotiation or "does this work?" language
- **Confidence**: High if date, time, and location all present
- **Note**: Can trigger interview prep workflows
- **CRITICAL EXCLUSIONS — these are NEVER "Interview Confirmation"**:
  - Emails with "Job Alert", "Job Invite", "job opportunity", "jobs matching" in subject → "Job Alert" or "Job Invite"
  - Promotional/retail emails ("cashback", "% off", "shop now", "gear", "apparel") → "Other"
  - LinkedIn digest or job recommendation emails → "LinkedIn Notification" or "Job Alert"
  - Any email that does NOT have a specific candidate + specific confirmed date/time for a specific role
  - "Introduction Call" messages that are actually cold outreach or general scheduling invites without a confirmed time → "Interview Request" or "Interview Schedule"

**5. Interview Cancelled**
- Interview explicitly cancelled
- Signals: "cancel", "no longer moving forward at this time", "position filled"
- Confidence: High if clear cancellation language

**7. Final Interview Scheduled**
- Last round interview confirmation
- Signals: "final round", "final interview", "meet with executive team"
- Confidence: Medium-High (sometimes implicit)

**8. Rejection**
- Candidate not selected for position
- Signals: "decided to move forward with other candidates", "not a fit", "unfortunately"
- Confidence: High if explicit rejection language

**9. Job Alert**
- **Job Alert vs Job Invite**: Job Alert = automated, bulk, recurring digest or "jobs near you" list from a platform or system (many listings, not about this candidate). Job Invite = a recruiter or staffing firm writing about ONE specific role (location, contract/W2, rate, "send your resume"). Neither is an interview.
- **Automated job posting notification - NOT a personal interview request**
- **SENDER RULE**: If the sender email domain is @indeed.com, @jobleads.com, @ziprecruiter.com, @glassdoor.com, @monster.com, @dice.com, @careerbuilder.com, @simplyhired.com, @lensa.com, @linkedin.com (job digest), or any job board aggregator → ALWAYS "Job Alert" regardless of subject content
- Signals: "jobs matching your criteria", "new opportunities", "job alert", "jobs just posted", job recommendations, hiring alerts, "X more jobs"
- Confidence: Very High if from job board domain; High if job alert language present
- **Critical**: Must distinguish from Interview Request (which is PERSONAL direct outreach from a company)

**10. Application Notification**
- Confirmation that application was received
- Signals: "application received", "thank you for applying", "we've received your application"
- Confidence: High if acknowledgment language present

**11. More Information Request**
- Company needs additional information/documents
- Signals: "please provide", "need additional information", "send us your"
- Confidence: High if explicit request present

**12. Offer**
- **STRICT DEFINITION**: A job offer of employment extended to a specific candidate by an employer
- **Must have**: Language like "pleased to offer you the position", "offer letter", "extend an offer of employment", salary/compensation details, start date for a job role
- **CRITICAL EXCLUSIONS — these are NEVER "Offer"**:
  - Retail deals, sales, discounts ("50% off", "snag a deal", "save $X") → classify as "Other"
  - Promotional marketing from stores, brands, or retailers → classify as "Other"
  - Job board listings or job recommendation emails → classify as "Job Alert" or "Job Invite"
  - Any email where "offer" refers to a product, service, discount, or subscription
- Confidence: Very High ONLY if it contains explicit employment offer language with a job role

**13. Background Check**
- Background check or reference request
- Signals: "background check", "reference check", "verification"
- Confidence: High if explicit check mentioned

**14. Assessment**
- Request to complete assessment/test
- Signals: "complete assessment", "technical test", "coding challenge", "skills evaluation"
- Confidence: High if test/assessment mentioned

**15. Phone Screen**
- Initial phone screening request
- Signals: "phone screen", "brief call", "quick conversation", "initial chat"
- Confidence: Medium-High (can overlap with Interview Request)

**16. Instant Interview**
- Immediate or on-the-spot interview request with no scheduling needed
- Signals: "interview right now", "instant interview", "interview immediately", "start now"
- Confidence: High if urgency and immediacy are explicit

**17. Client Screen**
- Screening conducted by the client company (not an internal HR/recruiter screen)
- Signals: "client interview", "client screen", "meet with the client", "client wants to speak"
- Confidence: High if client involvement is explicit

**17b. Technical Interview**
- A SCHEDULED technical interview: a live conversation with a panel or technical lead (plus HR), a coding/system-design interview, with a date or meeting details
- Signals: "technical interview", "technical round", "system design interview", "panel interview", "coding interview" with a time or link
- NOT this: a take-home test or online test link to complete alone → "Assessment". Asking for availability with no time → "Interview Request".
- Confidence: High if a technical interview is explicit and details are given

**17c. Interview Follow-up**
- Sent AFTER an interview already took place: thank-you notes, "checking in on the outcome", feedback, "next steps", status updates about a completed interview
- Signals: "thank you for your time", "following up on our interview", "next steps", "feedback", "checking in", reference to a previously completed interview
- NOT this: a request or invitation for a NEW interview → "Interview Request"; "we regret to inform you" → "Rejection"; an offer → "Offer"
- Confidence: High if it clearly refers to an interview that already happened

**18. Job Invite**
- Direct invitation to apply for a specific job role, INCLUDING staffing-firm / recruiter outreach about one open role (contract/W2, location, rate, "send your resume", "urgent opening")
- Signals: "you've been invited to apply", "job opportunity for you", "we think you'd be a great fit for"
- Confidence: High if personal job invitation language present

**19. Job Machine**
- Automated Colaberry job application system notification or job-machine-submitted application receipt
- Signals: references to Colaberry job machine, automated application submissions, job machine results
- Confidence: High if job machine system is referenced

**20. LinkedIn Notification**
- Automated notification from LinkedIn (connection requests, profile views, InMail, job alerts)
- **SENDER RULE**: The sender MUST be from @linkedin.com or @e.linkedin.com domain. If not from LinkedIn, do NOT use this category.
- Signals: "viewed your profile", "wants to connect", LinkedIn InMail, LinkedIn job alerts
- Confidence: Very High if from LinkedIn domain; do NOT assign this if sender is not from LinkedIn

**21. Google Sheet Request**
- Request or notification related to a Google Sheet (access request, sharing, update)
- Signals: "Google Sheets", "spreadsheet access", "shared a Google Sheet", "sheet update"
- Confidence: High if Google Sheets is explicitly mentioned

**22. Gmail Notification**
- **STRICT DEFINITION**: System notification sent BY Gmail/Google about your Gmail account
- **SENDER RULE**: The sender MUST be from an official Google domain (@google.com, @accounts.google.com, @googlemail.com, no-reply@google.com). If not from Google's official system, do NOT use this category — PERIOD.
- **Specific signals**: Gmail storage warnings, Gmail security alert, Gmail forwarding confirmation, Google account sign-in notice
- **CRITICAL EXCLUSIONS — these are NEVER "Gmail Notification"**:
  - Emails from TikTok, Facebook, Instagram, Twitter/X, YouTube, or any social media platform → "Other"
  - Emails from Indeed, LinkedIn, ZipRecruiter → "Job Alert"
  - Emails from retailers or promotional senders → "Other"
  - Verification codes from non-Google services → "Account Recovery"
  - Recruiter outreach or newsletter emails → appropriate category (not Gmail Notification)
  - ServiceNow, appointment, or scheduling notifications from non-Google services → "Other"
  - **Any email where the From/sender address is NOT an official @google.com or @accounts.google.com address**
- Confidence: Very High ONLY if sender is from official Google domain AND content is about Gmail/Google account
- **TEST**: Before assigning Gmail Notification, ask yourself: "Is the FROM address @google.com or @accounts.google.com?" If NO → use a different category.

**23. Forwarded Email**
- Email that has been forwarded as context or for action
- Signals: "---------- Forwarded message ---------", "FW:", "Fwd:", forwarding language
- Confidence: High if forwarding headers present

**24. Basecamp**
- Notification or message from Basecamp project management platform
- Signals: from basecamp.com, "Basecamp", project or task notification from Basecamp
- Confidence: Very High if Basecamp sender or branding

**25. Account Recovery**
- **STRICT DEFINITION**: Password reset, account verification, or security code email from ANY service
- **Signals**: "reset your password", "verify your account", "your verification code is", "account recovery", "security code", "confirm your email address", OTP codes
- **CRITICAL EXCLUSIONS — these are NEVER "Account Recovery"**:
  - Job alert or job recommendation emails → "Job Alert"
  - Retail or promotional emails → "Other"
  - LinkedIn/social notifications → "LinkedIn Notification"
  - General job-related emails → appropriate job category
- Confidence: Very High ONLY if the email contains an actual reset link, verification code, or account security action required

**26. Other**
- Does not fit above categories
- Use when: unclear intent, spam, non-relevant, multi-intent without clear primary
- Confidence: Low-Medium
- **ALWAYS flag for manual review**

---

## CLASSIFICATION RULES

### Decision Framework
1. **Read subject line first** - often contains primary intent
2. **Identify sender type** - company, recruiter, job board, automated system
3. **Find primary intent** - what action is required or being communicated?
4. **Check for explicit signals** - dates, times, keywords that confirm category
5. **Assess confidence** - how certain are you based on available evidence?

### Disambiguation Rules

**CRITICAL DISTINCTIONS** (Use the user's golden rule):
- **Interview Request vs Interview Schedule vs Interview Confirmation**:
  - Interview Request = asking for availability, NO time confirmed → STAYS IN INBOX
  - Interview Schedule = negotiating/coordinating time, still fluid → can be organized
  - Interview Confirmation = locked date/time with calendar invite → can be organized

- **Interview Request vs Job Alert**:
  - Interview Request = PERSONAL outreach from recruiter/company asking to schedule
  - Job Alert = AUTOMATED notification about job postings (Indeed, LinkedIn, ZipRecruiter)
  - If from job board aggregator → Job Alert (even if says "interview")
  - If from real company/recruiter directly → Interview Request

- **Phone Screen vs Interview Request**:
  - Phone Screen = initial/brief screening call
  - Interview Request = formal interview invitation

- **Interview Confirmation vs Final Interview Scheduled**:
  - Interview Confirmation = any round that's confirmed
  - Final Interview Scheduled = specifically the last/final round

- **Rejection vs Interview Cancelled**:
  - Rejection = candidate not selected
  - Cancelled = interview won't happen but may not be rejection

- **Once a time is confirmed, the TYPE of interview decides the category** (Interview Confirmation / Final Interview Scheduled are retired in favour of these):
  - client / second-round interview with the client → Client Screen
  - technical or panel interview → Technical Interview
  - call with an HR person or recruiter → Phone Screen
  - type unclear → Interview Request (a person decides)

- **Technical Interview vs Assessment vs Interview Request**:
  - Technical Interview = scheduled live technical conversation with people (panel/technical lead)
  - Assessment = a test or exercise the candidate completes alone
  - Interview Request = asking for availability, no time confirmed (even if the interview will be technical)

- **Interview Follow-up vs others**: follow-up refers to an interview that ALREADY happened; a new interview invitation is Interview Request.

- **Assessment vs Interview**:
  - Assessment = take-home or separate test
  - Interview = live conversation

- **More Info Request vs Assessment**:
  - More Info = documents/data
  - Assessment = skills evaluation

### Confidence Calibration
- **0.95-1.0**: Explicit category keywords, clear intent, all key data present
- **0.85-0.94**: Strong signals, minor ambiguity, most data present
- **0.70-0.84**: Moderate signals, some ambiguity, partial data
- **0.50-0.69**: Weak signals, significant ambiguity, limited data
- **0.00-0.49**: Unclear intent, missing data, requires human review

**Rule**: If confidence < 0.70, ALWAYS set `requires_manual_review: true`

---

## EDGE CASE DETECTION

You must detect and flag these edge cases:

### Edge Case Types

**multi-intent**
- Email contains multiple distinct purposes
- Example: "Your application was received [Application Notification] and we'd like to schedule an interview [Interview Request]"
- Action: Choose primary intent, flag secondary intent in reasoning

**unclear**
- Cannot determine primary intent with confidence
- Example: Vague language, missing context, automated message without clear category
- Action: Label as "Other", require manual review

**chain**
- Part of ongoing email thread requiring context
- Example: "Re: Re: Following up" without clear standalone intent
- Action: Extract what you can, flag for context review

**spam**
- Irrelevant marketing, phishing, obvious spam
- Example: Generic job board spam, unrelated promotions
- Action: Label as "Other", note spam in reasoning

**non-english**
- Email not primarily in English
- Action: Note language, attempt classification if possible, flag for review

**time-sensitive**
- Requires urgent action (interview in <24 hours, expiring offer)
- Action: Extract urgency indicator, flag for priority review

**missing-critical-data**
- Category is clear but critical data is missing
- Example: Interview scheduled but no date/time provided
- Action: Classify correctly, flag missing data in edge_case reasoning

---

## DATA EXTRACTION RULES

### Extraction Guidelines
- **Only extract if CONFIDENT** (>80% sure)
- **Use null for missing/uncertain fields**
- **Preserve exact names and titles as written**
- **Parse dates to ISO 8601 format (YYYY-MM-DD)**
- **Parse times to 24-hour format (HH:MM) with timezone if available**

### Required Fields

- company_name: string | null (Hiring company, not recruiting agency)
- position_title: string | null (Job title/role)
- contact_name: string | null (HR/recruiter name)
- contact_email: string | null (Contact email address)
- interview_date: YYYY-MM-DD | null (Interview date, ISO 8601)
- interview_time: HH:MM | null (Interview time, 24-hour)
- interview_timezone: string | null (Timezone, e.g. EST, PST)
- interview_type: string | null (phone | video | in-person | technical)
- interview_location: string | null (Physical address or video link)
- action_required: string | null (What the candidate must do)
- deadline: YYYY-MM-DD | null (Action deadline if specified)

### Special Extraction Notes
- **company_name**: Extract ultimate employer, not staffing agency (unless agency is employer)
- **interview_type**: Infer from context if not explicit ("Zoom link" = video, "our office" = in-person)
- **action_required**: Summarize in 1 sentence what candidate needs to do

---

## QUICK DISAMBIGUATION TABLE (apply these FIRST before anything else)

| Situation | Correct Category |
|---|---|
| Sender domain is @linkedin.com or @e.linkedin.com | LinkedIn Notification |
| Sender domain is @indeed.com, @jobleads.com, @ziprecruiter.com, @lensa.com, @dice.com, @monster.com | Job Alert |
| Sender domain is @google.com, @accounts.google.com AND about Gmail account | Gmail Notification |
| Sender domain is NOT @google.com/@accounts.google.com | NEVER "Gmail Notification" |
| Sender is TikTok, Facebook, Instagram, Twitter, YouTube, or social media | Other |
| Subject contains "Job Alert", "Job Invite", "jobs matching" | Job Alert or Job Invite — NEVER Interview Confirmation |
| Email contains retail deal / discount / sale / cashback ("50% off", "save $X", "cashback") | Other |
| Email is a job offer WITH employment language (offer letter, salary, start date) | Offer |
| Email contains verification code / password reset link | Account Recovery |
| Personal recruiter directly asking for availability — NO confirmed time | Interview Request |
| Automated job posting notification from job board | Job Alert |

**GOLDEN RULE**: When in doubt, ask "Is this from a person at a real company, directly about THIS candidate?"
- Yes → likely Interview Request / Interview Schedule / Offer
- No → likely Job Alert / LinkedIn Notification / Other

---

## OUTPUT FORMAT

Return ONLY valid JSON. The response must include:
- category: exact string from 14 approved categories
- confidence: number 0.0 to 1.0
- requires_manual_review: boolean
- reasoning: 1-3 sentences explaining the classification
- edge_case: object with is_edge_case, type, confidence, reasoning
- extracted_data: object with all extraction fields (use null for missing data)

---

## CRITICAL RULES

1. **Never hallucinate categories** - Use only the 14 approved categories
2. **Never skip reasoning** - Every classification must explain "why"
3. **Never return malformed JSON** - Validate structure before output
4. **Never overstate confidence** - Be honest about uncertainty
5. **Never extract uncertain data** - Use null instead of guessing
6. **Always flag low confidence** - Set requires_manual_review: true if confidence < 0.70
7. **Always preserve user data** - Never modify or "clean" extracted names, emails, or content

---

## RESPONSE

Analyze the email below and respond with ONLY the JSON classification object. No additional text.

Subject: {subject}
From: {sender_email}
Sender Name: {sender_name}
Date: {email_date}
Content:
{body_content}
"""


def format_email_for_prompt(email_data: Dict[str, Any]) -> str:
    """
    Format email data into the prompt format expected by the AI API.

    Args:
        email_data: Dictionary with keys: subject, sender_email, sender_name,
                   email_date, body_content

    Returns:
        Formatted prompt string ready for OpenAI API
    """
    return CLASSIFICATION_PROMPT.format(
        subject=email_data.get("subject", ""),
        sender_email=email_data.get("sender_email", ""),
        sender_name=email_data.get("sender_name", ""),
        email_date=email_data.get("email_date", ""),
        body_content=email_data.get("body_content", "")
    )


def _backoff_wait(attempt: int, retry_after: Optional[float] = None) -> float:
    """
    Calculate wait time for exponential backoff.

    Args:
        attempt: Current attempt number (1-based)
        retry_after: Server-supplied retry-after value (seconds), overrides backoff

    Returns:
        Seconds to wait before next retry
    """
    if retry_after is not None:
        return float(retry_after) + random.uniform(0, 1)
    # 2^attempt + jitter: 2.x, 4.x, 8.x seconds
    return (2 ** attempt) + random.uniform(0, 1)


def call_claude_api(
    prompt: str,
    api_key: Optional[str] = None,
    model: str = "gpt-4o-mini",
    max_tokens: int = 800,
    temperature: float = 0.0,
    max_retries: int = 3,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """
    Call OpenAI API with the classification prompt.

    Includes exponential backoff retry for transient errors:
    - 429 Rate Limit  — respects Retry-After header, then backs off
    - 500/502/503/529 — server errors, retried with backoff
    - Network/timeout — connection errors, retried with backoff

    Non-retryable errors (401, 400, 404, etc.) surface immediately.

    Args:
        prompt: Formatted classification prompt
        api_key: OpenAI API key (reads from OPENAI_API_KEY env var if not provided)
        model: OpenAI model to use (gpt-4o, gpt-4-turbo, etc.)
        max_tokens: Maximum tokens in response
        temperature: Temperature for generation (0.0 for deterministic)
        max_retries: Maximum number of attempts (default 3)
        timeout: Per-call HTTP timeout in seconds (default 60)

    Returns:
        Dict with keys: response (str), usage (dict: input_tokens, output_tokens)

    Raises:
        RuntimeError: If all retries are exhausted or a non-retryable error occurs
        ValueError: If API key is missing
    """
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not found. Set environment variable or pass api_key parameter."
        )

    try:
        import openai
    except ImportError:
        raise RuntimeError("openai library not installed. Run: pip install openai")

    # Retryable HTTP status codes
    RETRYABLE_STATUS = {500, 502, 503, 529}

    client = openai.OpenAI(api_key=api_key, timeout=timeout)

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Calling OpenAI API (model={model}, attempt={attempt}/{max_retries})")
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "You are an email classification system. Always respond with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            response_text = response.choices[0].message.content
            logger.info("OpenAI API call succeeded")
            return {
                "response": response_text,
                "usage": {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                }
            }

        except openai.RateLimitError as e:
            # 429 — check for Retry-After header first
            retry_after = getattr(e, "retry_after", None)
            wait = _backoff_wait(attempt, retry_after=retry_after)
            if attempt == max_retries:
                logger.error(f"Rate limit: exhausted {max_retries} retries")
                raise RuntimeError(f"OpenAI rate limit exceeded after {max_retries} attempts: {e}")
            logger.warning(
                f"Rate limit (429), retry {attempt}/{max_retries} in {wait:.1f}s"
                + (f" (Retry-After={retry_after})" if retry_after else "")
            )
            time.sleep(wait)

        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            wait = _backoff_wait(attempt)
            if attempt == max_retries:
                logger.error(f"Network error: exhausted {max_retries} retries")
                raise RuntimeError(f"OpenAI network error after {max_retries} attempts: {e}")
            logger.warning(f"Network error ({type(e).__name__}), retry {attempt}/{max_retries} in {wait:.1f}s")
            time.sleep(wait)

        except openai.APIStatusError as e:
            if e.status_code in RETRYABLE_STATUS and attempt < max_retries:
                wait = _backoff_wait(attempt)
                logger.warning(f"Server error (HTTP {e.status_code}), retry {attempt}/{max_retries} in {wait:.1f}s")
                time.sleep(wait)
            else:
                raise RuntimeError(f"OpenAI API error HTTP {e.status_code}: {e}")

        except openai.OpenAIError as e:
            # Auth errors, bad requests, etc. — do not retry
            raise RuntimeError(f"OpenAI API error (non-retryable): {e}")

        except Exception as e:
            raise RuntimeError(f"Unexpected error calling OpenAI API: {e}")

    # Should not reach here, but satisfy type checker
    raise RuntimeError(f"OpenAI API failed after {max_retries} attempts")


def parse_classification_response(response_text: str) -> Dict[str, Any]:
    """
    Parse JSON response from AI API.

    Args:
        response_text: Raw text response from the API

    Returns:
        Parsed JSON classification result

    Raises:
        json.JSONDecodeError: If response is not valid JSON
    """
    # Try to extract JSON from response (API sometimes adds markdown)
    response_text = response_text.strip()

    # Remove markdown code blocks if present
    if response_text.startswith("```json"):
        response_text = response_text[7:]  # Remove ```json
    if response_text.startswith("```"):
        response_text = response_text[3:]  # Remove ```
    if response_text.endswith("```"):
        response_text = response_text[:-3]  # Remove trailing ```

    response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Response text: {response_text[:500]}")
        raise


# Categories the workbook retires. Their mail is re-filed by interview type (decision with Ali, 2026-10-09).
RETIRED_INTERVIEW_CATEGORIES = {
    "Interview Schedule": "Interview Request",
    "Interview Confirmation": None,        # decided by type below
    "Final Interview Scheduled": None,     # decided by type below
}


def remap_retired_category(category: str, extracted: Optional[Dict[str, Any]], email_data: Optional[Dict[str, Any]]) -> str:
    """Pure rule: the category a retired interview category becomes (unchanged for every other category)."""
    if category not in RETIRED_INTERVIEW_CATEGORIES:
        return category
    fixed = RETIRED_INTERVIEW_CATEGORIES[category]
    if fixed:
        return fixed
    text = " ".join([
        str((extracted or {}).get("interview_type") or ""),
        str((email_data or {}).get("subject") or ""),
        str((email_data or {}).get("body_content") or "")[:1500],
    ]).lower()
    if "client" in text:
        return "Client Screen"
    if any(k in text for k in ("technical", "panel", "coding", "system design")):
        return "Technical Interview"
    if any(k in text for k in ("phone", "call", "screening")):
        return "Phone Screen"
    return "Interview Request"


def apply_business_rules(
    classification: Dict[str, Any],
    email_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Apply business rules to classification result.

    This is pure deterministic logic - no API calls, easily testable.

    Args:
        classification: Raw classification result from Claude
        email_data: Original email fields (used for sender-domain enforcement)

    Returns:
        Classification with business rules applied
    """
    # Make a copy to avoid mutating input
    result = classification.copy()

    # ── Sender-domain enforcement (override AI hallucinations) ───────────────
    # These rules are deterministic guards that correct the most common
    # category leakage regardless of what the AI returned.
    if email_data is not None:
        from_addr = (
            email_data.get("sender_email") or email_data.get("from") or ""
        ).lower()

        # "Gmail Notification" MUST come from an official Google domain.
        # Any other sender that slips past the pre-classifier gets corrected here.
        GOOGLE_DOMAINS = ["@google.com", "@accounts.google.com", "@googlemail.com"]
        if result.get("category") == "Gmail Notification" and not any(
            d in from_addr for d in GOOGLE_DOMAINS
        ):
            original = result["category"]
            result["category"] = "Other"
            result["requires_manual_review"] = True
            logger.warning(
                f"Domain override: '{original}' → 'Other' — sender '{from_addr}' "
                f"is not a Google domain"
            )

        # "LinkedIn Notification" MUST come from LinkedIn.
        LINKEDIN_DOMAINS = ["@linkedin.com", "@e.linkedin.com"]
        if result.get("category") == "LinkedIn Notification" and not any(
            d in from_addr for d in LINKEDIN_DOMAINS
        ):
            original = result["category"]
            result["category"] = "Other"
            result["requires_manual_review"] = True
            logger.warning(
                f"Domain override: '{original}' → 'Other' — sender '{from_addr}' "
                f"is not a LinkedIn domain"
            )

    # Retired interview categories: CATEGORY_REMAP_MODE = off | shadow (default: log the new label only) | live (use it).
    mode = os.getenv("CATEGORY_REMAP_MODE", "shadow").lower()
    if mode != "off":
        remapped = remap_retired_category(result.get("category", ""), result.get("extracted_data"), email_data)
        if remapped != result.get("category"):
            logger.info(f"[remap {mode}] '{result.get('category')}' -> '{remapped}'")
            result["category_shadow"] = remapped
            if mode == "live":
                result["category_original"] = result["category"]
                result["category"] = remapped

    # Rule 1: Low confidence requires manual review
    if result.get("confidence", 0) < 0.70:
        result["requires_manual_review"] = True
        logger.info(
            f"Flagged for manual review: confidence {result['confidence']} < 0.70"
        )

    # Rule 2: "Other" category always requires manual review
    if result.get("category") == "Other":
        result["requires_manual_review"] = True
        logger.info("Flagged for manual review: category is 'Other'")

    # Rule 3: Edge cases require manual review
    edge_case = result.get("edge_case", {})
    if edge_case.get("is_edge_case", False):
        result["requires_manual_review"] = True
        logger.info(
            f"Flagged for manual review: edge case detected - {edge_case.get('type')}"
        )

    # Rule 4: Add processing timestamp
    result["processing_timestamp"] = datetime.utcnow().isoformat() + "Z"

    return result


def classify_email(
    email_data: Dict[str, Any],
    api_key: Optional[str] = None,
    validate_only: bool = False
) -> Dict[str, Any]:
    """
    Classify an email using Claude API.

    Main entry point for email classification. Pure logic separated from I/O.

    Args:
        email_data: Dictionary with email fields (subject, sender_email,
                   sender_name, email_date, body_content)
        api_key: Optional API key (uses env var if not provided)
        validate_only: If True, skip API call and return mock result (for testing)

    Returns:
        Dictionary with classification result and metadata

    Raises:
        ValueError: If required email fields are missing
        RuntimeError: If API call or parsing fails
    """
    # Validate required fields
    required_fields = ["subject", "body_content"]
    missing_fields = [f for f in required_fields if f not in email_data]
    if missing_fields:
        raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

    # Log classification attempt
    logger.info(
        f"Starting classification for email: '{email_data.get('subject', 'No subject')}'"
    )

    # Format prompt
    prompt = format_email_for_prompt(email_data)

    # Call API (or skip for validation-only mode)
    if validate_only:
        # Return mock result for testing without API
        logger.info("Validation-only mode: skipping API call")
        classification = {
            "category": "Other",
            "confidence": 0.5,
            "requires_manual_review": True,
            "reasoning": "Validation-only mode",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {},
            "_gpt_usage": {"input_tokens": 0, "output_tokens": 0},
        }
    else:
        # Real API call (with retry + backoff built in)
        api_response = call_claude_api(prompt, api_key=api_key)
        classification = parse_classification_response(api_response["response"])
        # Attach token usage so callers can track cost (key starts with _ to
        # signal it's internal metadata; callers pop it before storing to DB)
        classification["_gpt_usage"] = api_response.get(
            "usage", {"input_tokens": 0, "output_tokens": 0}
        )

    # Apply business rules (pass email_data for sender-domain enforcement)
    result = apply_business_rules(classification, email_data=email_data)

    # Add metadata
    result["email_metadata"] = {
        "subject": email_data.get("subject"),
        "sender_email": email_data.get("sender_email"),
        "email_date": email_data.get("email_date")
    }

    logger.info(
        f"Classification complete: {result['category']} "
        f"(confidence: {result['confidence']}, "
        f"manual_review: {result['requires_manual_review']})"
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

    with open(file_path, 'r', encoding='utf-8') as f:
        email_data = json.load(f)

    logger.info("Email loaded successfully")
    return email_data


def save_classification_result(result: Dict[str, Any], output_path: Path) -> None:
    """
    Save classification result to JSON file.

    Args:
        result: Classification result dictionary
        output_path: Path to save result
    """
    logger.info(f"Saving classification result to {output_path}")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    logger.info("Classification result saved successfully")


def main() -> None:
    """
    CLI entry point for email classification.

    Usage:
        python classify_email.py <input_file> <output_file> [--validate-only]
    """
    import sys

    if len(sys.argv) < 3:
        print("Usage: python classify_email.py <input_file> <output_file> [--validate-only]")
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

    # Check environment
    env = os.getenv("ENVIRONMENT", "development")
    if env == "production" and validate_only:
        print("Warning: validate-only mode should not be used in production")

    try:
        # Load, classify, save
        email_data = load_email_from_file(input_file)
        result = classify_email(email_data, validate_only=validate_only)
        save_classification_result(result, output_file)

        # Report results
        print(f"\nClassification complete:")
        print(f"  Category: {result['category']}")
        print(f"  Confidence: {result['confidence']:.2f}")
        print(f"  Manual review required: {result['requires_manual_review']}")

        if result.get("edge_case", {}).get("is_edge_case"):
            print(f"  Edge case: {result['edge_case']['type']}")

        # Exit with code indicating if manual review is needed
        sys.exit(1 if result['requires_manual_review'] else 0)

    except Exception as e:
        logger.error(f"Classification failed: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
