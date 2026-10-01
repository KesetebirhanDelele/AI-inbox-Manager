"""
Email fetching execution script.

This script connects to an email inbox via IMAP, fetches emails,
and converts them to the format expected by the classification system.

Design principles:
- Pure logic separated from I/O for testability
- Deterministic email parsing
- Comprehensive error handling
- Safe connection management
"""

import email
from email.message import Message
import imaplib
import logging
import os
import json
import re
import time
from datetime import datetime
from email.header import decode_header
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailFetchError(Exception):
    """Raised when email fetching fails."""
    pass


class EmailConnectionError(Exception):
    """Raised when connection to email server fails."""
    pass


class EmailConnectionLost(EmailFetchError):
    """The IMAP connection died mid-fetch (dropped socket, TLS EOF, timeout).

    Distinct from a per-message failure (bad/corrupt email): the *connection* is
    unusable, so every further command on it fails too. fetch_emails() reconnects
    and retries instead of skipping every remaining message.
    """
    pass


class FetchedEmails(list):
    """List of parsed emails, plus what went wrong while fetching them.

    Behaves exactly like the plain ``list`` fetch_emails() used to return, so
    existing callers are unaffected; the extra attributes let the pipeline notice
    a *partly failed* fetch instead of reporting it as a normal run.

    Attributes:
        skipped: UIDs that could not be fetched this run (any reason). They stay
            unread in Gmail and are retried by the next run.
        abandoned: subset of ``skipped`` given up on because the connection was
            lost and could not be re-established within the retry budget.
        reconnects: how many times the connection was re-established.
    """

    def __init__(self, *args, skipped: int = 0, abandoned: int = 0, reconnects: int = 0):
        super().__init__(*args)
        self.skipped = skipped
        self.abandoned = abandoned
        self.reconnects = reconnects


# Connection re-establishments allowed per fetch_emails() call, and the pause
# before each (seconds). A dropped Gmail IMAP session is normally fixed by one
# reconnect; the budget stops a truly unreachable server from looping forever.
_MAX_RECONNECTS = 3
_RECONNECT_BACKOFF_SECONDS = (2, 5, 10)


# ── Stable-identifier helpers ────────────────────────────────────────────────
#
# IMAP message-sequence numbers are position-based: they renumber on every
# expunge and are only valid inside the connection that read them.  The
# classify → move pipeline resolves a message in one connection and mutates it
# in a *later* one, minutes later, while a human works the same mailbox — so
# this module tracks messages by UID (stable across sessions and expunges) and,
# as a second line of defence, re-resolves a vanished UID via the RFC 5322
# Message-ID header before touching anything.
#
# Mutations use Gmail label operations (X-GM-LABELS) rather than
# COPY + \Deleted + EXPUNGE, so the organize path can never permanently destroy
# mail; the only hard delete (confirmed-spam purge) is scoped with UID EXPUNGE.


_MESSAGE_ID_RE = re.compile(r"Message-ID:\s*(<[^>]+>)", re.I)
_UID_RE = re.compile(r"\bUID\s+(\d+)")


def _quote_folder(folder: str) -> str:
    """IMAP-quote a mailbox name so names with spaces ('Spam Review') parse."""
    if len(folder) >= 2 and folder[0] == '"' and folder[-1] == '"':
        return folder
    return '"%s"' % folder.replace('"', '\\"')


def _gm_label_atom(label: str) -> str:
    """Render a label for an X-GM-LABELS list. System labels (\\Inbox) stay bare."""
    if label.startswith("\\"):
        return label
    return '"%s"' % label.replace('"', '\\"')


def _resolve_folder_uids(imap: "imaplib.IMAP4") -> Tuple[set, Dict[str, str]]:
    """
    Snapshot the currently-selected mailbox.

    Returns:
        (present_uids, message_id -> uid)  — both resolved live in this
        connection, so the identifiers are guaranteed current.
    """
    present: set = set()
    mid_to_uid: Dict[str, str] = {}

    status, data = imap.uid("SEARCH", None, "ALL")
    if status != "OK" or not data or not data[0]:
        return present, mid_to_uid

    uid_bytes = data[0].split()
    present = {u.decode() for u in uid_bytes}
    if not uid_bytes:
        return present, mid_to_uid

    status, fetched = imap.uid(
        "FETCH", b",".join(uid_bytes), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"
    )
    if status != "OK" or not fetched:
        return present, mid_to_uid

    for part in fetched:
        if not isinstance(part, tuple):
            continue
        meta = part[0].decode("ascii", "ignore") if part[0] else ""
        blob = part[1].decode("utf-8", "ignore") if part[1] else ""
        uid_match = _UID_RE.search(meta)
        mid_match = _MESSAGE_ID_RE.search(blob)
        if uid_match and mid_match:
            mid_to_uid[mid_match.group(1).strip()] = uid_match.group(1)

    return present, mid_to_uid


