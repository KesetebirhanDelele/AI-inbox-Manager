"""
Email notification sending execution script.

Sends populated email notifications to students via Gmail SMTP.
All outgoing emails BCC c_interviews@colaberry.com for audit.

Design principles:
- Pure SMTP logic, no orchestration
- Validates inputs before sending
- Returns structured result with send status
- Handles errors gracefully (connection, auth, delivery)
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SMTP configuration from environment
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Colaberry Interview Support")

# BCC address for audit trail
BCC_ADDRESS = "c_interviews@colaberry.com"


def validate_send_inputs(
    recipient_email: str,
    subject: str,
    body: str,
) -> Optional[str]:
    """
    Validate that all required inputs are present before sending.

    Args:
        recipient_email: Student's personal email
        subject: Email subject line
        body: Email body text

    Returns:
        Error message string if validation fails, None if valid
    """
    if not recipient_email or "@" not in recipient_email:
        return f"Invalid recipient email: {recipient_email!r}"

    if not subject or not subject.strip():
        return "Email subject is empty"

    if not body or not body.strip():
        return "Email body is empty"

    return None


def build_email_message(
    recipient_email: str,
    subject: str,
    body: str,
    from_name: Optional[str] = None,
    from_email: Optional[str] = None,
    bcc: Optional[str] = None,
    cc: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> MIMEMultipart:
    """
    Build a MIME email message.

    Args:
        recipient_email: Student's personal email address
        subject: Email subject line
        body: Email body (plain text)
        from_name: Display name of sender
        from_email: Sender email address
        bcc: BCC address for audit

    Returns:
        Constructed MIMEMultipart message
    """
    sender_name = from_name or SMTP_FROM_NAME
    sender_email = from_email or SMTP_USERNAME

    msg = MIMEMultipart()
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = recipient_email
    msg["Subject"] = subject

    if cc:
        msg["Cc"] = cc
    if reply_to:
        msg["Reply-To"] = reply_to
    if bcc:
        msg["Bcc"] = bcc

    # Attach body as plain text
    msg.attach(MIMEText(body, "plain", "utf-8"))

    return msg


def send_email(
    recipient_email: str,
    subject: str,
    body: str,
    from_name: Optional[str] = None,
    from_email: Optional[str] = None,
    bcc: Optional[str] = None,
    smtp_server: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_username: Optional[str] = None,
    smtp_password: Optional[str] = None,
    cc: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send an email via Gmail SMTP.

    Args:
        recipient_email: Student's personal email address
        subject: Email subject line
        body: Email body text
        from_name: Display name of sender
        from_email: Sender email address
        bcc: BCC address (defaults to c_interviews@colaberry.com)
        smtp_server: SMTP server hostname (defaults to env)
        smtp_port: SMTP port (defaults to env)
        smtp_username: SMTP username (defaults to env)
        smtp_password: SMTP password (defaults to env)

    Returns:
        Dictionary with:
            - status: "sent" | "failed" | "validation_error"
            - message_id: str (if sent)
            - error: str (if failed)
            - timestamp: ISO datetime string
            - recipient: str
    """
    result = {
        "status": "failed",
        "message_id": None,
        "error": None,
        "timestamp": datetime.utcnow().isoformat(),
        "recipient": recipient_email,
    }

    # Validate inputs
    validation_error = validate_send_inputs(recipient_email, subject, body)
    if validation_error:
        result["status"] = "validation_error"
        result["error"] = validation_error
        logger.error(f"Validation failed: {validation_error}")
        return result

    # Resolve SMTP configuration
    server = smtp_server or SMTP_SERVER
    port = smtp_port or SMTP_PORT
    username = smtp_username or SMTP_USERNAME
    password = smtp_password or SMTP_PASSWORD
    bcc_addr = bcc if bcc is not None else BCC_ADDRESS

    if not username or not password:
        result["status"] = "failed"
        result["error"] = "SMTP credentials not configured (SMTP_USERNAME / SMTP_PASSWORD)"
        logger.error(result["error"])
        return result

    # Build the email message
    msg = build_email_message(
        recipient_email=recipient_email,
        subject=subject,
        body=body,
        from_name=from_name,
        from_email=from_email or username,
        bcc=bcc_addr,
        cc=cc,
        reply_to=reply_to,
    )

    # Send via SMTP
    try:
        logger.info(f"Connecting to SMTP server {server}:{port}")
        with smtplib.SMTP(server, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)

            # Build recipient list (To + BCC)
            recipients = [recipient_email]
            if cc:
                recipients.extend(a.strip() for a in cc.split(",") if a.strip())
            if bcc_addr:
                recipients.append(bcc_addr)

            smtp.sendmail(
                from_addr=from_email or username,
                to_addrs=recipients,
                msg=msg.as_string(),
            )

            # Extract message ID from headers
            message_id = msg.get("Message-ID", "")

            result["status"] = "sent"
            result["message_id"] = message_id
            logger.info(
                f"Email sent to {recipient_email} "
                f"(Message-ID: {message_id})"
            )

    except smtplib.SMTPAuthenticationError as e:
        result["error"] = f"SMTP authentication failed: {e}"
        logger.error(result["error"])
    except smtplib.SMTPRecipientsRefused as e:
        result["error"] = f"Recipient refused: {e}"
        logger.error(result["error"])
    except smtplib.SMTPException as e:
        result["error"] = f"SMTP error: {e}"
        logger.error(result["error"])
    except ConnectionError as e:
        result["error"] = f"Connection error: {e}"
        logger.error(result["error"])
    except TimeoutError as e:
        result["error"] = f"Connection timeout: {e}"
        logger.error(result["error"])
    except Exception as e:
        result["error"] = f"Unexpected error: {e}"
        logger.error(result["error"])

    return result


def send_notification(
    draft: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Send a notification email from a draft_notification result.

    Convenience wrapper around send_email that takes a draft dict
    (as returned by draft_notification.draft_notification()).

    Args:
        draft: Draft notification dictionary with:
            - recipient_email: str
            - email_subject: str
            - email_body: str
            - bcc: str

    Returns:
        Send result dictionary (same as send_email)
    """
    recipient = draft.get("recipient_email", "")
    subject = draft.get("email_subject", "")
    body = draft.get("email_body", "")
    bcc = draft.get("bcc", BCC_ADDRESS)

    return send_email(
        recipient_email=recipient,
        subject=subject,
        body=body,
        bcc=bcc,
    )
