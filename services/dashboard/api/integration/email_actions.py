"""
Integration wrapper for email actions (move, delete, mark read).

Provides interface to perform actions on emails and log them to database.
"""

import sys
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session

# Add execution directory to path (local dev only)
execution_path = Path(__file__).parent.parent.parent.parent.parent / "execution"
sys.path.insert(0, str(execution_path))

try:
    from fetch_emails import move_emails, delete_emails
    IMAP_AVAILABLE = True
except ImportError:
    IMAP_AVAILABLE = False
    move_emails = None
    delete_emails = None

from config import settings
from models import Email, EmailAction

logger = logging.getLogger(__name__)


def move_email(
    db: Session,
    email: Email,
    target_folder: str,
    performed_by: str,
    reason: Optional[str] = None
) -> EmailAction:
    """
    Move an email to a different folder.

    Args:
        db: Database session
        email: Email object to move
        target_folder: Target IMAP folder name
        performed_by: Username performing the action
        reason: Optional reason for the move

    Returns:
        EmailAction object logging the move

    Raises:
        Exception: If move fails
    """
    logger.info(f"Moving email {email.email_id} to {target_folder}")

    # Prepare move operation. Handle is the UID; pass the Message-ID too so
    # move_emails() can recover if that UID has since shifted.
    email_moves = {email.email_id: target_folder}
    id_to_mid = {str(email.email_id): (email.message_id or "")}

    # Execute move via IMAP
    try:
        if not IMAP_AVAILABLE:
            raise Exception("IMAP actions not available in cloud deployment")
        moved_count = move_emails(
            server=settings.email_server,
            port=settings.email_port,
            email_address=settings.email_address,
            password=settings.email_password,
            email_moves=email_moves,
            source_folder=email.current_folder or "INBOX",   # the mail is usually NOT in INBOX any more; looking only there made every move fail
            id_to_message_id=id_to_mid,
        )

        if moved_count == 0:
            raise Exception(f"Failed to move email {email.email_id}")

    except Exception as e:
        logger.error(f"Error moving email {email.email_id}: {e}")
        raise

    # Update email record in database
    from_folder = email.current_folder
    email.current_folder = target_folder
    email.last_updated = datetime.utcnow()

    # Log action in database
    action = EmailAction(
        email_id=email.id,
        action_type="moved",
        from_folder=from_folder,
        to_folder=target_folder,
        performed_by=performed_by,
        performed_at=datetime.utcnow(),
        reason=reason
    )

    db.add(action)
    db.commit()
    db.refresh(action)

    logger.info(f"Email {email.email_id} moved successfully")
    return action


def delete_email(
    db: Session,
    email: Email,
    performed_by: str,
    reason: Optional[str] = None
) -> EmailAction:
    """
    Delete an email permanently.

    Args:
        db: Database session
        email: Email object to delete
        performed_by: Username performing the action
        reason: Optional reason for deletion

    Returns:
        EmailAction object logging the deletion

    Raises:
        Exception: If deletion fails
    """
    logger.info(f"Deleting email {email.email_id}")

    # Execute delete via IMAP
    try:
        if not IMAP_AVAILABLE:
            raise Exception("IMAP actions not available in cloud deployment")
        deleted_count = delete_emails(
            server=settings.email_server,
            port=settings.email_port,
            email_address=settings.email_address,
            password=settings.email_password,
            email_ids=[email.email_id],
            id_to_message_id={str(email.email_id): (email.message_id or "")},
        )

        if deleted_count == 0:
            raise Exception(f"Failed to delete email {email.email_id}")

    except Exception as e:
        logger.error(f"Error deleting email {email.email_id}: {e}")
        raise

    # Log action in database (before deleting email record)
    action = EmailAction(
        email_id=email.id,
        action_type="deleted",
        from_folder=email.current_folder,
        to_folder=None,
        performed_by=performed_by,
        performed_at=datetime.utcnow(),
        reason=reason
    )

    db.add(action)

    # Update email record (mark as deleted, don't actually remove)
    email.current_folder = "DELETED"
    email.last_updated = datetime.utcnow()

    db.commit()
    db.refresh(action)

    logger.info(f"Email {email.email_id} deleted successfully")
    return action