def _log_uidvalidity(imap: "imaplib.IMAP4", folder: str) -> None:
    """Log the folder's UIDVALIDITY so a (very rare) reset is visible in logs."""
    try:
        raw = imap.untagged_responses.get("UIDVALIDITY")
        if raw:
            logger.info(f"{folder} UIDVALIDITY={raw[0].decode() if isinstance(raw[0], bytes) else raw[0]}")
    except Exception:
        pass


def delete_emails(
    server: str,
    port: int,
    email_address: str,
    password: str,
    email_ids: List[str],
    folder: str = "INBOX",
    id_to_message_id: Optional[Dict[str, str]] = None,
) -> int:
    """
    Permanently delete emails from the server.

    Handles are UIDs (see module docstring).  Each is verified against the
    folder's live UID set — and, if missing, re-resolved via its Message-ID —
    before anything is flagged, so a stale handle can never purge the wrong
    message.  Deletion is scoped with UID EXPUNGE (RFC 4315): only the messages
    flagged here are expunged, never anything else in the folder.

    Args:
        server: IMAP server address
        port: IMAP port
        email_address: Email address
        password: Email password
        email_ids: UIDs of the messages to delete
        folder: Folder to delete from
        id_to_message_id: Optional {uid: message_id} for stale-handle recovery

    Returns:
        Number of emails successfully deleted
    """
    if not email_ids:
        return 0

    id_to_message_id = id_to_message_id or {}
    imap = None
    try:
        imap = connect_to_imap(server, port, email_address, password)

        status, _ = imap.select(_quote_folder(folder))  # writable
        if status != "OK":
            raise EmailFetchError(f"Cannot select folder {folder!r} for deletion")
        _log_uidvalidity(imap, folder)

        present, mid_to_uid = _resolve_folder_uids(imap)

        targets: List[str] = []
        for handle in email_ids:
            uid = str(handle)
            if uid not in present:
                mid = id_to_message_id.get(uid)
                recovered = mid_to_uid.get(mid) if mid else None
                if recovered:
                    logger.info(f"Delete: recovered UID {uid} -> {recovered} via Message-ID")
                    uid = recovered
                else:
                    logger.warning(
                        f"Delete: message {handle} not present in {folder!r} "
                        f"(already gone) — skipping"
                    )
                    continue
            targets.append(uid)

        if not targets:
            logger.info("Delete: nothing to do (no handles resolved)")
            return 0

        for uid in targets:
            imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")

        # UIDPLUS: expunge ONLY the UIDs we just flagged. Never a blind
        # expunge() — this mailbox is also worked by a human.
        try:
            typ, _ = imap.uid("EXPUNGE", ",".join(targets))
            if typ != "OK":
                raise imaplib.IMAP4.error(f"UID EXPUNGE returned {typ}")
        except imaplib.IMAP4.error as exc:
            logger.warning(
                f"UID EXPUNGE unavailable ({exc}) — falling back to "
                f"folder-scoped expunge() on {folder!r}"
            )
            imap.expunge()

        logger.info(f"Successfully deleted {len(targets)} email(s) from {folder!r}")
        return len(targets)

    except EmailFetchError:
        raise
    except Exception as e:
        logger.error(f"Email deletion failed: {e}")
        raise EmailFetchError(f"Failed to delete emails: {str(e)}")
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


