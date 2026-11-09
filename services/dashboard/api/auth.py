"""
Authentication and session management.

Handles password hashing, session token generation, and
session validation for API endpoints.
"""

import uuid
import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status, Depends, Cookie
from fastapi.security import HTTPBearer

from models import UserSession
from database import get_db
from config import settings

security = HTTPBearer()


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Bcrypt hash string
    """
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)  # Cost factor 12
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Bcrypt hash to verify against

    Returns:
        True if password matches, False otherwise
    """
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_session(username: str, db: Session, role: str = "stakeholder", hours: Optional[int] = None) -> dict:
    """
    Create a new user session.

    Args:
        username: Username for the session
        db: Database session

    Returns:
        Dictionary with session_token and expires_at
    """
    # Generate UUID session token
    session_token = str(uuid.uuid4())

    # Calculate expiration time
    expires_at = datetime.utcnow() + timedelta(hours=hours or settings.session_expiry_hours)

    # Create session record
    session = UserSession(
        session_token=session_token,
        username=username,
        role=role,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
        last_activity=datetime.utcnow()
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "session_token": session_token,
        "expires_at": expires_at.isoformat()
    }


def get_session_by_token(session_token: str, db: Session) -> Optional[UserSession]:
    """
    Retrieve a session by its token.

    Args:
        session_token: Session token to look up
        db: Database session

    Returns:
        UserSession object if found and valid, None otherwise
    """
    session = db.query(UserSession).filter(
        UserSession.session_token == session_token
    ).first()

    if not session:
        return None

    # Check if expired
    if session.expires_at < datetime.utcnow():
        db.delete(session)
        db.commit()
        return None

    # Update last activity
    session.last_activity = datetime.utcnow()
    db.commit()

    return session


def invalidate_session(session_token: str, db: Session) -> bool:
    """
    Invalidate (delete) a session.

    Args:
        session_token: Session token to invalidate
        db: Database session

    Returns:
        True if session was found and deleted, False otherwise
    """
    session = db.query(UserSession).filter(
        UserSession.session_token == session_token
    ).first()

    if session:
        db.delete(session)
        db.commit()
        return True

    return False


def get_current_user(
    session_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
) -> UserSession:
    """
    Dependency function to get the current authenticated user.

    This function is used as a FastAPI dependency to protect endpoints.
    It validates the session token from the cookie and returns the user session.

    Usage:
        @app.get("/protected")
        def protected_route(user: UserSession = Depends(get_current_user)):
            return {"message": f"Hello {user.username}"}

    Args:
        session_token: Session token from HTTP-only cookie
        db: Database session

    Returns:
        UserSession object

    Raises:
        HTTPException: If not authenticated or session expired
    """
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    session = get_session_by_token(session_token, db)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session"
        )

    return session


def cleanup_expired_sessions(db: Session) -> int:
    """
    Remove expired sessions from the database.

    This should be called periodically (e.g., daily cron job) to
    prevent the sessions table from growing unbounded.

    Args:
        db: Database session

    Returns:
        Number of sessions deleted
    """
    now = datetime.utcnow()
    expired = db.query(UserSession).filter(UserSession.expires_at < now).all()
    count = len(expired)

    for session in expired:
        db.delete(session)

    db.commit()
    return count