def mark_email_read(
    db: Session,
    email: Email,
    performed_by: str,
    mark_as_read: bool = True
) -> EmailAction:
    """
    Mark an email as read or unread.

    Note: This is a database-only operation for now.
    Full IMAP implementation would require additional IMAP commands.

    Args:
        db: Database session
        email: Email object
        performed_by: Username performing the action
        mark_as_read: True to mark as read, False for unread

    Returns:
        EmailAction object logging the change
    """
    action_type = "marked_read" if mark_as_read else "marked_unread"
    logger.info(f"{action_type}: {email.email_id}")

    # Update email record
    email.is_read = mark_as_read
    email.last_updated = datetime.utcnow()

    # Log action
    action = EmailAction(
        email_id=email.id,
        action_type=action_type,
        from_folder=email.current_folder,
        to_folder=email.current_folder,
        performed_by=performed_by,
        performed_at=datetime.utcnow()
    )

    db.add(action)
    db.commit()
    db.refresh(action)

    logger.info(f"Email {email.email_id} {action_type}")
    return action


def bulk_move_emails(
    db: Session,
    email_ids: List[str],
    target_folder: str,
    performed_by: str,
    reason: Optional[str] = None
) -> List[EmailAction]:
    """
    Move multiple emails to a folder.

    Args:
        db: Database session
        email_ids: List of email IDs to move
        target_folder: Target folder name
        performed_by: Username performing the action
        reason: Optional reason

    Returns:
        List of EmailAction objects
    """
    logger.info(f"Bulk moving {len(email_ids)} emails to {target_folder}")

    # Prepare move operations
    email_moves = {email_id: target_folder for email_id in email_ids}

    # Execute moves via IMAP
    try:
        if not IMAP_AVAILABLE:
            raise Exception("IMAP actions not available in cloud deployment")
        moved_count = move_emails(
            server=settings.email_server,
            port=settings.email_port,
            email_address=settings.email_address,
            password=settings.email_password,
            email_moves=email_moves
        )

        logger.info(f"Moved {moved_count} emails via IMAP")

    except Exception as e:
        logger.error(f"Error in bulk move: {e}")
        raise

    # Update database records
    actions = []
    for email_id in email_ids:
        email = db.query(Email).filter(Email.email_id == email_id).first()
        if email:
            from_folder = email.current_folder
            email.current_folder = target_folder
            email.last_updated = datetime.utcnow()

            action = EmailAction(
                email_id=email.id,
                action_type="moved",
                from_folder=from_folder,
                to_folder=target_folder,
                performed_by=performed_by,
                performed_at=datetime.utcnow(),
                reason=reason
            )
            db.add(action)
            actions.append(action)

    db.commit()

    logger.info(f"Bulk move complete: {len(actions)} actions logged")
    return actions


def bulk_delete_emails(
    db: Session,
    email_ids: List[str],
    performed_by: str,
    reason: Optional[str] = None
) -> List[EmailAction]:
    """
    Delete multiple emails.

    Args:
        db: Database session
        email_ids: List of email IDs to delete
        performed_by: Username performing the action
        reason: Optional reason

    Returns:
        List of EmailAction objects
    """
    logger.info(f"Bulk deleting {len(email_ids)} emails")

    # Execute deletes via IMAP
    try:
        if not IMAP_AVAILABLE:
            raise Exception("IMAP actions not available in cloud deployment")
        deleted_count = delete_emails(
            server=settings.email_server,
            port=settings.email_port,
            email_address=settings.email_address,
            password=settings.email_password,
            email_ids=email_ids
        )

        logger.info(f"Deleted {deleted_count} emails via IMAP")

    except Exception as e:
        logger.error(f"Error in bulk delete: {e}")
        raise

    # Update database records
    actions = []
    for email_id in email_ids:
        email = db.query(Email).filter(Email.email_id == email_id).first()
        if email:
            action = EmailAction(
                email_id=email.id,
                action_type="deleted",
                from_folder=email.current_folder,
                to_folder=None,
                performed_by=performed_by,
                performed_at=datetime.utcnow(),
                reason=reason
            )
            db.add(action)
            actions.append(action)

            # Mark as deleted
            email.current_folder = "DELETED"
            email.last_updated = datetime.utcnow()

    db.commit()

    logger.info(f"Bulk delete complete: {len(actions)} actions logged")
    return actions