def move_emails(
    server: str,
    port: int,
    email_address: str,
    password: str,
    email_moves: Dict[str, str],
    source_folder: str = "INBOX",
    id_to_message_id: Optional[Dict[str, str]] = None,
) -> int:
    """
    Organize emails by Gmail label, then remove them from the source folder.

    For each message this applies the destination label with
    ``STORE +X-GM-LABELS`` (Gmail auto-creates the label), then removes it from
    the source folder via ``STORE +FLAGS (\\Deleted)`` + a UID-scoped
    ``UID EXPUNGE`` (RFC 4315) on that folder.

    Gmail's IMAP treats ``\\Inbox`` (and other folder labels) as special: a
    plain ``STORE -X-GM-LABELS (\\Inbox)`` reports OK and drops it from the
    ``X-GM-LABELS`` FETCH response, but does *not* actually remove the message
    from Gmail's own ``in:inbox`` index — confirmed live via ``X-GM-RAW``
    search, which kept matching ``in:inbox`` for messages "moved" this way.
    Delete+expunge scoped to the source folder is Gmail's documented,
    actually-effective way to do this: since the expunge only ever targets
    this folder (never Trash or All Mail), it removes the folder's label
    rather than the message itself — any other label already applied (the
    destination category) keeps the message alive, just no longer in this
    folder. Still no COPY, no blind ``expunge()`` — only the specific UIDs
    flagged here are ever expunged, and only after the destination label is
    confirmed applied, so a partial failure just retries next run.

    Handles are UIDs (see module docstring); each is checked against the live
    UID set and, if missing, re-resolved via its Message-ID before any mutation.

    Args:
        email_moves: {uid: destination_label}
        source_folder: folder the messages currently live in (default INBOX)
        id_to_message_id: optional {uid: message_id} for stale-handle recovery

    Returns:
        Number of emails successfully organized.
    """
    if not email_moves:
        return 0

    id_to_message_id = id_to_message_id or {}

    imap = None
    try:
        imap = connect_to_imap(server, port, email_address, password)

        status, _ = imap.select(_quote_folder(source_folder))  # writable
        if status != "OK":
            raise EmailFetchError(f"Cannot select source folder {source_folder!r}")
        _log_uidvalidity(imap, source_folder)

        present, mid_to_uid = _resolve_folder_uids(imap)

        to_expunge: List[str] = []
        for handle, dest_folder in email_moves.items():
            uid = str(handle)

            if uid not in present:
                mid = id_to_message_id.get(uid)
                recovered = mid_to_uid.get(mid) if mid else None
                if recovered:
                    logger.info(f"Move: recovered UID {uid} -> {recovered} via Message-ID")
                    uid = recovered
                else:
                    logger.warning(
                        f"Move: message {handle} no longer in {source_folder!r} "
                        f"(already moved or deleted) — skipping"
                    )
                    continue

            # 1. Apply the destination label first (safe, reversible, auto-creates).
            s1, r1 = imap.uid("STORE", uid, "+X-GM-LABELS", f"({_gm_label_atom(dest_folder)})")
            if s1 != "OK":
                logger.error(f"Move: failed to label UID {uid} as {dest_folder!r}: {r1}")
                continue

            # 2. Flag for removal from the source folder — expunged as a batch below.
            s2, r2 = imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            if s2 != "OK":
                logger.error(
                    f"Move: labeled UID {uid} {dest_folder!r} but could not flag "
                    f"it \\Deleted in {source_folder!r}: {r2} — will retry next run"
                )
                continue

            to_expunge.append(uid)

        moved_count = 0
        if to_expunge:
            # UIDPLUS: expunge ONLY the UIDs just flagged. Never a blind
            # expunge() — this mailbox is also worked by a human.
            try:
                typ, resp = imap.uid("EXPUNGE", ",".join(to_expunge))
                if typ != "OK":
                    raise imaplib.IMAP4.error(f"UID EXPUNGE returned {typ}: {resp}")
                moved_count = len(to_expunge)
            except imaplib.IMAP4.error as exc:
                logger.error(
                    f"Move: labeled {len(to_expunge)} message(s) but UID EXPUNGE "
                    f"failed ({exc}) — they'll retry next run"
                )

        logger.info(f"Successfully moved {moved_count} of {len(email_moves)} email(s)")
        return moved_count

    except EmailFetchError:
        raise
    except Exception as e:
        logger.error(f"Email moving failed: {e}")
        raise EmailFetchError(f"Failed to move emails: {str(e)}")
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


