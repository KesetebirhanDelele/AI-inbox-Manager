"""
Automated inbox processing - Production script for scheduled execution.

This script is designed to run on a schedule (hourly/daily) and will:
1. Process ONLY unread (UNSEEN) emails to prevent re-processing
2. Keep genuine interview requests in inbox (unread for visibility)
3. Move job alerts and other emails to category folders
4. Delete spam emails
5. Sub-classify interview emails and create InterviewEvent records

IMPORTANT: This script NEVER processes read emails, preventing accidental
deletion or movement of important emails like interview requests.

Usage:
    python process_inbox_auto.py

Configuration:
    Set in .env file:
    - EMAIL_SERVER
    - EMAIL_PORT
    - EMAIL_ADDRESS
    - EMAIL_PASSWORD
    - OPENAI_API_KEY
"""

import json
import logging
import os
import re
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv

# Load environment variables FIRST (before any module imports that may read env)
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

# Set up file + console logging BEFORE importing other modules.
# fetch_emails.py calls logging.basicConfig() at import time; using force=True
# ensures our file handler is not silently discarded.
log_dir = project_root / "logs"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,   # override any handlers set by imported modules
    handlers=[
        # encoding="utf-8" is required: per-email audit lines contain "→" and other
        # non-Latin-1 characters. Without it, the default Windows cp1252 encoder
        # raises UnicodeEncodeError on every such line and the logging module
        # silently drops it — the entire "Applying actions" section vanished from
        # the log file.
        logging.FileHandler(
            log_dir / f"inbox_auto_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)

# Import our execution modules
from fetch_emails import fetch_emails, delete_emails, move_emails, label_emails, EmailConnectionError, EmailFetchError

# Gmail label added to the original email when the student it is for had to be guessed (the approver verifies them).
VERIFY_STUDENT_LABEL = "Verify Student"
from classify_email import classify_email
from db_url import normalize_db_url

# Add project root so execution.* package imports work (e.g. draft_notification → execution.email_templates)
sys.path.insert(0, str(project_root))
# Add services path for dashboard database access
sys.path.insert(0, str(project_root / "services" / "dashboard" / "api"))

# Database and interview processing imports (lazy loaded)
_db_session = None
_db_engine = None
# First DB failure seen this run (init or ProcessRun write). DB writes are
# best-effort so they never block email processing, but a run that silently
# writes nothing to the dashboard must still be surfaced (see main()).
_db_error: Optional[str] = None


def _record_db_error(msg: str) -> None:
    global _db_error
    if _db_error is None:
        _db_error = msg


def get_db_session():
    """Get or create database session for interview logging."""
    global _db_session, _db_engine
    if _db_session is None:
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker

            db_url = normalize_db_url(os.getenv("DATABASE_URL"))
            if not db_url:
                db_path = project_root / "services" / "dashboard" / "api" / "email_dashboard.db"
                db_url = f"sqlite:///{db_path}"
            engine_kwargs = {"echo": False}
            if db_url.startswith("postgres"):
                # Neon's free tier drops idle connections mid-run (a full run can
                # take 10+ min with long IMAP / Google Sheets phases between DB
                # writes). pool_pre_ping revalidates a connection before use and
                # pool_recycle forces a refresh well inside Neon's idle timeout.
                engine_kwargs.update(pool_pre_ping=True, pool_recycle=280)
            _db_engine = create_engine(db_url, **engine_kwargs)
            _ensure_schema(_db_engine)
            SessionLocal = sessionmaker(bind=_db_engine)
            _db_session = SessionLocal()
        except Exception as e:
            logging.getLogger(__name__).warning(f"Could not initialize database: {e}")
            _record_db_error(f"Could not initialize database: {e}")
            return None
    return _db_session


def close_db_session():
    """Close database session.

    A dropped connection (Neon idle timeout) makes SQLAlchemy's implicit
    rollback-on-close raise. That is a cleanup-only failure — every prior
    commit is already durable — so it must never propagate and fail the run.
    """
    global _db_session, _db_engine
    if _db_session:
        try:
            _db_session.close()
        except Exception as e:
            logging.getLogger(__name__).warning(f"DB session close failed (ignored): {e}")
        _db_session = None
    if _db_engine:
        try:
            _db_engine.dispose()
        except Exception:
            pass
        _db_engine = None


def _ensure_schema(engine) -> None:
    """Bring an older database up to the current emails-table shape.

    Two fixes, both idempotent and cheap (one inspect per run):
      1. add the emails.message_id column (the real dedup key), and
      2. drop the bogus UNIQUE index on emails.email_id — that column holds the
         IMAP sequence number, which repeats every run, so the constraint made
         every new insert fail once the old rows filled the low sequence range.

    Keeps interns from having to remember a manual migration step.
    """
    log = logging.getLogger(__name__)
    try:
        from sqlalchemy import inspect as _sa_inspect, text as _sa_text

        inspector = _sa_inspect(engine)
        if "emails" not in inspector.get_table_names():
            return
        dialect = engine.dialect.name
        cols = {c["name"] for c in inspector.get_columns("emails")}
        indexes = inspector.get_indexes("emails")

        if "message_id" not in cols:
            with engine.begin() as conn:
                conn.execute(_sa_text("ALTER TABLE emails ADD COLUMN message_id VARCHAR(500)"))
            log.info("Schema: added emails.message_id column")
            indexes = _sa_inspect(engine).get_indexes("emails")

        # Ensure the message_id index exists and is UNIQUE (multiple NULLs are
        # allowed on both PostgreSQL and SQLite). Only touch it if it is missing
        # or non-unique.
        msgid_ix = next((ix for ix in indexes if ix.get("column_names") == ["message_id"]), None)
        if msgid_ix is None or not msgid_ix.get("unique"):
            with engine.begin() as conn:
                try:
                    conn.execute(_sa_text("DROP INDEX IF EXISTS ix_emails_message_id"))
                except Exception:
                    pass
                try:
                    conn.execute(_sa_text("CREATE UNIQUE INDEX ix_emails_message_id ON emails (message_id)"))
                    log.info("Schema: made emails.message_id index UNIQUE")
                except Exception:
                    pass

        # Drop the UNIQUE constraint/index on email_id if present, replace with a
        # plain index.
        unique_on_email_id = any(
            ix.get("unique") and ix.get("column_names") == ["email_id"]
            for ix in indexes
        )
        unique_constraints = {
            uc["name"]
            for uc in inspector.get_unique_constraints("emails")
            if uc.get("column_names") == ["email_id"]
        }
        if unique_on_email_id or unique_constraints:
            with engine.begin() as conn:
                for uc_name in unique_constraints:
                    try:
                        conn.execute(_sa_text(f'ALTER TABLE emails DROP CONSTRAINT "{uc_name}"'))
                    except Exception:
                        pass
                if dialect == "postgresql":
                    try:
                        conn.execute(_sa_text("DROP INDEX IF EXISTS ix_emails_email_id"))
                        conn.execute(_sa_text("CREATE INDEX ix_emails_email_id ON emails (email_id)"))
                    except Exception:
                        pass
                # SQLite: a UNIQUE declared inline on the column can't be dropped
                # without a table rebuild; not worth it for the local dev DB.
            log.info("Schema: dropped UNIQUE constraint on emails.email_id")
    except Exception as e:
        log.warning(f"Schema check failed (continuing): {e}")


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalise to naive UTC — the emails table stores tz-naive datetimes and
    dashboard 'today' / 'last N days' queries compare against a naive now()."""
    if dt.tzinfo is not None:
        from datetime import timezone

        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_received_date(email_data: Dict[str, Any]) -> datetime:
    """Best-effort parse of the email's received date from any known key."""
    raw_date = email_data.get("email_date") or email_data.get("date")
    if isinstance(raw_date, datetime):
        return _to_naive_utc(raw_date)
    if isinstance(raw_date, str) and raw_date.strip():
        try:
            return _to_naive_utc(datetime.fromisoformat(raw_date.replace("Z", "+00:00")))
        except Exception:
            try:
                from email.utils import parsedate_to_datetime

                return _to_naive_utc(parsedate_to_datetime(raw_date))
            except Exception:
                pass
    return datetime.utcnow()


def import_email_to_db(email_data: Dict[str, Any], classification: Dict[str, Any], folder: str = "INBOX") -> Optional[int]:
    """
    Import (upsert) an email + its classification into the dashboard database.

    Dedup key is the RFC 5322 Message-ID header (`email_data["message_id"]`),
    which is stable and globally unique. The IMAP sequence number
    (`email_data["email_id"]`) is NOT usable for dedup — IMAP re-assigns it every
    session, so historically every new email collided with an old row and the
    import silently no-op'd.

    Args:
        email_data: Email data from fetch_emails() (keys: subject, sender_email,
            sender_name, email_date, body_content, email_id, message_id)
        classification: Classification result
        folder: Destination folder the email was routed to

    Returns:
        Database ID of the email row, or None if import failed
    """
    db = get_db_session()
    if not db:
        logging.getLogger(__name__).warning("DB import skipped: no database session")
        return None

    logger_ = logging.getLogger(__name__)

    try:
        from models import Email, Classification

        seq_uid = str(email_data.get("email_id", "") or "")
        message_id = (email_data.get("message_id") or "").strip()

        # Normalise across the two key conventions used in this codebase.
        subject = (email_data.get("subject") or "No Subject")[:500]
        from_address = (
            email_data.get("sender_email")
            or email_data.get("from")
            or "Unknown"
        )[:255]
        body = (email_data.get("body_content") or email_data.get("body") or "") or ""
        received_date = _parse_received_date(email_data)

        # ── Locate an existing row ──────────────────────────────────────────
        existing = None
        if message_id:
            existing = db.query(Email).filter(Email.message_id == message_id).first()
        if existing is None:
            # No Message-ID (rare) — fall back to a content match so a
            # re-processed email still de-dupes instead of duplicating.
            existing = (
                db.query(Email)
                .filter(
                    Email.subject == subject,
                    Email.from_address == from_address,
                    Email.received_date == received_date,
                )
                .first()
            )

        extracted = classification.get("extracted_data") or {}
        category = (classification.get("category", "Unknown") or "")[:100]
        confidence = float(classification.get("confidence", 0.0))
        company_name = (extracted.get("company_name") or "")[:255] or None
        position = (extracted.get("position_title") or "")[:255] or None

        if existing is not None:
            # Update folder + refresh the classification in place. A row that was first created as a stub (no body,
            # sender "Unknown": 239 of them in production, 17 of 33 Interview Requests) gets its body filled in now,
            # and a real subject/sender is never overwritten by a placeholder.
            existing.current_folder = folder
            if subject != "No Subject" or not existing.subject:
                existing.subject = subject
            if from_address != "Unknown" or not existing.from_address:
                existing.from_address = from_address
            if body and not (existing.full_body or "").strip():
                existing.full_body = body
                existing.body_preview = body[:500]
            if message_id and not existing.message_id:
                existing.message_id = message_id
            if seq_uid:
                existing.email_id = seq_uid

            latest = (
                db.query(Classification)
                .filter(Classification.email_id == existing.id)
                .order_by(Classification.classification_timestamp.desc())
                .first()
            )
            if latest is None:
                latest = Classification(
                    email_id=existing.id,
                    category=category,
                    confidence=confidence,
                    company_name=company_name,
                    position=position,
                    classification_timestamp=datetime.utcnow(),
                    classifier_version="gpt-4o",
                    raw_response=classification,
                )
                db.add(latest)
            else:
                latest.category = category
                latest.confidence = confidence
                latest.company_name = company_name
                latest.position = position
                latest.classification_timestamp = datetime.utcnow()
                latest.raw_response = classification

            db.flush()
            _queue_for_review(db, existing.id, latest.id, category, confidence)
            db.commit()
            logger_.info(f"DB import: updated email id={existing.id} [{category}] → {folder}")
            return existing.id

        # ── Insert a new row ───────────────────────────────────────────────
        new_email = Email(
            email_id=seq_uid or (message_id[:255] if message_id else f"noid-{datetime.utcnow().timestamp()}"),
            message_id=message_id or None,
            subject=subject,
            from_address=from_address,
            received_date=received_date,
            body_preview=body[:500],
            full_body=body,
            current_folder=folder,
            is_read=False,
            fetch_timestamp=datetime.utcnow(),
        )
        db.add(new_email)
        db.flush()  # assign PK without committing
        email_db_id = new_email.id

        new_cls = Classification(
            email_id=email_db_id,
            category=category,
            confidence=confidence,
            company_name=company_name,
            position=position,
            classification_timestamp=datetime.utcnow(),
            classifier_version="gpt-4o",
            raw_response=classification,
        )
        db.add(new_cls)
        db.flush()
        _queue_for_review(db, email_db_id, new_cls.id, category, confidence)
        db.commit()
        logger_.info(f"DB import: inserted email id={email_db_id} [{category}] → {folder}")
        return email_db_id

    except Exception as e:
        logger_.error(f"Failed to import email to database: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None


def needs_human_review(category: str, confidence: float) -> bool:
    """
    True when a classification should land in the dashboard approvals queue.

    Anything under ROUTING_CONFIDENCE_THRESHOLD qualifies, except "Other" at
    exactly 0.0. For "Other" the model reports 0.0 as its normal answer for plain
    junk (740 of 810 live rows in the week to 2026-10-01), so counting those
    would bury the queue in about 800 items a week. "Other" with a real
    in-between score (0.0 < c < 0.70) is genuine uncertainty and is queued.
    """
    if confidence >= ROUTING_CONFIDENCE_THRESHOLD:
        return False
    if category == "Other" and confidence <= 0.0:
        return False
    return True


def _queue_for_review(db, email_db_id: int, classification_id: int,
                      category: str, confidence: float) -> bool:
    """Add a pending Approval row once per email. Caller commits."""
    if not needs_human_review(category, confidence):
        return False
    from models import Approval
    already = db.query(Approval).filter(Approval.email_id == email_db_id).first()
    if already is not None:
        return False
    db.add(Approval(
        email_id=email_db_id,
        classification_id=classification_id,
        status="pending",
        notes=f"Auto-queued: {category} at confidence {confidence:.2f}",
    ))
    logging.getLogger(__name__).info(
        f"Queued for human review: email id={email_db_id} [{category} {confidence:.2f}]"
    )
    return True


# Used only when the interview sub-classifier cannot give an answer. These are
# the primary category names mapped to the older snake_case labels.
_CATEGORY_TO_SUB_TYPE = {
    "Interview Request":         "interview_request",
    "Interview Schedule":        "interview_schedule",
    "Interview Reschedule":      "reschedule",
    "Interview Confirmation":    "confirmed",
    "Interview Cancelled":       "cancelled",
    "Phone Screen":              "phone_screen",
    "Final Interview Scheduled": "final_round",
    "Assessment":                "assessment",
    "Instant Interview":         "interview_request",
    "Technical Interview":       "technical_interview",
    "Client Screen":             "client_screen",
}

# Primary categories that may or may not be an interview: the interview sub-classifier decides (see _job_machine_not_interview).
# Job Machine mail is job postings and application updates as well as interview notices.
_NEEDS_SUBCLASSIFIER = {"Job Machine"}
_JOB_MACHINE_INTERVIEW_SUBTYPES = {"interview", "reschedule", "cancellation"}
_FORMAT_MAP = {
    "phone":     "phone",
    "video":     "video",
    "in-person": "in_person",
    "in_person": "in_person",
    "technical": "technical",
    "panel":     "panel",
}


def _fallback_sub_classification(classification: Dict[str, Any]) -> Dict[str, Any]:
    """Build an InterviewEvent-ready dict from the primary classification alone."""
    extracted = classification.get("extracted_data") or {}
    raw_fmt = (extracted.get("interview_type") or "").lower().strip()
    location = extracted.get("interview_location") or ""
    meeting_link = location if any(
        k in location.lower() for k in ["http", "zoom", "meet", "teams"]
    ) else None
    return {
        "interview_sub_type":      _CATEGORY_TO_SUB_TYPE.get(classification.get("category", ""), "other"),
        "company_name":            extracted.get("company_name"),
        "position_title":          extracted.get("position_title"),
        "contact_name":            extracted.get("contact_name"),
        "contact_email":           extracted.get("contact_email"),
        "contact_phone":           None,
        "interview_date":          extracted.get("interview_date"),
        "interview_time":          extracted.get("interview_time"),
        "interview_timezone":      extracted.get("interview_timezone"),
        "interview_format":        _FORMAT_MAP.get(raw_fmt, raw_fmt or None),
        "meeting_link_or_dial_in": meeting_link,
        "num_interviewers":        None,
        "is_job_machine":          False,
        "is_next_round":           False,
        "confidence":              float(classification.get("confidence", 0.0)),
        "sub_type_source":         "category_fallback",
    }


def _build_sub_classification(email_data: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decide the interview sub-type for an InterviewEvent.

    Interview-related emails go through subclassify_interview (phone screen,
    client screen, technical, cancelled, rescheduled, job machine). If that call
    fails or returns an unknown type, the event is still created from the
    primary category so an interview is never dropped.
    """
    fallback = _fallback_sub_classification(classification)
    category = classification.get("category", "")
    log = logging.getLogger(__name__)

    try:
        from subclassify_interview import (
            subclassify_interview, is_interview_related, INTERVIEW_SUB_TYPES,
        )
        if not is_interview_related(category):
            return fallback

        result = subclassify_interview(email_data)
        sub_type = (result or {}).get("interview_sub_type")
        if sub_type not in INTERVIEW_SUB_TYPES:
            log.warning(f"Sub-classifier returned unusable type {sub_type!r}; using category fallback")
            return fallback

        merged = dict(result)
        for key, value in fallback.items():
            if merged.get(key) is None:
                merged[key] = value
        merged["sub_type_source"] = "subclassifier"
        return merged
    except Exception as e:
        log.warning(f"Sub-classification failed ({e}); using category fallback")
        return fallback


def _resolve_assigned_gmail(email_data: Dict[str, Any]) -> Optional[str]:
    """The student's assigned Gmail, only when read from forwarding headers."""
    try:
        from resolve_student import resolve_student
        resolved = resolve_student(email_data)
        if resolved.get("resolution_method") in ("email_headers", "to_field"):
            return resolved.get("student_gmail")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Header student resolution skipped: {e}")
    return None


def _is_new_email(email_data: Dict[str, Any]) -> bool:
    """True when this IMAP uid is not in the database yet (checked BEFORE the import)."""
    db = get_db_session()
    uid = str(email_data.get("email_id", ""))
    if not db or not uid:
        return True
    from models import Email as EmailModel
    return db.query(EmailModel).filter(EmailModel.email_id == uid).first() is None


def creates_interview_event(classification: Dict[str, Any]) -> bool:
    """
    True when the email is about an interview and should get an InterviewEvent.

    Mail from a known interview company is always kept in the inbox as a safety
    net, but a Job Alert or Job Invite from such a company is not an interview,
    so it must not create an event (20 of 50 events were this noise on 2026-10-01).
    """
    if is_genuine_interview_request(classification):
        return True
    category = classification.get("category", "")
    return category in _CATEGORY_TO_SUB_TYPE or category in _NEEDS_SUBCLASSIFIER


def _name_hint(classification: Dict[str, Any], email_data: Dict[str, Any]) -> Optional[str]:
    """A person's name the classifier or the email's greeting offers (may be wrong; the caller checks it against the Gmail)."""
    extracted = classification.get("extracted_data", {}) or {}
    hint = extracted.get("candidate_name") or extracted.get("student_name") or classification.get("candidate_name")
    if hint:
        return str(hint)
    try:
        from resolve_student import find_student_name_in_body
        body = email_data.get("body", "") or email_data.get("body_content", "") or ""
        return find_student_name_in_body(body) or find_student_name_in_body(email_data.get("subject", "") or "")
    except Exception:
        return None


_NOT_PEOPLE = {"there", "team", "sir", "madam", "candidate", "applicant", "user", "friend", "everyone", "folks", "greetings",
               "all", "hello", "dear", "recruiter", "manager", "hiring", "admin", "support"}


def plausible_person_name(text: Optional[str]) -> bool:
    """A name worth showing: letters, spaces, hyphens and apostrophes, 2-40 chars, no job-title or greeting words."""
    value = (text or "").strip()
    if not (2 <= len(value) <= 40) or not re.fullmatch(r"[A-Za-z][A-Za-z'\- ]*", value):
        return False
    from fetch_students_sheet import _looks_like_a_job_title
    return not _looks_like_a_job_title(value) and not any(w.lower() in _NOT_PEOPLE for w in value.split())


def recipient_only_student(gmail: str, name_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    A student known only by the Gmail an interview email was delivered to (not in the roster).

    The Gmail is the identity KEY (the mailbox the email reached; the username of the student record) and the greeting's name is
    the DISPLAY name even when the Gmail does not contain it ("Hi OMOLOLA" for opcrowne@): a Gmail address is just a username the
    person chose. With no usable greeting the name is guessed from the address. Either way the student is UNVERIFIED until the approver confirms.
    """
    local = gmail.split("@")[0].lower()
    words = [w for w in re.split(r"[^a-z]+", local) if len(w) >= 3]
    guessed = " ".join(w.capitalize() for w in words[:2]) or local
    hint = (name_hint or "").strip()
    use_hint = plausible_person_name(hint)
    name = (hint.title() if hint.isupper() else hint) if use_hint else guessed
    evidence = f"The email was delivered to {gmail.lower()}." + (f' The greeting or text names "{hint}".' if hint else " No name appears in the email.")
    return {"name": name, "username": local, "personal_email": gmail.lower(), "phone": "",
            "assigned_to": None, "assistant_email": None, "identified_by": "recipient_gmail",
            "name_source": "greeting_name" if use_hint else "gmail_guess", "evidence": evidence}


def _name_matches_gmail(full_name: str, gmail: str) -> bool:
    """Loose check: some word (3+ letters) of the name appears in the Gmail's local part."""
    local = (gmail or "").split("@")[0].lower()
    words = [w for w in re.split(r"[^a-z]+", (full_name or "").lower()) if len(w) >= 3]
    return any(w in local for w in words)


def _config_from_student(row) -> Dict[str, Any]:
    """A student config (the shape the pipeline expects) built from a students-table row."""
    return {"name": row.full_name or row.username, "username": row.username,
            "personal_email": row.personal_email or row.assigned_gmail or "", "phone": row.phone_number or "",
            "assigned_to": None, "assistant_email": None, "identified_by": "known student"}


def _student_named_in_gmail(db, gmail: str) -> Optional[Dict[str, Any]]:
    """The ONE known student (roster or database) whose name appears in the Gmail's local part, else None."""
    from models import Student
    from fetch_students_sheet import get_all_students
    found: Dict[str, Dict[str, Any]] = {}
    for cfg in get_all_students():
        if len((cfg["name"] or "").split()) >= 2 and _name_matches_gmail(cfg["name"], gmail):
            found[cfg["name"].lower()] = cfg
    for row in db.query(Student).all():
        if row.full_name and len(row.full_name.split()) >= 2 and _name_matches_gmail(row.full_name, gmail):
            found.setdefault(row.full_name.lower(), _config_from_student(row))
    return next(iter(found.values())) if len(found) == 1 else None


def _identify_student(db, email_data: Dict[str, Any], classification: Dict[str, Any]):
    """
    Work out which student an interview email is for.

    The mailbox an email was delivered to (a forwarding header, or a Gmail in To/CC) is the strongest identity, so when
    there is one it decides, in this order: a student whose assigned Gmail it is; a student (database or roster) whose
    email it is; the body's name hint, only if that name appears in the Gmail; the one known student whose name appears in
    the Gmail; otherwise the Gmail itself identifies a new student (name guessed from the address, the approver confirms). A body
    name that does NOT fit the Gmail is ignored: it was how "Lead Business" became a student.
    With no recipient Gmail, the name lookup is all there is.

    Returns:
        (student_config or None, assigned_gmail_to_store or None)
    """
    log = logging.getLogger(__name__)
    from models import Student
    from notify_student import _get_student_info
    from fetch_students_sheet import find_student_by_name, find_student_by_email

    header_gmail = _resolve_assigned_gmail(email_data)
    if not header_gmail:
        return _get_student_info(classification, email_data), None

    owner = db.query(Student).filter(Student.assigned_gmail == header_gmail).first()
    if owner:
        return (find_student_by_name(owner.full_name or "") or _config_from_student(owner)), header_gmail

    by_email = db.query(Student).filter(Student.personal_email == header_gmail).first()
    if by_email:
        return (find_student_by_name(by_email.full_name or "") or _config_from_student(by_email)), header_gmail
    known = find_student_by_email(header_gmail)
    if known:
        return known, header_gmail

    config = _get_student_info(classification, email_data)
    if config and _name_matches_gmail(config["name"], header_gmail):
        username = config.get("username") or config["name"].lower().replace(" ", ".")
        existing = db.query(Student).filter(Student.username == username).first()
        if existing and existing.assigned_gmail and existing.assigned_gmail != header_gmail:
            log.warning(f"Student '{config['name']}' already has a different assigned Gmail; not overwriting")
            return config, None
        return config, header_gmail
    if config:
        log.warning(f"Body names '{config['name']}' but the email was delivered to {header_gmail}; using the Gmail's identity")

    named = _student_named_in_gmail(db, header_gmail)
    if named:
        return named, header_gmail
    return recipient_only_student(header_gmail, _name_hint(classification, email_data)), header_gmail


def _is_job_machine_interview(sub_classification: Dict[str, Any]) -> bool:
    """True only when the sub-classifier itself read the mail as a Job Machine interview, reschedule or cancellation notice."""
    return (sub_classification.get("sub_type_source") == "subclassifier"
            and sub_classification.get("job_machine_sub_type") in _JOB_MACHINE_INTERVIEW_SUBTYPES)


def process_interview_email(email_data: Dict[str, Any], email_db_id: int, classification: Dict[str, Any]) -> bool:
    """
    Process an interview email through the sub-classification pipeline.

    Creates an InterviewEvent record, resolves the student from config,
    upserts them into the students table, and creates a NotificationDraft
    so the dashboard can track and display the notification lifecycle.

    Args:
        email_data: Email data from IMAP
        email_db_id: Database ID of the email
        classification: Primary classification result

    Returns:
        True if successfully processed, False otherwise
    """
    db = get_db_session()
    if not db:
        return False

    try:
        from log_interview import log_interview_event, upsert_student, log_notification_draft

        _logger = logging.getLogger(__name__)

        extracted = classification.get("extracted_data") or {}
        sub_classification = _build_sub_classification(email_data, classification)
        sub_type = sub_classification["interview_sub_type"]

        if classification.get("category") in _NEEDS_SUBCLASSIFIER and not _is_job_machine_interview(sub_classification):
            classification["_not_an_interview"] = True
            _logger.info("Job Machine mail that is not an interview notice: no event, no student notice")
            return False

        # ── Resolve student from config/students.py ──────────────────────────
        student_id = None
        student_config = None
        try:
            from notify_student import _get_student_info, _build_student_info_for_draft, _build_classification_for_draft

            student_config, assigned_gmail = _identify_student(db, email_data, classification)
            if student_config:
                # Derive a stable username: "First Last" → "first.last"
                username = student_config.get("username") or student_config["name"].lower().replace(" ", ".")
                student_db = upsert_student(
                    db=db,
                    username=username,
                    full_name=student_config["name"],
                    personal_email=student_config.get("personal_email"),
                    assigned_gmail=assigned_gmail,
                    phone_number=student_config.get("phone"),
                )
                student_id = student_db["id"]
                if student_config.get("identified_by") == "recipient_gmail":
                    from log_interview import mark_unverified
                    mark_unverified(db, student_id, student_config.get("name_source", "gmail_guess"),
                                    student_config["name"], student_config.get("evidence", ""))
                    classification["_needs_verification"] = True
                _logger.info(
                    f"Resolved student: {student_config['name']} (DB id={student_id})"
                )
        except Exception as e:
            _logger.warning(f"Student resolution skipped: {e}")

        # ── Create InterviewEvent ─────────────────────────────────────────────
        event_result = log_interview_event(
            db=db,
            email_db_id=email_db_id,
            classification=sub_classification,
            student_id=student_id,
        )

        _logger.info(
            f"Created InterviewEvent {event_result['id']}: "
            f"{sub_type} at {extracted.get('company_name')}"
        )

        # ── Create NotificationDraft for dashboard visibility ─────────────────
        if student_id and student_config:
            try:
                from draft_notification import draft_notification
                from notify_student import _build_student_info_for_draft, _build_classification_for_draft

                student_info_for_draft = _build_student_info_for_draft(student_config)
                draft_cls = _build_classification_for_draft(
                    classification, email_data, sub_classification
                )
                assistant_name = student_config.get("assigned_to")

                draft = draft_notification(
                    classification=draft_cls,
                    student_info=student_info_for_draft,
                    assistant_name=assistant_name,
                )

                auto_send = draft["draft_status"] == "ready"
                log_notification_draft(
                    db=db,
                    interview_event_id=event_result["id"],
                    draft=draft,
                    auto_send_eligible=auto_send,
                )
                _logger.info(
                    f"Created NotificationDraft for {student_config['name']} "
                    f"(auto_send={auto_send}, status={draft['draft_status']})"
                )
            except Exception as e:
                _logger.warning(f"NotificationDraft creation skipped: {e}")

        return True

    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to process interview email: {e}")
        return False

logger = logging.getLogger(__name__)

# ── Rate limit + Cost guardrails ─────────────────────────────────────────────
# All values are configurable via environment variables so they can be tightened
# without code changes.

# Hard ceiling on emails per run regardless of --limit flag.
# Prevents runaway cost if a backlog builds up.
_MAX_EMAILS_PER_RUN: int = int(os.getenv("MAX_EMAILS_PER_RUN", "100"))

# A run whose IMAP fetch left emails behind is a *partial* failure: the emails
# stay unread and are retried next run, but the run must not look like a normal
# success. Connection-loss give-ups always count; isolated per-message failures
# (one corrupt email, which would recur every run) only count from this many.
_FETCH_ERROR_ALERT_THRESHOLD: int = 5


def _fetch_had_problems(stats: Dict[str, Any]) -> bool:
    """True if this run's INBOX fetch was partly unsuccessful (see above)."""
    return (
        stats.get("fetch_abandoned", 0) > 0
        or stats.get("fetch_errors", 0) >= _FETCH_ERROR_ALERT_THRESHOLD
    )


def _run_status(stats: Dict[str, Any]) -> str:
    """ProcessRun.status for a run that finished: 'success' or 'partial_failure'."""
    return "partial_failure" if _fetch_had_problems(stats) else "success"

# Maximum estimated USD cost for GPT calls in a single run.
# If the post-classification actual cost exceeds this, Gmail mutations are
# skipped (move/delete) to prevent compounding an already expensive run.
_MAX_COST_PER_RUN_USD: float = float(os.getenv("MAX_COST_PER_RUN_USD", "5.0"))

# gpt-4o pricing (USD per million tokens) — update if OpenAI changes pricing.
_GPT4O_INPUT_PRICE_PER_M: float = 2.50
_GPT4O_OUTPUT_PRICE_PER_M: float = 10.00

# Conservative per-email cost estimate used for the pre-run budget check.
# Based on: ~3500 input tokens (prompt + email) + ~650 output tokens per call.
_EST_COST_PER_EMAIL_USD: float = (
    (3500 / 1_000_000) * _GPT4O_INPUT_PRICE_PER_M
    + (650 / 1_000_000) * _GPT4O_OUTPUT_PRICE_PER_M
)  # ≈ $0.015 per email


def _compute_cost(input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost from actual token counts."""
    return (
        (input_tokens / 1_000_000) * _GPT4O_INPUT_PRICE_PER_M
        + (output_tokens / 1_000_000) * _GPT4O_OUTPUT_PRICE_PER_M
    )


# CRITICAL SAFETY FEATURE: Whitelist of companies that have sent genuine interview requests
# NEVER move or delete emails from these companies, regardless of AI classification
KNOWN_INTERVIEW_COMPANIES = {
    "ask consulting",
    "united global technologies",
    "excelon solutions",
    "wesco",
    "vdart",
    "refocus",
    "empiric"
}

# Folder that holds "Other" emails for a second-pass review before deletion.
# Emails that survive re-classification as spam are then permanently deleted.
SPAM_REVIEW_FOLDER = "Spam Review"
# Mail the second pass still judges "Other" is parked here, never deleted, until
# we have measured how often "Other" is wrong (see progress.md, 2026-10-01).
QUARANTINE_FOLDER = "Quarantine"

# Folder for low-confidence or unmapped categories — needs human attention.
NEEDS_REVIEW_FOLDER = "Needs Review"

# Minimum confidence required to route an email to its detected category folder.
# Below this threshold the email goes to NEEDS_REVIEW_FOLDER instead.
ROUTING_CONFIDENCE_THRESHOLD = 0.70

# Gmail label names follow the 'Email Management - Labels' workbook (Ali), renamed in Gmail 2026-10-09.
# Master category → Gmail label mapping (module-level so both INBOX processing
# and the spam-review pass use the same authoritative table).
CATEGORY_TO_FOLDER: Dict[str, str] = {
    # Interview flow
    "Interview Confirmation":    "Interview Confirmation",
    "Interview Schedule":        "Interview Request",
    "Interview Reschedule":      "Interview Rescheduled",
    "Interview Cancelled":       "Interview Cancelled",
    "Final Interview Scheduled": "Final Interview Scheduled",
    "Instant Interview":         "Instant Interview",
    "Client Screen":             "Client Screen",
    "Phone Screen":              "Phone Screen (HR or Recruiter)",
    "Technical Interview":       "Technical Interview",
    "Interview Follow-up":       "Interview follow up",   # after the interview: no event, no student notice
    # Outcomes
    "Rejection":                 "Rejections",
    "Offer":                     "Offers",
    # Jobs & applications
    "Job Alert":                 "Job Alerts",
    "Job Invite":                "Job Invite",
    "Job Machine":               "Job Machine",
    "Application Notification":  "Application Notification",
    # Actions & requests
    "More Information Request":  "More Information Request",
    "Background Check":          "More Information Request",
    "Assessment":                "Assessment",
    "Google Sheet Request":      "Google Sheet Request",
    # System / noise
    "LinkedIn Notification":     "LinkedIn Notification",
    "Gmail Notification":        "Gmail Notification",
    "Forwarded Email":           "Forwarded Emails",
    "Basecamp":                  "Basecamp",
    "Account Recovery":          "Account Recovery",
}


def _run_spam_review_pass(
    server: str, port: int, email_address: str, password: str
) -> Dict[str, int]:
    """
    Second-pass review of emails sitting in SPAM_REVIEW_FOLDER.

    Each email is re-classified:
      - Still 'Other' or still below confidence threshold → moved to the
        Quarantine folder (kept, recoverable; nothing is deleted)
      - Rescued (non-spam on second look) → moved to the correct category folder
      - Re-classification failed → left in Spam Review for the next run

    Returns:
        Dict with keys: reviewed, quarantined, rescued, deleted. 'deleted' is
        always 0 and only kept so older readers of the summary do not break.
    """
    _logger = logging.getLogger(__name__)
    results: Dict[str, int] = {"reviewed": 0, "quarantined": 0, "rescued": 0, "deleted": 0}

    try:
        review_emails = fetch_emails(
            server=server,
            port=port,
            email_address=email_address,
            password=password,
            folder=SPAM_REVIEW_FOLDER,
            criteria="ALL",
            limit=50,
            mark_as_read=False,
        )
    except Exception as e:
        _logger.debug(f"Spam Review folder not accessible (may not exist yet): {e}")
        return results

    if not review_emails:
        _logger.info("Spam Review folder is empty — nothing to re-examine.")
        return results

    _logger.info(f"")
    _logger.info(f"=== SECOND-PASS SPAM REVIEW ({len(review_emails)} email(s)) ===")

    confirmed_spam_ids: List[str] = []
    rescued_moves: Dict[str, str] = {}
    # {uid: message_id} — lets move/delete recover a stale handle via the
    # stable RFC 5322 Message-ID if a UID has shifted since this fetch.
    review_id_to_mid: Dict[str, str] = {
        str(e.get("email_id", "")): (e.get("message_id") or "")
        for e in review_emails
    }

    for email_data in review_emails:
        results["reviewed"] += 1
        subject = (email_data.get("subject") or "")[:70]
        email_id = str(email_data.get("email_id", ""))

        try:
            classification = classify_email(email_data, validate_only=False)
            classification.pop("_gpt_usage", None)
            category   = classification.get("category", "Other")
            confidence = float(classification.get("confidence", 0.0))
            edge_case  = classification.get("edge_case", {})
        except Exception as exc:
            _logger.error(f"  Re-classification failed for '{subject}': {exc} — leaving in {SPAM_REVIEW_FOLDER}")
            continue

        is_spam = (
            category == "Other"
            or confidence < ROUTING_CONFIDENCE_THRESHOLD
            or (edge_case.get("is_edge_case") and edge_case.get("type") in ["spam"])
        )

        if is_spam:
            confirmed_spam_ids.append(email_id)
            _logger.info(f"  [STILL UNCLEAR → {QUARANTINE_FOLDER}] {category} ({confidence:.0%}) — {subject}")
        else:
            dest = CATEGORY_TO_FOLDER.get(category, NEEDS_REVIEW_FOLDER)
            rescued_moves[email_id] = dest
            _logger.info(f"  [RESCUED → {dest}] {category} ({confidence:.0%}) — {subject}")

    if confirmed_spam_ids:
        try:
            quarantined = move_emails(
                server=server,
                port=port,
                email_address=email_address,
                password=password,
                email_moves={eid: QUARANTINE_FOLDER for eid in confirmed_spam_ids},
                source_folder=SPAM_REVIEW_FOLDER,
                id_to_message_id=review_id_to_mid,
            )
            results["quarantined"] = quarantined
            _logger.info(f"Spam review: moved {quarantined} unclear email(s) to {QUARANTINE_FOLDER}")
        except Exception as exc:
            _logger.error(f"Spam review quarantine move failed: {exc}")

    if rescued_moves:
        try:
            moved = move_emails(
                server=server,
                port=port,
                email_address=email_address,
                password=password,
                email_moves=rescued_moves,
                source_folder=SPAM_REVIEW_FOLDER,
                id_to_message_id=review_id_to_mid,
            )
            results["rescued"] = moved
            _logger.info(f"Spam review: rescued {moved} misclassified email(s) to correct folders")
        except Exception as exc:
            _logger.error(f"Spam review move failed: {exc}")

    _logger.info(f"=== SPAM REVIEW COMPLETE — reviewed={results['reviewed']} quarantined={results['quarantined']} rescued={results['rescued']} ===")
    _logger.info("")
    return results


def is_from_known_company(email_data: Dict[str, Any], classification: Dict[str, Any]) -> bool:
    """
    SAFETY CHECK: Check if email is from a known interview company.

    This prevents accidental deletion/moving of genuine interview requests
    even if the AI misclassifies them.

    Args:
        email_data: Email data dictionary
        classification: Classification result

    Returns:
        True if from a known interview company
    """
    # Check classification company name
    company = classification.get("extracted_data", {}).get("company_name", "")
    if company and any(known in company.lower() for known in KNOWN_INTERVIEW_COMPANIES):
        logger.info(f"SAFETY CHECK: Email from known company '{company}'")
        return True

    # Check email from address
    from_addr = email_data.get("from", "").lower()
    if any(known in from_addr for known in KNOWN_INTERVIEW_COMPANIES):
        logger.info(f"SAFETY CHECK: Email from known sender '{from_addr}'")
        return True

    # Check subject line
    subject = email_data.get("subject", "").lower()
    if any(known in subject for known in KNOWN_INTERVIEW_COMPANIES):
        logger.info(f"SAFETY CHECK: Email subject mentions known company")
        return True

    return False


def process_unread_emails(limit: Optional[int] = None, criteria: str = "UNSEEN") -> Dict[str, Any]:
    """
    Process emails from inbox matching an IMAP search criteria.

    Args:
        limit: Maximum number of emails to process (None for unlimited)
        criteria: IMAP search criteria, scoped to the INBOX folder (default
            "UNSEEN"). "ALL" catches up on anything still sitting in INBOX
            uncategorized — safe to run any time, since an email already
            processed has been relabeled out of INBOX and won't match either
            way; it only ever picks up what's arrived (or been left unlabeled)
            since the last run.

    Returns:
        Processing statistics
    """
    # Load configuration
    server = os.getenv("EMAIL_SERVER")
    port = int(os.getenv("EMAIL_PORT", "993"))
    email_address = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")

    if not all([server, email_address, password]):
        raise ValueError("Missing email configuration in .env file")

    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY not set in .env file")

    # Track processing start time for duration_seconds
    start_time = datetime.now()

    # Create output directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"tmp/auto_process_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Default stats — updated as the run progresses.
    # Defined before the try block so the finally clause can always log a
    # ProcessRun even when the run crashes mid-flight.
    stats: Dict[str, Any] = {
        "timestamp": timestamp,
        "total_emails": 0,
        "interview_requests": 0,
        "organized": 0,
        "spam_deleted": 0,
        "categories": {},
    }
    _run_logged = False  # set True once _log_process_run succeeds
    _crashed = False     # set True if the run dies with an exception

    logger.info("=" * 60)
    logger.info("AUTOMATED INBOX PROCESSING")
    logger.info("=" * 60)
    logger.info(f"Timestamp: {timestamp}")
    logger.info(f"Account: {email_address}")
    logger.info(f"Processing: {criteria} emails")
    logger.info("")

    try:
        # Second-pass review: re-classify anything already sitting in Spam Review.
        # Run this BEFORE fetching new INBOX emails so the counts stay clean.
        spam_review_stats = _run_spam_review_pass(server, port, email_address, password)
        stats["spam_review"] = spam_review_stats

        # Fetch emails matching the requested criteria
        logger.info(f"Fetching {criteria} emails...")
        emails = fetch_emails(
            server=server,
            port=port,
            email_address=email_address,
            password=password,
            folder="INBOX",
            criteria=criteria,
            limit=limit or _MAX_EMAILS_PER_RUN,  # Fetch only what we'll process
            mark_as_read=False,  # Never mark interview requests as read
            newest_first=True,  # Sort today's mail before draining any backlog
        )

        # How the fetch itself went (FetchedEmails carries these; a plain list
        # from a test double has none). Recorded before the empty-inbox return
        # below so a fetch that failed for EVERY email is not reported as
        # "no unread emails".
        stats["fetch_errors"] = getattr(emails, "skipped", 0)
        stats["fetch_abandoned"] = getattr(emails, "abandoned", 0)
        stats["fetch_reconnects"] = getattr(emails, "reconnects", 0)
        if stats["fetch_errors"] or stats["fetch_reconnects"]:
            logger.warning(
                f"FETCH PROBLEMS: skipped={stats['fetch_errors']} "
                f"abandoned_after_connection_loss={stats['fetch_abandoned']} "
                f"reconnects={stats['fetch_reconnects']} "
                f"— unfetched emails stay unread and are retried next run"
            )

        if not emails:
            logger.info("No unread emails found")
            return {
                "timestamp": timestamp,
                "total_emails": 0,
                "interview_requests": 0,
                "organized": 0,
                "spam_deleted": 0,
                "fetch_errors": stats["fetch_errors"],
                "fetch_abandoned": stats["fetch_abandoned"],
                "fetch_reconnects": stats["fetch_reconnects"],
            }

        # Apply --limit flag first (from the caller, e.g. a manual run)
        total_found = len(emails)
        if limit and len(emails) > limit:
            logger.info(f"Found {total_found} unread emails, limiting to {limit} (--limit flag)")
            emails = emails[:limit]
        else:
            logger.info(f"Found {len(emails)} unread emails")

        # Hard safety ceiling — enforced regardless of --limit
        if len(emails) > _MAX_EMAILS_PER_RUN:
            logger.warning(
                f"Email count ({len(emails)}) exceeds MAX_EMAILS_PER_RUN={_MAX_EMAILS_PER_RUN} "
                f"— truncating to prevent runaway GPT cost"
            )
            emails = emails[:_MAX_EMAILS_PER_RUN]

        # Pre-run budget estimate: abort BEFORE any API calls if projected cost
        # already exceeds the configured ceiling.
        estimated_cost = len(emails) * _EST_COST_PER_EMAIL_USD
        logger.info(
            f"Pre-run budget estimate: {len(emails)} emails × "
            f"~${_EST_COST_PER_EMAIL_USD:.4f}/email = ~${estimated_cost:.3f} "
            f"(limit: ${_MAX_COST_PER_RUN_USD:.2f})"
        )
        if estimated_cost > _MAX_COST_PER_RUN_USD:
            logger.error(
                f"COST GUARDRAIL: estimated ${estimated_cost:.2f} exceeds "
                f"MAX_COST_PER_RUN_USD=${_MAX_COST_PER_RUN_USD} — aborting run"
            )
            return {
                "timestamp": timestamp,
                "total_emails": 0,
                "interview_requests": 0,
                "organized": 0,
                "spam_deleted": 0,
                "aborted_reason": f"cost_guardrail: estimated ${estimated_cost:.2f} > limit ${_MAX_COST_PER_RUN_USD}",
            }

        # Process emails — update the pre-initialized stats dict
        stats["total_emails"] = len(emails)

        interview_requests = []
        spam_email_ids: List[str] = []  # reserved for future hard-delete bypass; not used currently
        email_moves: Dict[str, str] = {}
        verify_labels: Dict[str, str] = {}   # uid -> VERIFY_STUDENT_LABEL, for mail whose student is unverified
        # {uid: message_id} so move_emails can recover a stale handle via the
        # stable RFC 5322 Message-ID if a UID shifts between now and the move.
        id_to_mid: Dict[str, str] = {
            str(e.get("email_id", "")): (e.get("message_id") or "") for e in emails
        }

        # CATEGORY_TO_FOLDER, NEEDS_REVIEW_FOLDER, SPAM_REVIEW_FOLDER, and
        # ROUTING_CONFIDENCE_THRESHOLD are all module-level constants defined above.

        logger.info("")
        logger.info(f"Classifying {len(emails)} emails in parallel (8 workers)...")
        logger.info("")

        # ── Step 1: Classify all emails concurrently (OpenAI API calls) ──────
        def _classify_one(args: Tuple[int, Dict]) -> Tuple[int, Dict, Optional[Dict], Dict]:
            """Classify a single email.

            Applies deterministic sender-domain rules first (pre_classify_by_sender).
            Falls back to AI classification only when no rule matches.

            Returns (idx, email_data, classification|None, gpt_usage).
            gpt_usage = {"input_tokens": int, "output_tokens": int}
            """
            idx, email_data = args
            _zero_usage: Dict = {"input_tokens": 0, "output_tokens": 0}
            try:
                # Fast deterministic pre-classifier — skips AI for obvious cases
                pre_category = pre_classify_by_sender(email_data)
                if pre_category:
                    logger.info(
                        f"[{idx}] Pre-classified as '{pre_category}' "
                        f"(rule-based, no AI call) — {email_data.get('subject','')[:50]}"
                    )
                    classification = {
                        "category": pre_category,
                        "confidence": 0.99,
                        "requires_manual_review": False,
                        "reasoning": "Deterministic sender-domain rule applied.",
                        "edge_case": {"is_edge_case": False, "type": None, "confidence": 1.0, "reasoning": ""},
                        "extracted_data": {},
                    }
                    return (idx, email_data, classification, _zero_usage)

                classification = classify_email(email_data, validate_only=False)
                # Pop internal usage metadata before passing classification downstream
                usage = classification.pop("_gpt_usage", _zero_usage)
                return (idx, email_data, classification, usage)
            except Exception as exc:
                logger.error(f"Classification failed for email {idx}: {exc}")
                return (idx, email_data, None, _zero_usage)

        # Per-email timeout: 60s API call × up to 3 retries + backoff ≈ 3 min worst case.
        # Batch timeout gives every email at least 3 min plus a buffer for 16 parallel workers.
        _BATCH_TIMEOUT_S = max(180, len(emails) * 4)  # at least 3 min, ~4s/email overhead

        classified: List[Tuple[int, Dict, Optional[Dict], Dict]] = []
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = {
                pool.submit(_classify_one, (idx, email_data)): idx
                for idx, email_data in enumerate(emails, 1)
            }
            try:
                for future in as_completed(futures, timeout=_BATCH_TIMEOUT_S):
                    classified.append(future.result())
            except FuturesTimeoutError:
                logger.error(
                    f"Classification batch timed out after {_BATCH_TIMEOUT_S}s — "
                    f"collecting {sum(1 for f in futures if f.done())}/{len(futures)} completed results"
                )
                _zero: Dict = {"input_tokens": 0, "output_tokens": 0}
                for future, idx in futures.items():
                    if future.done():
                        try:
                            classified.append(future.result())
                        except Exception as exc:
                            logger.error(f"Future {idx} failed: {exc}")
                            # find the email_data for this idx
                            email_data_for_idx = next(
                                (e for i, e in enumerate(emails, 1) if i == idx), {}
                            )
                            classified.append((idx, email_data_for_idx, None, _zero))

        # Sort back into original order so logs are readable
        classified.sort(key=lambda x: x[0])

        # ── Cost accounting (post-classification) ─────────────────────────────
        total_input_tokens = sum(r[3]["input_tokens"] for r in classified)
        total_output_tokens = sum(r[3]["output_tokens"] for r in classified)
        actual_cost = _compute_cost(total_input_tokens, total_output_tokens)
        successful_calls = sum(1 for r in classified if r[2] is not None)

        logger.info(
            f"GPT usage: {successful_calls} calls | "
            f"{total_input_tokens:,} input tokens | "
            f"{total_output_tokens:,} output tokens | "
            f"estimated cost: ${actual_cost:.4f}"
        )

        # If actual cost exceeds limit, skip Gmail mutations (already paid for
        # the API calls — but don't compound with potentially wrong moves/deletes)
        cost_guardrail_triggered = actual_cost > _MAX_COST_PER_RUN_USD
        if cost_guardrail_triggered:
            logger.error(
                f"COST GUARDRAIL: actual cost ${actual_cost:.4f} exceeds "
                f"MAX_COST_PER_RUN_USD=${_MAX_COST_PER_RUN_USD} — "
                f"skipping Gmail mutations (emails classified but NOT moved/deleted)"
            )

        # ── Step 2: Apply actions sequentially (IMAP + DB) ───────────────────
        logger.info("Applying actions...")
        if cost_guardrail_triggered:
            logger.warning("Cost guardrail active — DB writes proceed, Gmail moves/deletes are SKIPPED")
        logger.info("")

        # Tracks final folder per email for SharePoint audit log
        _sp_folder_map: Dict[str, str] = {}

        for idx, email_data, classification, _usage in classified:
            email_subject = email_data.get("subject", "No Subject")[:60]

            if classification is None:
                logger.error(f"[{idx}/{len(emails)}] Skipped (classification error) - {email_subject}")
                continue

            try:
                category = classification.get("category")
                confidence = classification.get("confidence", 0)

                # CRITICAL SAFETY CHECK: Never move/delete emails from known interview companies
                from_known_company = is_from_known_company(email_data, classification)

                # Check if genuine interview request OR from known company (safety check)
                if is_genuine_interview_request(classification) or from_known_company:
                    # KEEP IN INBOX - Do not touch
                    company = classification["extracted_data"].get("company_name")

                    # Track folder for SharePoint audit log
                    _sp_folder_map[str(email_data.get("email_id", ""))] = "INBOX"

                    # Import email to database and process through interview pipeline
                    # Only count as new interview request if email is truly new (not already in DB)
                    try:
                        email_uid = str(email_data.get("email_id", ""))
                        db = get_db_session()
                        is_new_email = True
                        if db and email_uid:
                            from models import Email as EmailModel
                            is_new_email = db.query(EmailModel).filter(EmailModel.email_id == email_uid).first() is None

                        email_db_id = import_email_to_db(email_data, classification, "INBOX")

                        if is_new_email:
                            # Only count and log new interview requests
                            stats["interview_requests"] += 1
                            stats["categories"][category] = stats["categories"].get(category, 0) + 1
                            interview_requests.append({
                                "subject": email_subject,
                                "company": company,
                                "confidence": confidence,
                                "timestamp": datetime.now().isoformat(),
                                "safety_protected": from_known_company
                            })
                            if from_known_company:
                                logger.info(f"[{idx}/{len(emails)}] ** SAFETY PROTECTED (NEW) ** - {email_subject}")
                                logger.info(f"              Company: {company}")
                                logger.info(f"              Category: {category} (confidence: {confidence:.0%})")
                                logger.info(f"              [KEPT IN INBOX - KNOWN INTERVIEW COMPANY]")
                            else:
                                logger.info(f"[{idx}/{len(emails)}] ** INTERVIEW REQUEST (NEW) ** - {email_subject}")
                                logger.info(f"              Company: {company}")
                                logger.info(f"              [KEPT IN INBOX - NEEDS REVIEW]")
                        else:
                            logger.info(f"[{idx}/{len(emails)}] [ALREADY PROCESSED] - {email_subject}")

                        if email_db_id:
                            if is_new_email and not creates_interview_event(classification):
                                logger.info(f"              [NO INTERVIEW EVENT: category '{category}' is not an interview]")
                            elif is_new_email and process_interview_email(email_data, email_db_id, classification):
                                logger.info(f"              [INTERVIEW EVENT CREATED]")
                                if classification.get("_needs_verification"):
                                    verify_labels[str(email_data.get("email_id"))] = VERIFY_STUDENT_LABEL
                            elif not is_new_email:
                                pass  # Already processed, skip
                            elif classification.get("_not_an_interview"):
                                logger.info(f"              [NO INTERVIEW EVENT: not an interview notice]")
                            else:
                                logger.warning(f"              [INTERVIEW PROCESSING FAILED]")
                    except Exception as e:
                        logger.error(f"              [DB IMPORT FAILED: {e}]")
                        # Still count as interview request if DB failed but email was new
                        stats["interview_requests"] += 1
                        stats["categories"][category] = stats["categories"].get(category, 0) + 1

                elif category == "Other":
                    # Potential spam — quarantine in Spam Review for a second look.
                    # The next run's _run_spam_review_pass() will either move it to
                    # Quarantine (if still classified as Other) or rescue it to the
                    # correct folder (if it turns out to be something else).
                    stats["spam_deleted"] += 1  # counter name kept for backward compat
                    email_moves[email_data.get("email_id")] = SPAM_REVIEW_FOLDER
                    _sp_folder_map[str(email_data.get("email_id", ""))] = SPAM_REVIEW_FOLDER
                    logger.info(f"[{idx}/{len(emails)}] [POSSIBLE SPAM → Spam Review] - {email_subject}")
                    try:
                        import_email_to_db(email_data, classification, SPAM_REVIEW_FOLDER)
                    except Exception as _e:
                        logger.error(f"              [DB import failed: {_e}]")

                else:
                    # OTHER CATEGORIES - Organize
                    stats["organized"] += 1
                    stats["categories"][category] = stats["categories"].get(category, 0) + 1

                    # Low-confidence classifications go to Needs Review instead of
                    # the target folder — a human should verify before the email is
                    # acted on.  Unmapped categories also land in Needs Review so
                    # they never loop in INBOX forever as UNSEEN.
                    mapped_folder = CATEGORY_TO_FOLDER.get(category)
                    if confidence < ROUTING_CONFIDENCE_THRESHOLD:
                        server_folder = NEEDS_REVIEW_FOLDER
                        logger.warning(
                            f"              [Low confidence {confidence:.0%} < {ROUTING_CONFIDENCE_THRESHOLD:.0%}"
                            f" — routing '{category}' to '{NEEDS_REVIEW_FOLDER}']"
                        )
                    elif mapped_folder:
                        server_folder = mapped_folder
                    else:
                        server_folder = NEEDS_REVIEW_FOLDER
                        logger.warning(f"              [No folder mapping for '{category}' — moved to '{NEEDS_REVIEW_FOLDER}']")

                    email_moves[email_data.get("email_id")] = server_folder

                    # Track folder for SharePoint audit log
                    _sp_folder_map[str(email_data.get("email_id", ""))] = server_folder

                    logger.info(f"[{idx}/{len(emails)}] [{category}] ({confidence:.0%}) → {server_folder} — {email_subject}")

                    # Save to database for audit trail. An interview-related email (Phone Screen, Cancelled,
                    # Confirmation, Schedule, Assessment...) also needs its InterviewEvent, otherwise it never
                    # reaches Interviews, Upcoming or the student notifications (20 such emails had none).
                    try:
                        _new_here = _is_new_email(email_data)
                        _db_id = import_email_to_db(email_data, classification, server_folder)
                        if _db_id and _new_here and creates_interview_event(classification):
                            if process_interview_email(email_data, _db_id, classification):
                                logger.info(f"              [INTERVIEW EVENT CREATED]")
                                if classification.get("_needs_verification"):
                                    verify_labels[str(email_data.get("email_id"))] = VERIFY_STUDENT_LABEL
                            elif classification.get("_not_an_interview"):
                                logger.info(f"              [NO INTERVIEW EVENT: not an interview notice]")
                            else:
                                logger.warning(f"              [INTERVIEW PROCESSING FAILED]")
                    except Exception as _e:
                        logger.error(f"              [DB import failed: {_e}]")

            except Exception as e:
                logger.error(f"Failed to apply action for email {idx}: {e}")

        # "Verify Student" label: added in place (no move) BEFORE any move, so the UID is still in INBOX.
        if verify_labels and not cost_guardrail_triggered:
            try:
                n_lab = label_emails(server=server, port=port, email_address=email_address, password=password,
                                     email_labels=verify_labels, id_to_message_id=id_to_mid)
                logger.info(f"Labelled {n_lab} of {len(verify_labels)} email(s) '{VERIFY_STUDENT_LABEL}'")
            except Exception as e:
                logger.error(f"Failed to add the '{VERIFY_STUDENT_LABEL}' label: {e}")

        # Move organized emails
        if email_moves and not cost_guardrail_triggered:
            logger.info("")
            logger.info(f"Moving {len(email_moves)} emails to category folders...")
            try:
                moved_count = move_emails(
                    server=server,
                    port=port,
                    email_address=email_address,
                    password=password,
                    email_moves=email_moves,
                    id_to_message_id=id_to_mid,
                )
                logger.info(f"Successfully moved {moved_count} emails")
            except Exception as e:
                logger.error(f"Failed to move emails: {e}")
        elif email_moves and cost_guardrail_triggered:
            logger.warning(f"Cost guardrail: skipped moving {len(email_moves)} emails")

        # ── Google Sheets audit log ───────────────────────────────────────────
        # Non-blocking: appends all classified emails to a Google Sheet for
        # reference tracking. Silently skipped if not configured.
        try:
            from log_to_google_sheets import log_batch_to_sheets, is_configured as _gs_configured
            if _gs_configured():
                logger.info("Logging classified emails to Google Sheets...")
                gs_result = log_batch_to_sheets(classified, _sp_folder_map)
                logger.info(
                    f"Google Sheets: {gs_result['logged']} rows appended, "
                    f"{gs_result.get('failed', 0)} failed"
                )
                stats["google_sheets"] = gs_result
            else:
                logger.debug("Google Sheets not configured — skipping audit log")
        except Exception as _gs_err:
            logger.warning(f"Google Sheets batch logging failed (non-fatal): {_gs_err}")

        # Calculate and record duration
        duration_seconds = (datetime.now() - start_time).total_seconds()
        stats["duration_seconds"] = duration_seconds

        # Record GPT usage metrics
        stats["gpt_usage"] = {
            "calls": successful_calls,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "estimated_cost_usd": round(actual_cost, 6),
            "cost_guardrail_triggered": cost_guardrail_triggered,
        }

        # Save summary
        summary = {
            "processing_timestamp": datetime.utcnow().isoformat() + "Z",
            "duration_seconds": duration_seconds,
            "statistics": stats,
            "interview_requests": interview_requests
        }

        summary_file = output_dir / "summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        # Print summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("PROCESSING SUMMARY")
        logger.info("=" * 60)
        sr = stats.get("spam_review", {})
        logger.info(f"Total Processed: {stats['total_emails']}")
        logger.info(f"Interview Requests (kept in inbox): {stats['interview_requests']}")
        logger.info(f"Organized to folders: {stats['organized']}")
        logger.info(f"Quarantined to Spam Review: {stats['spam_deleted']}")
        logger.info(
            f"Spam Review pass: "
            f"reviewed={sr.get('reviewed', 0)} "
            f"quarantined={sr.get('quarantined', 0)} "
            f"rescued={sr.get('rescued', 0)}"
        )

        if interview_requests:
            logger.info("")
            logger.info("INTERVIEW REQUESTS IN INBOX:")
            for ir in interview_requests:
                logger.info(f"  - {ir['company']}: {ir['subject']}")

        logger.info("")
        logger.info(f"Summary saved to: {summary_file}")
        logger.info("=" * 60)

        # Log this run to the dashboard ProcessRun table. A run whose fetch left
        # emails behind is recorded as a partial failure, not a plain success.
        _log_process_run(stats, summary_file, status=_run_status(stats))
        _run_logged = True

        return stats

    except Exception as e:
        _crashed = True
        logger.error(f"Error during processing: {e}", exc_info=True)
        raise

    finally:
        # Make sure the dashboard has a ProcessRun for every run that went wrong,
        # not just ones that got as far as processing emails:
        #   * crashed at any point (even before one email was fetched, e.g. Gmail
        #     auth failure)                              -> "failed"
        #   * emails were fetched but the run never reached the normal log -> "failed"
        #   * the fetch left emails behind and nothing else happened (e.g. every
        #     fetch failed, so "0 emails")                 -> "partial_failure"
        # A clean, genuinely empty run still writes no row (unchanged).
        if not _run_logged:
            _had_emails = stats.get("total_emails", 0) > 0
            if _crashed or _had_emails or _fetch_had_problems(stats):
                stats["duration_seconds"] = (datetime.now() - start_time).total_seconds()
                _log_process_run(
                    stats,
                    status="failed" if (_crashed or _had_emails) else _run_status(stats),
                )
        if _db_error:
            stats["db_error"] = _db_error
        # Clean up database session
        close_db_session()


def _log_process_run(stats: Dict[str, Any], summary_file=None, status: str = "success") -> None:
    """
    Write a ProcessRun record to the dashboard database so the UI shows
    the latest run stats and the countdown timer has a reference point.
    Called on success AND in the finally block on crash (status="failed").
    """
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        # Use DATABASE_URL env var if set (cloud deployment), else fall back to local SQLite
        dashboard_db_url = normalize_db_url(os.getenv("DATABASE_URL"))
        if not dashboard_db_url:
            db_path = project_root / "services" / "dashboard" / "api" / "email_dashboard.db"
            if not db_path.exists():
                logger.warning("Dashboard database not found — skipping ProcessRun log")
                return
            dashboard_db_url = f"sqlite:///{db_path}"

        engine_kwargs = {"echo": False}
        if dashboard_db_url.startswith("postgres"):
            engine_kwargs.update(pool_pre_ping=True, pool_recycle=280)
        engine = create_engine(dashboard_db_url, **engine_kwargs)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            from models import ProcessRun

            # Parse timestamp from summary stats
            ts_str = stats.get("timestamp", "")
            try:
                run_timestamp = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            except ValueError:
                run_timestamp = datetime.utcnow()

            # Avoid duplicate entries
            existing = db.query(ProcessRun).filter(
                ProcessRun.run_timestamp == run_timestamp
            ).first()

            if existing:
                logger.debug("ProcessRun record already exists for this run")
                return

            gpt_usage = stats.get("gpt_usage") or {}
            process_run = ProcessRun(
                run_timestamp=run_timestamp,
                total_emails=stats.get("total_emails", 0),
                interview_requests=stats.get("interview_requests", 0),
                organized=stats.get("organized", 0),
                spam_deleted=stats.get("spam_deleted", 0),
                categories_breakdown=stats.get("categories", {}),
                duration_seconds=stats.get("duration_seconds", 0),
                gpt_cost_usd=gpt_usage.get("estimated_cost_usd", 0.0),
                status=status,
            )
            db.add(process_run)
            db.commit()
            logger.info(f"Dashboard ProcessRun record created (id={process_run.id})")
        except Exception as e:
            db.rollback()
            logger.warning(f"Could not write ProcessRun to dashboard DB: {e}")
            _record_db_error(f"Could not write ProcessRun to dashboard DB: {e}")
        finally:
            db.close()
            engine.dispose()

    except Exception as e:
        logger.warning(f"_log_process_run failed: {e}")
        _record_db_error(f"_log_process_run failed: {e}")


def _sender_domain(from_addr: str) -> str:
    """Domain of an address like 'Name <a@alert.indeed.com>' ('' when there is none)."""
    m = re.search(r"@([\w.-]+)", from_addr or "")
    return m.group(1).lower().rstrip(".") if m else ""


def _domain_is(domain: str, *roots: str) -> bool:
    """True when `domain` is one of `roots` or a subdomain of one (alert.indeed.com matches indeed.com)."""
    return any(domain == r or domain.endswith("." + r) for r in roots)


# A subject that is only a link to a posting on a known job site (what a student sends when forwarding a job). Not "Fwd: <link>": that can carry a real message.
_BARE_JOB_LINK = re.compile(
    r"(?:linkedin\.com/(?:comm/)?jobs/|indeed\.com/(?:viewjob|rc/clk|m/viewjob)|glassdoor\.com/job-listing|ziprecruiter\.com/(?:c|jobs|k)/"
    r"|dice\.com/(?:job-detail|jobs/detail)|monster\.com/job-openings|careerbuilder\.com/job/|simplyhired\.com/job/)", re.I)


_ADDR = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def _is_self_sent(email_data: Dict[str, Any], from_addr: str) -> bool:
    """True when a student mailed their own account: the sender is also one of the recipients (To/Cc or the delivery headers).
    Employers never send mail to themselves, so this is a note-to-self (a screenshot, a saved link, proof of an application), never news about an interview.
    Colaberry's own addresses are excluded: staff mail to the central inbox is not a student note-to-self."""
    sender = from_addr.strip().lower()
    if not sender or sender.endswith("colaberry.com"):
        return False
    recipients = {a.lower() for a in (email_data.get("to_addresses") or []) if isinstance(a, str)}
    for value in (email_data.get("headers") or {}).values():
        recipients.update(a.lower() for a in _ADDR.findall(str(value)))
    return sender in recipients


def pre_classify_by_sender(email_data: Dict[str, Any]) -> Optional[str]:
    """
    Apply deterministic sender-domain rules BEFORE the AI classification call.

    Returns a category string if a confident rule matches, or None to let the
    AI decide. This eliminates the most common misclassifications (retail promos
    landing in Offer, job-board alerts landing in Gmail Notification, etc.)
    without any API cost.
    """
    # Support both key naming conventions: fetch_emails uses "sender_email"/"body_content",
    # older callers may use "from"/"body". Check both to be safe.
    from_addr = (email_data.get("sender_email") or email_data.get("from") or "").lower()
    subject   = (email_data.get("subject") or "").lower()
    body      = (email_data.get("body_content") or email_data.get("body") or "").lower()[:500]

    # ── A student mailing their own account — a note to self, never an interview notice ──
    if _is_self_sent(email_data, from_addr):
        return "Other"

    # ── LinkedIn ────────────────────────────────────────────────────────────
    domain = _sender_domain(from_addr)
    if _domain_is(domain, "linkedin.com"):
        return "LinkedIn Notification"

    # ── Basecamp ────────────────────────────────────────────────────────────
    if _domain_is(domain, "basecamp.com", "3.basecamp.com"):
        return "Basecamp"

    # ── Job boards — always Job Alert ───────────────────────────────────────
    JOB_BOARD_DOMAINS = [
        "indeed.com", "jobleads.com", "ziprecruiter.com", "glassdoor.com",
        "monster.com", "dice.com", "careerbuilder.com", "simplyhired.com",
        "lensa.com", "snagajob.com", "flexjobs.com", "getwork.com",
        # Seen as Job Alert on every one of 800+ mails in 2026-10 (Gmail sample); sent from subdomains the old exact-match rule missed.
        "refer.io", "adzuna.com", "jobs2web.com", "jobs2careers.com", "theladders.com", "postjobfree.com",
        # Lead-generation mailers whose subjects read like interview invitations ("confirm your interview availability").
        "job-assist-now.com", "job-matches.com",
        # Headhunter network mailers (14 mails, none an interview).
        "experteer.com",
    ]
    if _domain_is(domain, *JOB_BOARD_DOMAINS):
        return "Job Alert"

    # ── Colaberry school form mailer (Kes 2026-10-10): "New/Final Project Request" notices, never an interview. Exact address only: other school.colaberry.com mail is not touched. ──
    if from_addr.strip() == "info@school.colaberry.com":
        return "Other"

    # ── Marketing and newsletter senders — never job-related ──────────────────
    # 2026-10-10: Kes asked for these to classify themselves. Checked on production: 0 interview events ever from any of them (65, 221, 17, 9 mails).
    # "Other" goes to Spam Review, then Quarantine on the next run; nothing is deleted.
    if _domain_is(domain, "dataengineeracademy.com", "arcamax.com", "irelaunch.com", "propertymeld.com"):
        return "Other"

    # ── Community platform reminders (Skool) — never interview-related ───────
    # 2026-10-01: "1 event happening tomorrow" reminders were landing in the review
    # queue at 0.65 because the model had no category for them.
    if re.search(r"@(?:[\w-]+\.)*skool\.com(?![\w-])", from_addr):
        return "Other"

    # ── Bare LinkedIn job links — a student forwarding a posting, not an interview ─
    # Subject is just the URL, so there is no interview context for the model to find.
    if subject.strip().startswith("http") and _BARE_JOB_LINK.search(subject):
        return "Job Alert"

    # ── Social media / entertainment notifications — never interview-related ─
    SOCIAL_DOMAINS = [
        "@tiktok.com", "@facebookmail.com", "@instagram.com", "@twitter.com",
        "@x.com", "@youtube.com", "@snapchat.com", "@pinterest.com",
    ]
    if any(d in from_addr for d in SOCIAL_DOMAINS):
        return "Other"

    # ── Gmail/Google system notifications ───────────────────────────────────
    # STRICT: sender MUST be from an official Google domain for Gmail Notification.
    GOOGLE_SYSTEM_DOMAINS = ["@google.com", "@accounts.google.com", "@googlemail.com"]
    GMAIL_SUBJECT_KEYWORDS = [
        "gmail", "google account", "sign-in attempt", "new sign-in",
        "forwarding confirmation", "storage", "security alert",
    ]
    if any(d in from_addr for d in GOOGLE_SYSTEM_DOMAINS):
        if any(kw in subject or kw in body for kw in GMAIL_SUBJECT_KEYWORDS):
            return "Gmail Notification"

    # ── Account Recovery — only actual reset/verification emails ────────────
    RECOVERY_KEYWORDS = [
        "reset your password", "password reset", "your verification code",
        "verification code is", "account recovery", "confirm your email",
        "verify your account", "one-time code", "otp:", "security code",
    ]
    if any(kw in subject or kw in body for kw in RECOVERY_KEYWORDS):
        return "Account Recovery"

    # ── Retail / promotional — never Offer or Interview category ────────────
    RETAIL_SIGNALS = [
        "% off", "save $", "snag a deal", "free shipping", "shop now",
        "limited time offer", "sale ends", "discount code", "promo code",
        "clearance", "buy now", "best deals", "today only", "cashback",
        "shop the", "gear for", "apparel", "bike gear", "summit club",
    ]
    if any(sig in subject or sig in body for sig in RETAIL_SIGNALS):
        return "Other"

    return None  # Let AI decide


def is_genuine_interview_request(classification: Dict[str, Any]) -> bool:
    """
    Determine if this is a REAL interview request (not a job alert).

    Based on the golden rule:
    "Interview Request = Initial outreach requesting an interview or availability,
    NO TIME CONFIRMED YET. They want to talk, but nothing is scheduled yet."

    Args:
        classification: Classification result

    Returns:
        True if genuine interview request that needs immediate attention
    """
    category = classification.get("category")

    # Must be categorized as Interview Request
    if category != "Interview Request":
        return False

    # Check confidence - must be high confidence (>=80%)
    confidence = classification.get("confidence", 0)
    if confidence < 0.80:
        return False

    # Check edge case - not spam or automated
    edge_case = classification.get("edge_case", {})
    if edge_case.get("is_edge_case"):
        edge_type = edge_case.get("type")
        if edge_type in ["spam", "unclear", "multi-intent"]:
            return False

    # Check extracted data - must have real company (not job board aggregator)
    extracted = classification.get("extracted_data", {})
    company = extracted.get("company_name")
    if not company:
        return False

    # Reject if from job board aggregators
    company_lower = company.lower()
    job_board_indicators = [
        "job board", "indeed", "linkedin", "ziprecruiter", "glassdoor",
        "monster", "careerbuilder", "dice", "job alert", "job posting"
    ]
    if any(indicator in company_lower for indicator in job_board_indicators):
        return False

    # All checks passed - this is a genuine interview request
    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Process unread emails from inbox with AI classification"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of emails to process (default: process all)"
    )
    parser.add_argument(
        "--criteria",
        choices=["UNSEEN", "ALL"],
        default="UNSEEN",
        help=(
            "IMAP search criteria within INBOX (default: UNSEEN, used by the "
            "scheduled cron run). ALL is for one-off catch-up runs — it picks "
            "up anything still sitting in INBOX uncategorized, including "
            "already-read mail, without reprocessing anything already moved "
            "out of INBOX by a prior run."
        ),
    )
    parser.add_argument(
        "--triggered-by",
        default="scheduled",
        help="Label for who triggered this run (default: scheduled)"
    )
    args = parser.parse_args()

    # ── Alerting (non-blocking — failure here must never crash the run) ────────
    try:
        from alert import send_failure_alert, is_configured as _alert_configured
        _alerting_enabled = _alert_configured()
    except Exception:
        send_failure_alert = None  # type: ignore[assignment]
        _alerting_enabled = False

    # ── Run lock protection ───────────────────────────────────────────────────
    # Prevents concurrent execution: double Gmail mutations, GPT cost spikes,
    # race conditions outside the DB.
    from run_lock import acquire_lock, release_lock
    if not acquire_lock(triggered_by=args.triggered_by):
        logger.warning("Another processing run is already active — exiting.")
        sys.exit(2)  # Exit 2 = already running (not an error for the scheduler)

    try:
        stats = process_unread_emails(limit=args.limit, criteria=args.criteria)

        # ── Alert: pre-run cost guardrail abort ───────────────────────────────
        aborted = stats.get("aborted_reason", "")
        if aborted and send_failure_alert:
            send_failure_alert(
                "Run aborted — cost guardrail",
                f"The email processing run was aborted BEFORE any GPT calls:\n\n"
                f"  Reason: {aborted}\n\n"
                f"Action: Increase MAX_COST_PER_RUN_USD or reduce email volume in .env",
            )

        # ── Alert: post-classification cost guardrail ─────────────────────────
        gpt = stats.get("gpt_usage", {})
        if gpt.get("cost_guardrail_triggered") and send_failure_alert:
            actual = gpt.get("estimated_cost_usd", 0.0)
            send_failure_alert(
                "Cost guardrail triggered — Gmail moves SKIPPED",
                f"Emails were classified by GPT but NOT moved or deleted because\n"
                f"the actual cost exceeded the per-run limit.\n\n"
                f"  Actual cost : ${actual:.4f}\n"
                f"  Limit       : ${_MAX_COST_PER_RUN_USD}\n"
                f"  Emails seen : {stats.get('total_emails', '?')}\n\n"
                f"Action: Check logs, then increase MAX_COST_PER_RUN_USD in .env if needed.\n"
                f"  The emails remain unread in Gmail — next run will retry them.",
            )

        # ── Alert: dashboard DB unreachable (emails sorted, nothing recorded) ─
        db_error = stats.get("db_error")
        if db_error:
            logger.error(f"DASHBOARD DB WRITES FAILED this run: {db_error}")
            if os.getenv("GITHUB_ACTIONS") == "true":
                # Annotation shows on the run page even though the job stays green
                print(f"::error title=Dashboard DB writes failed::{db_error}")
            if send_failure_alert:
                send_failure_alert(
                    "Dashboard DB writes FAILED — emails sorted but not recorded",
                    f"Gmail processing completed, but writes to the dashboard\n"
                    f"database failed, so this run's emails, interview events,\n"
                    f"notification drafts and ProcessRun row are missing.\n\n"
                    f"  First error : {db_error}\n"
                    f"  Emails seen : {stats.get('total_emails', '?')}\n\n"
                    f"Action: see RUNBOOK.md §12 'Dashboard shows no / stale data'.",
                )

        # ── Alert: IMAP fetch left emails behind (run looks green but isn't) ──
        if _fetch_had_problems(stats):
            logger.error(
                f"FETCH INCOMPLETE this run: {stats.get('fetch_errors', 0)} email(s) "
                f"not fetched ({stats.get('fetch_abandoned', 0)} after connection loss)"
            )
            if send_failure_alert:
                send_failure_alert(
                    "Email fetch incomplete — some emails were not processed",
                    f"The IMAP fetch could not retrieve every email this run.\n\n"
                    f"  Not fetched          : {stats.get('fetch_errors', 0)}\n"
                    f"  Given up after a lost connection: {stats.get('fetch_abandoned', 0)}\n"
                    f"  Reconnects performed : {stats.get('fetch_reconnects', 0)}\n"
                    f"  Emails processed     : {stats.get('total_emails', 0)}\n\n"
                    f"Nothing is lost: unfetched emails stay unread in Gmail and the\n"
                    f"next scheduled run picks them up. The run is recorded as\n"
                    f"'partial_failure' on the dashboard.\n"
                    f"If this repeats, see RUNBOOK.md §4c (Hetzner failure playbook).",
                )

        if stats["interview_requests"] > 0:
            logger.info(f"ACTION REQUIRED: {stats['interview_requests']} interview request(s) in inbox.")
        sys.exit(0)  # Always exit 0 so the scheduler (cron) doesn't treat a handled run as a crash

    except Exception as e:
        import traceback as _tb
        logger.error(f"Fatal error: {e}\n{_tb.format_exc()}")
        if send_failure_alert:
            send_failure_alert(
                f"FATAL ERROR: {type(e).__name__}",
                f"The email processing script crashed with an unhandled error.\n\n"
                f"  Error      : {e}\n"
                f"  Triggered by: {args.triggered_by}\n\n"
                f"The run was aborted. Emails in Gmail are unchanged.\n"
                f"Check logs/inbox_auto_*.log for the full traceback.",
                exc=e,
            )
        sys.exit(1)  # Error

    finally:
        release_lock()


if __name__ == "__main__":
    main()
