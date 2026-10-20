"""
SQLAlchemy database models for the email management dashboard.

Defines all tables: emails, classifications, approvals, process_runs,
whitelist_companies, email_actions, user_sessions, system_config
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Float, DateTime,
    ForeignKey, JSON, Index
)
from sqlalchemy.orm import relationship
from database import Base


class Email(Base):
    """
    Stores email metadata and content.

    This table holds all emails fetched from the inbox, including
    their current classification and folder location.
    """
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    # IMAP message-sequence number. NOT stable — IMAP re-assigns it every session,
    # so it must never carry a unique constraint or be used as a dedup key.
    email_id = Column(String(255), nullable=False, index=True)
    # RFC 5322 Message-ID header — stable and globally unique. This is the dedup key.
    message_id = Column(String(500), nullable=True, unique=True, index=True)
    subject = Column(String(500), nullable=False)
    from_address = Column(String(255), nullable=False)
    received_date = Column(DateTime, nullable=False, index=True)
    body_preview = Column(String(500))  # First 500 chars for quick display
    full_body = Column(Text)
    current_folder = Column(String(100), default="INBOX", index=True)
    is_read = Column(Boolean, default=False, index=True)
    fetch_timestamp = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    classifications = relationship("Classification", back_populates="email", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="email", cascade="all, delete-orphan")
    actions = relationship("EmailAction", back_populates="email", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index('idx_folder_read', 'current_folder', 'is_read'),
    )


class Classification(Base):
    """
    Stores AI classification results for emails.

    Each email can have multiple classifications (reclassifications),
    but only the most recent is typically used.
    """
    __tablename__ = "classifications"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False, index=True)
    category = Column(String(100), nullable=False, index=True)  # 14 email categories
    confidence = Column(Float, nullable=False, index=True)  # 0.0 to 1.0
    company_name = Column(String(255))
    position = Column(String(255))
    classification_timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    classifier_version = Column(String(50), default="gpt-4o-2024-08-06")
    raw_response = Column(JSON)  # Store full AI response for debugging

    # Relationships
    email = relationship("Email", back_populates="classifications")
    approvals = relationship("Approval", back_populates="classification", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index('idx_category_confidence', 'category', 'confidence'),
    )


class Approval(Base):
    """
    Tracks human review and approval of email classifications.

    When an email has low confidence (<0.70) or needs manual review,
    an approval record is created. The human can approve, reject, or override.
    """
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False)
    classification_id = Column(Integer, ForeignKey("classifications.id"), nullable=False)
    status = Column(String(50), default="pending", index=True)  # pending, approved, rejected, overridden
    human_category = Column(String(100))  # If overridden
    human_action = Column(String(50))  # keep_inbox, move_to_folder, delete
    target_folder = Column(String(100))  # If moved
    reviewed_by = Column(String(100))  # username
    reviewed_at = Column(DateTime, index=True)
    notes = Column(Text)

    # Relationships
    email = relationship("Email", back_populates="approvals")
    classification = relationship("Classification", back_populates="approvals")

    # Indexes
    __table_args__ = (
        Index('idx_status', 'status'),
    )


class ProcessRun(Base):
    """
    Stores statistics and metadata for each automated processing run.

    Each time process_inbox_auto.py runs, a record is created here
    with summary statistics.
    """
    __tablename__ = "process_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    total_emails = Column(Integer, default=0)
    interview_requests = Column(Integer, default=0)
    organized = Column(Integer, default=0)
    spam_deleted = Column(Integer, default=0)
    categories_breakdown = Column(JSON)  # {"Job Alert": 5, "Rejection": 2, ...}
    duration_seconds = Column(Float)
    gpt_cost_usd = Column(Float, nullable=True)  # Actual GPT API cost for this run
    status = Column(String(50), default="success", index=True)  # success, partial_failure, failure
    error_log = Column(Text)

    # Indexes
    __table_args__ = (
        Index('idx_run_status', 'run_timestamp', 'status'),
    )


class WhitelistCompany(Base):
    """
    Stores companies that have sent genuine interview requests.

    These companies are protected - their emails are never moved or deleted
    regardless of AI classification.
    """
    __tablename__ = "whitelist_companies"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(255), unique=True, nullable=False, index=True)  # Normalized lowercase
    added_date = Column(DateTime, default=datetime.utcnow)
    added_by = Column(String(100), default="system")  # system or username
    notes = Column(Text)


class EmailAction(Base):
    """
    Audit trail of all actions performed on emails.

    Records every move, delete, reclassification, etc. for compliance
    and debugging purposes.
    """
    __tablename__ = "email_actions"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False, index=True)
    action_type = Column(String(50), nullable=False, index=True)  # moved, deleted, marked_read, reclassified
    from_folder = Column(String(100))
    to_folder = Column(String(100))
    performed_by = Column(String(100), nullable=False)  # system or username
    performed_at = Column(DateTime, default=datetime.utcnow, index=True)
    reason = Column(Text)

    # Relationships
    email = relationship("Email", back_populates="actions")

    # Indexes
    __table_args__ = (
        Index('idx_action_performed', 'action_type', 'performed_at'),
    )


class UserSession(Base):
    """
    Stores active user sessions for authentication.

    Session tokens are UUIDs stored in HTTP-only cookies.
    Sessions expire after 24 hours of inactivity.
    """
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_token = Column(String(255), unique=True, nullable=False, index=True)  # UUID
    username = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False, default="stakeholder")  # admin or stakeholder
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    last_activity = Column(DateTime, default=datetime.utcnow)


class Student(Base):
    """
    Stores student information synced from Google Drive.

    Each student has an assigned Gmail (used for job submissions,
    forwarded to c_interviews@colaberry.com) and a personal email
    (where notifications are sent).
    """
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, nullable=False, index=True)  # Drive folder name / Gmail username
    full_name = Column(String(255))
    personal_email = Column(String(255))  # WHERE WE SEND NOTIFICATIONS
    assigned_gmail = Column(String(255))  # The c_interviews-linked Gmail
    phone_number = Column(String(50))
    drive_folder_id = Column(String(255))
    last_synced_at = Column(DateTime)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    interview_events = relationship("InterviewEvent", back_populates="student", cascade="all, delete-orphan")


class InterviewEvent(Base):
    """
    Stores sub-classified interview events extracted from emails.

    Each interview email produces one InterviewEvent record with
    all extracted details (company, date, format, etc.).
    """
    __tablename__ = "interview_events"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), index=True)
    sub_type = Column(String(100), nullable=False, index=True)  # Phone Screen, Client Screen, etc.
    company_name = Column(String(255))
    position_title = Column(String(255))
    contact_name = Column(String(255))
    contact_email = Column(String(255))
    contact_phone = Column(String(100))
    interview_date = Column(String(20))  # YYYY-MM-DD
    interview_time = Column(String(10))  # HH:MM
    interview_timezone = Column(String(20))
    interview_format = Column(String(50))  # phone / video / in-person / panel
    meeting_link = Column(Text)
    num_interviewers = Column(Integer)
    is_job_machine = Column(Boolean, default=False)
    is_next_round = Column(Boolean, default=False)
    confidence = Column(Float, nullable=False, index=True)
    raw_extraction = Column(JSON)  # Full AI extraction for audit
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    email = relationship("Email")
    student = relationship("Student", back_populates="interview_events")
    notification_drafts = relationship("NotificationDraft", back_populates="interview_event", cascade="all, delete-orphan")
    checklist_completions = relationship("ChecklistCompletion", back_populates="interview_event", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index('idx_interview_sub_type_date', 'sub_type', 'created_at'),
        Index('idx_interview_company', 'company_name'),
    )


class NotificationDraft(Base):
    """
    Stores notification drafts (email + WhatsApp) for interview events.

    Tracks the full lifecycle: draft → approved → sent (or rejected).
    """
    __tablename__ = "notification_drafts"

    id = Column(Integer, primary_key=True, index=True)
    interview_event_id = Column(Integer, ForeignKey("interview_events.id"), nullable=False, index=True)

    # Email notification
    template_id = Column(String(100))
    email_subject = Column(String(500))
    email_body = Column(Text)
    recipient_email = Column(String(255))  # Student's PERSONAL email
    email_status = Column(String(50), default="draft", index=True)  # draft, approved, sent, failed, rejected
    auto_send_eligible = Column(Boolean, default=False)

    # Review tracking
    missing_fields = Column(JSON)
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime)
    sent_at = Column(DateTime)
    send_error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    interview_event = relationship("InterviewEvent", back_populates="notification_drafts")

    # Indexes
    __table_args__ = (
        Index('idx_draft_status', 'email_status', 'created_at'),
    )


class NotificationSequence(Base):
    """
    One escalation run for an approved NotificationDraft (see
    directives/student-notification-escalation.md).

    Starts when the approver approves; keeps contacting the student until they acknowledge
    or the approver closes it. New table on purpose: create_all() cannot add columns to
    the existing notification_drafts table in production.
    """
    __tablename__ = "notification_sequences"

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(Integer, ForeignKey("notification_drafts.id"), nullable=False, unique=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True, index=True)

    # active | acknowledged | closed (by the approver) | exhausted (4 days, no ack) | opted_out
    status = Column(String(30), default="active", nullable=False, index=True)
    timezone = Column(String(64), nullable=False)          # student's own zone (Ali: quiet hours use it)
    timezone_source = Column(String(30))                   # stored | area_code | fallback
    started_at = Column(DateTime, nullable=False)          # naive UTC, = the approver's approval time
    started_by = Column(String(100))

    ack_token = Column(String(64), unique=True, index=True)  # email "I got this" link
    ack_at = Column(DateTime)
    ack_channel = Column(String(20))                       # call | sms | email | approver | ai
    ack_kind = Column(String(20))                          # explicit | approver | ai_inferred
    closed_by = Column(String(100))
    closed_at = Column(DateTime)

    rob_day1_alert_at = Column(DateTime)                   # "no response after day 1" sent
    rob_ended_alert_at = Column(DateTime)                  # "sequence ended" sent
    created_at = Column(DateTime, default=datetime.utcnow)

    attempts = relationship("NotificationAttempt", back_populates="sequence", cascade="all, delete-orphan")


class NotificationAttempt(Base):
    """One planned or made contact (call, text or email) within a sequence."""
    __tablename__ = "notification_attempts"

    id = Column(Integer, primary_key=True, index=True)
    sequence_id = Column(Integer, ForeignKey("notification_sequences.id"), nullable=False, index=True)
    channel = Column(String(10), nullable=False)           # call | sms | email
    step = Column(String(20), nullable=False)              # start | d1_2h | d1_4h | day2 | day3 | day4
    planned_for = Column(DateTime, nullable=False)         # naive UTC, before quiet-hours adjustment
    scheduled_for = Column(DateTime, nullable=False, index=True)  # naive UTC, after quiet-hours adjustment
    # pending | sent | failed | skipped | cancelled
    status = Column(String(20), default="pending", nullable=False, index=True)
    sent_at = Column(DateTime)
    detail = Column(Text)                                  # why skipped/failed, or provider note
    provider_id = Column(String(100))                      # Twilio/GHL/Synthflow id
    segments = Column(Integer)                             # SMS segments, for the shared daily budget
    created_at = Column(DateTime, default=datetime.utcnow)

    sequence = relationship("NotificationSequence", back_populates="attempts")

    __table_args__ = (
        Index("idx_attempt_sequence_step_channel", "sequence_id", "step", "channel", unique=True),
        Index("idx_attempt_due", "status", "scheduled_for"),
    )


class ReplyAnalysis(Base):
    """
    The AI's reading of one student reply. In shadow mode (first two weeks) these
    are recorded but never stop a sequence; human_verdict is how we measure the hit rate.
    """
    __tablename__ = "reply_analyses"

    id = Column(Integer, primary_key=True, index=True)
    sequence_id = Column(Integer, ForeignKey("notification_sequences.id"), nullable=False, index=True)
    channel = Column(String(10), nullable=False)          # sms | email | call
    message_text = Column(Text, nullable=False)           # the STUDENT's words only, never ours
    outcome = Column(String(20), nullable=False)          # understood | needs_help | confused | unsure
    confidence = Column(Float)
    reason = Column(Text)
    shadow = Column(Boolean, default=True, nullable=False)
    acted = Column(Boolean, default=False, nullable=False)   # did this analysis stop the sequence?
    human_verdict = Column(String(20))                    # right | wrong, set by the approver/Ali later
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class NotificationInbound(Base):
    """
    One message or call read from the student's GHL Conversations and processed for a sequence.
    The unique GHL message id is what makes polling idempotent: a message is handled exactly once.
    """
    __tablename__ = "notification_inbound"

    id = Column(Integer, primary_key=True, index=True)
    sequence_id = Column(Integer, ForeignKey("notification_sequences.id"), nullable=False, index=True)
    ghl_message_id = Column(String(100), nullable=False, unique=True, index=True)
    channel = Column(String(10), nullable=False)           # sms | email | call
    direction = Column(String(10))
    text = Column(Text)                                    # the student's words (calls: only their side, if isolable)
    received_at = Column(DateTime)
    # yes_rule | stop_rule | ai | call_unreadable | call_no_transcript | call_recorded | echo
    handled_as = Column(String(30), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class NotificationOptOut(Base):
    """
    The app's own memory that a student asked us to stop on a channel (a STOP text, or "don't call me again"
    on a call). Checked before every send, in addition to GHL Do-Not-Disturb and opt-out tags, so the request
    holds even if the GHL side is never updated. Keyed by the last 10 digits of the phone number.
    """
    __tablename__ = "notification_opt_outs"

    id = Column(Integer, primary_key=True, index=True)
    phone_tail = Column(String(10), nullable=False, index=True)
    channel = Column(String(10), nullable=False)           # sms | call | email
    source = Column(String(30), nullable=False)            # stop_text | stop_call | stop_email
    sequence_id = Column(Integer)                          # the notice that was open when they asked
    created_at = Column(DateTime, default=datetime.utcnow)


class InterviewFollowUp(Base):
    """
    An email about an interview the student was ALREADY told about (reminder, reply, duplicate confirmation) at the same moment.
    It gets no student notice: this row links it to the earlier event. One row per follow-up event.
    """
    __tablename__ = "interview_follow_ups"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("interview_events.id"), nullable=False, unique=True, index=True)
    original_event_id = Column(Integer, ForeignKey("interview_events.id"), nullable=False, index=True)
    reason = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)


class CallbackRequest(Base):
    """
    A student called the AI receptionist back about an interview. The callback owner (a ROLE) must call them back within one business hour.
    One row per receptionist call (ghl_call_id is unique, so a call is handled once). status: open | done. The AI never calls back.
    """
    __tablename__ = "callback_requests"

    id = Column(Integer, primary_key=True, index=True)
    ghl_call_id = Column(String(100), nullable=False, unique=True, index=True)
    contact_id = Column(String(100))
    student_id = Column(Integer, ForeignKey("students.id"), index=True)         # null = caller not matched to a student
    caller_number = Column(String(40))
    received_at = Column(DateTime, nullable=False, index=True)                   # naive UTC
    duration_seconds = Column(Integer)
    said = Column(Text)                                                         # the caller's own words (excerpt)
    status = Column(String(10), nullable=False, default="open", index=True)
    done_by = Column(String(100))
    done_at = Column(DateTime)
    alerted_at = Column(DateTime)                                               # callback owner emailed
    sla_alerted_at = Column(DateTime)                                           # escalation role emailed (not called back in time)
    created_at = Column(DateTime, default=datetime.utcnow)


class RoleAssignment(Base):
    """
    Who holds a role (approver, callback_owner, escalation_target). Roles are assigned on the Settings page, never written into the code,
    so moving the work to recruiters is a settings change. `scope` is reserved for per-recruiter routing later (unused).
    """
    __tablename__ = "role_assignments"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(40), nullable=False, index=True)
    email = Column(String(255))
    display_name = Column(String(255))
    scope = Column(String(100))
    active = Column(Boolean, default=True, nullable=False)
    updated_by = Column(String(100))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlertLog(Base):
    """One row per alert already sent, so an alert (for example "this draft is stale") is sent once. kind + key is unique."""
    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(40), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    detail = Column(Text)

    __table_args__ = (Index("uq_alert_kind_key", "kind", "key", unique=True),)


class StudentVerification(Base):
    """
    Whether the approver has confirmed who a student is. A student the pipeline had to create from an email's delivery Gmail (not in the
    roster or database) starts "unverified": the Gmail is only an address and the name is a guess (the greeting's name, or the Gmail).
    Students with no row here (the roster, earlier students) count as verified. Approving a notification for an unverified student is refused.
    """
    __tablename__ = "student_verifications"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="unverified")      # unverified | verified | rejected (not a student we can find)
    basis = Column(String(30), nullable=False)                             # greeting_name | gmail_guess
    guessed_name = Column(String(255))
    evidence = Column(Text)                                                # for example: delivered to x@gmail.com; greeting "Hi OMOLOLA"
    verified_by = Column(String(100))
    verified_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChecklistCompletion(Base):
    """
    Tracks completion state of process checklist steps per interview event.

    Each interview event has a set of process steps determined by its sub_type.
    Step definitions are hardcoded in checklist_steps.py; only completion
    state is persisted here.
    """
    __tablename__ = "checklist_completions"

    id = Column(Integer, primary_key=True, index=True)
    interview_event_id = Column(Integer, ForeignKey("interview_events.id"), nullable=False, index=True)
    step_key = Column(String(100), nullable=False)  # e.g. "phone_screen.1.1"
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_by = Column(String(100))
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    interview_event = relationship("InterviewEvent", back_populates="checklist_completions")

    # Indexes
    __table_args__ = (
        Index('idx_checklist_event_step', 'interview_event_id', 'step_key', unique=True),
    )


class SystemConfig(Base):
    """
    Stores system-wide configuration key-value pairs.

    Used for runtime configuration that can be changed without
    redeploying the application.
    """
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(100))


class ApprovalLink(Base):
    """
    A secure link in an alert email that opens ONE card for review and approval without logging in. Only the SHA-256 of the token is stored (the token itself
    is only in the email). Valid for a limited time; used up by the first approve or reject; refused once the card has been decided another way.
    """
    __tablename__ = "approval_links"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    draft_id = Column(Integer, ForeignKey("notification_drafts.id"), nullable=False, index=True)
    role = Column(String(30), nullable=False)               # approver | escalation_target (who the email went to)
    recipient_email = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)
    used_action = Column(String(20))                        # approved | rejected


class ApprovalCode(Base):
    """
    The one-time 6-digit code that proves the person opening an approval link can read the approver's mailbox. Only a salted hash is stored. A code lasts 10 minutes,
    allows 5 wrong tries, and is used up by the approval or rejection it unlocks, so every decision needs a fresh code.
    """
    __tablename__ = "approval_codes"

    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("approval_links.id"), nullable=False, index=True)
    salt = Column(String(32), nullable=False)
    code_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    consumed_at = Column(DateTime)