def connect_to_imap(
    server: str,
    port: int,
    email_address: str,
    password: str,
    use_ssl: bool = True
) -> imaplib.IMAP4_SSL:
    """
    Connect to IMAP email server.

    Automatically uses OAuth2 (XOAUTH2) when config/gmail_token.json exists,
    falling back to password auth otherwise.

    Args:
        server: IMAP server address (e.g., imap.gmail.com)
        port: IMAP port (usually 993 for SSL)
        email_address: Email account address
        password: Account password or app-specific password (used if no OAuth2 token)
        use_ssl: Use SSL connection (recommended)

    Returns:
        Connected IMAP client

    Raises:
        EmailConnectionError: If connection or authentication fails
    """
    try:
        logger.info(f"Connecting to IMAP server: {server}:{port}")

        if use_ssl:
            imap = imaplib.IMAP4_SSL(server, port)
        else:
            imap = imaplib.IMAP4(server, port)

        # Use OAuth2 XOAUTH2 if token exists, else fall back to password
        token_path = Path(__file__).parent.parent / "config" / "gmail_token.json"
        if token_path.exists():
            try:
                from gmail_auth import get_access_token
                access_token = get_access_token()
                # XOAUTH2 string: "user=<email>\x01auth=Bearer <token>\x01\x01"
                auth_string = f"user={email_address}\x01auth=Bearer {access_token}\x01\x01"
                imap.authenticate("XOAUTH2", lambda _: auth_string.encode())
                logger.info(f"Authenticated via OAuth2 as: {email_address}")
            except Exception as oauth_err:
                logger.warning(f"OAuth2 failed, falling back to password: {oauth_err}")
                imap.login(email_address, password)
                logger.info(f"Authenticated via password as: {email_address}")
        else:
            logger.info(f"Authenticating via password as: {email_address}")
            imap.login(email_address, password)

        logger.info("Successfully connected and authenticated")
        return imap

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP authentication failed: {e}")
        raise EmailConnectionError(f"Authentication failed: {str(e)}")
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        raise EmailConnectionError(f"Connection failed: {str(e)}")


def select_folder(imap: imaplib.IMAP4_SSL, folder: str = "INBOX") -> int:
    """
    Select email folder to read from.

    Args:
        imap: Connected IMAP client
        folder: Folder name (default: INBOX)

    Returns:
        Number of messages in folder

    Raises:
        EmailFetchError: If folder selection fails
    """
    try:
        logger.info(f"Selecting folder: {folder}")
        # Quote so names with spaces ("Spam Review") don't trip the IMAP parser.
        status, messages = imap.select(_quote_folder(folder), readonly=True)

        if status != "OK":
            raise EmailFetchError(f"Failed to select folder: {folder}")

        message_count = int(messages[0])
        logger.info(f"Folder contains {message_count} messages")
        return message_count

    except Exception as e:
        logger.error(f"Folder selection failed: {e}")
        raise EmailFetchError(f"Failed to select folder: {str(e)}")


def search_emails(
    imap: imaplib.IMAP4_SSL,
    criteria: str = "UNSEEN",
    limit: Optional[int] = None,
    exclude_gm_labels: Optional[List[str]] = None,
    newest_first: bool = False,
) -> List[str]:
    """
    Search for emails matching criteria and return their **UIDs**.

    UIDs (not message-sequence numbers) are returned because they stay valid
    across IMAP sessions and are unaffected by expunges — the move step runs in
    a separate, later connection.

    Args:
        imap: Connected IMAP client
        criteria: IMAP search criteria (e.g., "UNSEEN", "ALL")
        limit: Maximum number of emails to return (None = all)
        exclude_gm_labels: Gmail labels to exclude, applied as
            ``NOT X-GM-LABELS <label>`` (e.g. ["InboxGenius-Processed"])
        newest_first: return highest UIDs first, so fresh mail is processed
            ahead of a backlog (default False keeps ascending order)

    Returns:
        List of UID strings matching criteria

    Raises:
        EmailFetchError: If search fails
    """
    try:
        terms: List[str] = [criteria]
        for label in (exclude_gm_labels or []):
            terms += ["NOT", "X-GM-LABELS", label]

        logger.info(f"Searching (UID) for emails: {' '.join(terms)}")
        status, messages = imap.uid("SEARCH", None, *terms)

        if status != "OK":
            raise EmailFetchError(f"Search failed with criteria: {' '.join(terms)}")

        uids = messages[0].split()
        if newest_first:
            uids = uids[::-1]

        if limit and len(uids) > limit:
            logger.info(f"Limiting results from {len(uids)} to {limit}")
            uids = uids[:limit]

        logger.info(f"Found {len(uids)} matching emails")
        return [uid.decode() for uid in uids]

    except EmailFetchError:
        raise
    except Exception as e:
        logger.error(f"Email search failed: {e}")
        raise EmailFetchError(f"Search failed: {str(e)}")


def decode_email_header(header_value: str) -> str:
    """
    Decode email header that may be encoded.

    Args:
        header_value: Header value (potentially encoded)

    Returns:
        Decoded string
    """
    if not header_value:
        return ""

    try:
        decoded_parts = decode_header(header_value)
        decoded_string = ""

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_string += part.decode(encoding or "utf-8", errors="ignore")
            else:
                decoded_string += str(part)

        return decoded_string.strip()
    except Exception as e:
        logger.warning(f"Failed to decode header '{header_value}': {e}")
        return str(header_value)


def extract_email_body(msg: Message) -> str:
    """
    Extract plain text body from email message.

    Args:
        msg: Parsed email message

    Returns:
        Email body as plain text
    """
    body = ""

    try:
        # Handle multipart emails
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                # Get plain text
                if content_type == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(charset, errors="ignore")
                    break
                # Fallback to HTML if no plain text
                elif content_type == "text/html" and not body:
                    charset = part.get_content_charset() or "utf-8"
                    html_body = part.get_payload(decode=True).decode(charset, errors="ignore")
                    # Simple HTML to text conversion (strip tags)
                    import re
                    body = re.sub('<[^<]+?>', '', html_body)
        else:
            # Single part message
            charset = msg.get_content_charset() or "utf-8"
            body = msg.get_payload(decode=True).decode(charset, errors="ignore")

        return body.strip()

    except Exception as e:
        logger.warning(f"Failed to extract email body: {e}")
        return ""


# Headers that can reveal which student's Gmail forwarded a message to the
# central inbox. Only these are kept; the full header block is never stored.
_RECIPIENT_HEADER_NAMES = (
    "Delivered-To", "X-Forwarded-To", "X-Original-To", "Envelope-To",
    "X-Delivered-To", "X-Forwarded-For", "X-Gm-Original-To",
)


def extract_recipient_headers(msg) -> Tuple[Dict[str, str], List[str]]:
    """
    Pull the recipient-related headers and To/Cc addresses from a parsed message.

    A forwarded message can carry several values for one header (for example one
    Delivered-To per hop), so every value is kept, joined by spaces, and
    resolve_student picks the first non-central address.

    Returns:
        (headers, to_addresses). Both are empty when nothing is present.
    """
    from email.utils import getaddresses

    headers: Dict[str, str] = {}
    for name in _RECIPIENT_HEADER_NAMES:
        values = msg.get_all(name) or []
        joined = " ".join(str(v) for v in values).strip()
        if joined:
            headers[name] = joined

    to_addresses = [
        addr.strip()
        for _, addr in getaddresses((msg.get_all("To") or []) + (msg.get_all("Cc") or []))
        if addr and addr.strip()
    ]
    return headers, to_addresses


def parse_email_message(raw_email: bytes, email_id: str) -> Dict[str, Any]:
    """
    Parse raw email into structured format.

    This is pure parsing logic - no I/O, easily testable.

    Args:
        raw_email: Raw email bytes from IMAP
        email_id: Unique email ID

    Returns:
        Dictionary with parsed email fields
    """
    try:
        # Parse email
        msg = email.message_from_bytes(raw_email)

        # Extract headers
        subject = decode_email_header(msg.get("Subject", ""))
        from_header = decode_email_header(msg.get("From", ""))
        date_header = msg.get("Date", "")

        # Parse sender email and name
        sender_email = ""
        sender_name = ""
        if from_header:
            # Format: "Name <email@example.com>" or "email@example.com"
            import re
            match = re.match(r'(.+?)\s*<(.+?)>', from_header)
            if match:
                sender_name = match.group(1).strip().strip('"')
                sender_email = match.group(2).strip()
            else:
                sender_email = from_header.strip()

        # Parse date
        email_date = ""
        if date_header:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_header)
                email_date = dt.isoformat()
            except Exception as e:
                logger.warning(f"Failed to parse date '{date_header}': {e}")
                email_date = date_header

        # Extract body
        body_content = extract_email_body(msg)
        recipient_headers, to_addresses = extract_recipient_headers(msg)

        return {
            "headers": recipient_headers,
            "to_addresses": to_addresses,
            "subject": subject,
            "sender_email": sender_email,
            "sender_name": sender_name,
            "email_date": email_date,
            "body_content": body_content,
            "email_id": email_id,
            "message_id": msg.get("Message-ID", ""),
        }

    except Exception as e:
        logger.error(f"Failed to parse email {email_id}: {e}")
        raise EmailFetchError(f"Email parsing failed: {str(e)}")


def fetch_email_by_uid(imap: imaplib.IMAP4_SSL, uid: str) -> bytes:
    """
    Fetch raw email content by UID.

    Args:
        imap: Connected IMAP client
        uid: Message UID to fetch

    Returns:
        Raw email bytes

    Raises:
        EmailFetchError: If fetch fails
    """
    try:
        status, msg_data = imap.uid("FETCH", str(uid), "(RFC822)")

        if status != "OK" or not msg_data or msg_data[0] is None:
            raise EmailFetchError(f"Failed to fetch email UID {uid}")

        raw_email = msg_data[0][1]
        return raw_email

    except EmailFetchError:
        raise
    except (imaplib.IMAP4.abort, EOFError, OSError) as e:
        # OSError covers socket.error, ssl.SSLError ("EOF occurred in violation
        # of protocol"), timeouts and connection resets: the connection is dead,
        # not this one message.
        logger.error(f"IMAP connection lost while fetching UID {uid}: {e}")
        raise EmailConnectionLost(f"Fetch failed: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to fetch email UID {uid}: {e}")
        raise EmailFetchError(f"Fetch failed: {str(e)}")


def fetch_email_by_id(imap: imaplib.IMAP4_SSL, email_id: str) -> bytes:
    """Deprecated alias for :func:`fetch_email_by_uid` (handles are UIDs now)."""
    return fetch_email_by_uid(imap, email_id)


def fetch_emails(
    server: str,
    port: int,
    email_address: str,
    password: str,
    folder: str = "INBOX",
    criteria: str = "UNSEEN",
    limit: Optional[int] = None,
    mark_as_read: bool = False,
    exclude_gm_labels: Optional[List[str]] = None,
    newest_first: bool = False,
) -> List[Dict[str, Any]]:
    """
    Main function to fetch and parse emails from inbox.

    Args:
        server: IMAP server address
        port: IMAP port
        email_address: Email account address
        password: Account password
        folder: Folder to fetch from (default: INBOX)
        criteria: Search criteria (default: UNSEEN)
        limit: Maximum emails to fetch (None = all)
        mark_as_read: Mark emails as read after fetching
        exclude_gm_labels: Gmail labels to exclude from the search
        newest_first: process the newest mail first (default False)

    Returns:
        A :class:`FetchedEmails` (a ``list``) of parsed email dictionaries.
        ``email_id`` holds the message UID. Its ``skipped`` / ``abandoned`` /
        ``reconnects`` attributes report partial failures (see FetchedEmails).

    Raises:
        EmailConnectionError: If connection fails
        EmailFetchError: If fetching/parsing fails

    If the IMAP connection drops mid-fetch (Gmail closes long or busy sessions;
    seen 2026-09-29 as ``socket error: EOF`` on every remaining UID), the
    connection is re-established and the same UID retried, up to
    ``_MAX_RECONNECTS`` times. UIDs are stable across sessions, so resuming is
    safe. Anything still unfetched stays unread in Gmail for the next run.
    """
    imap = None
    try:
        # Connect to server
        imap = connect_to_imap(server, port, email_address, password)

        # Select folder
        select_folder(imap, folder)

        # Search for emails (returns UIDs)
        uids = search_emails(
            imap, criteria, limit,
            exclude_gm_labels=exclude_gm_labels,
            newest_first=newest_first,
        )

        if not uids:
            logger.info("No emails found matching criteria")
            return FetchedEmails()

        # Fetch and parse each email
        emails = FetchedEmails()
        i = 0
        while i < len(uids):
            uid = uids[i]
            try:
                logger.info(f"Fetching email UID {uid}")
                raw_email = fetch_email_by_uid(imap, uid)
                parsed_email = parse_email_message(raw_email, uid)
                emails.append(parsed_email)

                # Mark as read if requested
                if mark_as_read:
                    imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")
                    logger.info(f"Marked email UID {uid} as read")

                i += 1

            except EmailConnectionLost as e:
                remaining = len(uids) - i
                if emails.reconnects >= _MAX_RECONNECTS:
                    logger.error(
                        f"IMAP connection lost and reconnect budget "
                        f"({_MAX_RECONNECTS}) exhausted; abandoning {remaining} "
                        f"unfetched email(s) — they stay unread for the next run"
                    )
                    emails.skipped += remaining
                    emails.abandoned += remaining
                    break

                delay = _RECONNECT_BACKOFF_SECONDS[
                    min(emails.reconnects, len(_RECONNECT_BACKOFF_SECONDS) - 1)
                ]
                emails.reconnects += 1
                logger.warning(
                    f"IMAP connection lost at UID {uid} ({e}); reconnecting in "
                    f"{delay}s (attempt {emails.reconnects}/{_MAX_RECONNECTS})"
                )
                time.sleep(delay)
                try:
                    try:
                        imap.logout()
                    except Exception:
                        pass  # the old connection is already dead
                    imap = connect_to_imap(server, port, email_address, password)
                    select_folder(imap, folder)
                except (EmailConnectionError, EmailFetchError) as re_err:
                    logger.error(
                        f"Reconnect failed ({re_err}); abandoning {remaining} "
                        f"unfetched email(s) — they stay unread for the next run"
                    )
                    emails.skipped += remaining
                    emails.abandoned += remaining
                    break
                # loop again on the SAME uid (i unchanged)

            except EmailFetchError as e:
                logger.error(f"Skipping email UID {uid}: {e}")
                emails.skipped += 1
                i += 1

        logger.info(
            f"Successfully fetched {len(emails)} emails "
            f"(skipped={emails.skipped}, reconnects={emails.reconnects})"
        )
        return emails

    finally:
        # Always close connection
        if imap:
            try:
                imap.close()
                imap.logout()
                logger.info("IMAP connection closed")
            except:
                pass


def save_emails_to_file(emails: List[Dict[str, Any]], output_path: Path) -> None:
    """
    Save fetched emails to JSON file.

    Args:
        emails: List of parsed email dictionaries
        output_path: Path to save JSON file
    """
    logger.info(f"Saving {len(emails)} emails to {output_path}")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(emails, f, indent=2, ensure_ascii=False)

    logger.info("Emails saved successfully")


def main() -> None:
    """
    CLI entry point for email fetching.

    Usage:
        python fetch_emails.py <output_file> [--mark-read] [--limit N]
    """
    import sys

    if len(sys.argv) < 2:
        print("Usage: python fetch_emails.py <output_file> [--mark-read] [--limit N]")
        print("\nFetches emails from configured inbox and saves to JSON file.")
        print("\nOptions:")
        print("  --mark-read    Mark fetched emails as read")
        print("  --limit N      Fetch maximum N emails")
        sys.exit(1)

    output_file = Path(sys.argv[1])
    mark_as_read = "--mark-read" in sys.argv

    # Parse limit
    limit = None
    if "--limit" in sys.argv:
        try:
            limit_index = sys.argv.index("--limit")
            limit = int(sys.argv[limit_index + 1])
        except (IndexError, ValueError):
            print("Error: --limit requires a number")
            sys.exit(1)

    # Load configuration from environment
    server = os.getenv("EMAIL_SERVER")
    port = int(os.getenv("EMAIL_PORT", "993"))
    email_address = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")
    folder = os.getenv("EMAIL_FOLDER", "INBOX")
    criteria = os.getenv("EMAIL_SEARCH_CRITERIA", "UNSEEN")

    if not all([server, email_address, password]):
        print("Error: Missing required environment variables:")
        print("  EMAIL_SERVER")
        print("  EMAIL_ADDRESS")
        print("  EMAIL_PASSWORD")
        print("\nSet these in your .env file")
        sys.exit(1)

    try:
        # Fetch emails
        print(f"\nFetching emails from {email_address}...")
        print(f"Server: {server}:{port}")
        print(f"Folder: {folder}")
        print(f"Criteria: {criteria}")
        if limit:
            print(f"Limit: {limit} emails")

        emails = fetch_emails(
            server=server,
            port=port,
            email_address=email_address,
            password=password,
            folder=folder,
            criteria=criteria,
            limit=limit,
            mark_as_read=mark_as_read
        )

        # Save to file
        save_emails_to_file(emails, output_file)

        # Report results
        print(f"\nFetch complete:")
        print(f"  Emails fetched: {len(emails)}")
        print(f"  Saved to: {output_file}")
        if mark_as_read:
            print(f"  Marked as read: Yes")

        sys.exit(0)

    except EmailConnectionError as e:
        logger.error(f"Connection failed: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        print("\nCheck your email credentials and server settings")
        sys.exit(2)

    except EmailFetchError as e:
        logger.error(f"Fetch failed: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(2)

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
