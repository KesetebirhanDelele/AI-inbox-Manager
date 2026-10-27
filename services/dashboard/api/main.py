"""
FastAPI application entry point for the Email Management Dashboard.

This is the main application file that sets up the FastAPI app,
configures middleware, registers routers, and defines core endpoints.
"""

from fastapi import FastAPI, Depends, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
import logging

from config import settings
from database import get_db, init_db
from auth import hash_password, verify_password, create_session, invalidate_session, get_current_user
from models import UserSession

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="API for managing and approving email classifications",
    version="1.0.0",
    debug=settings.debug
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models for request/response
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    message: str
    username: str


class HealthResponse(BaseModel):
    status: str
    environment: str
    database: str


# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize database on application startup."""
    logger.info("Starting Email Management Dashboard API")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"CORS Origins: {settings.cors_origins}")

    # Initialize database tables
    init_db()
    logger.info("Database tables initialized")


# Health check endpoint
@app.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint.

    Returns application status and verifies database connectivity.
    """
    try:
        # Test database connection
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "disconnected"

    return {
        "status": "healthy",
        "environment": settings.environment,
        "database": db_status
    }


# Authentication endpoints
@app.post("/api/auth/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Login endpoint.

    Validates username/password and creates a session.
    Sets an HTTP-only session cookie on success.

    Args:
        request: Login credentials
        response: FastAPI response object (to set cookie)
        db: Database session

    Returns:
        Login success message with username

    Raises:
        HTTPException: If credentials are invalid
    """
    # For MVP, we use a simple username/password check
    # In production, this would check against a users table
    # For now, we'll use a hardcoded admin password (set via env var)

    if not settings.admin_password_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication not configured. Set ADMIN_PASSWORD_HASH in .env"
        )

    # Determine role based on which password matches
    # Strip whitespace in case env var was line-wrapped by hosting provider
    admin_hash = settings.admin_password_hash.strip()
    stakeholder_hash = settings.stakeholder_password_hash.strip() if settings.stakeholder_password_hash else None
    role = None
    if verify_password(request.password, admin_hash):
        role = "admin"
    elif stakeholder_hash and verify_password(request.password, stakeholder_hash):
        role = "stakeholder"

    if role is None:
        logger.warning(f"Failed login attempt for user: {request.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # Create session
    session_data = create_session(request.username, db, role=role)

    # Set HTTP-only session cookie
    response.set_cookie(
        key="session_token",
        value=session_data["session_token"],
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.session_expiry_hours * 3600
    )

    logger.info(f"User {request.username} logged in successfully")

    return {
        "message": "Login successful",
        "username": request.username
    }


@app.post("/api/auth/logout")
async def logout(
    response: Response,
    user: UserSession = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Logout endpoint.

    Invalidates the current session and clears the session cookie.

    Args:
        response: FastAPI response object (to clear cookie)
        user: Current user session (from dependency)
        db: Database session

    Returns:
        Logout success message
    """
    # Invalidate session
    invalidate_session(user.session_token, db)

    # Clear session cookie
    response.delete_cookie(key="session_token")

    logger.info(f"User {user.username} logged out")

    return {"message": "Logout successful"}


@app.get("/api/auth/me")
async def get_current_user_info(user: UserSession = Depends(get_current_user)):
    """
    Get current user information.

    Returns information about the currently authenticated user.

    Args:
        user: Current user session (from dependency)

    Returns:
        User information including username and session expiry
    """
    return {
        "username": user.username,
        "role": getattr(user, "role", "stakeholder"),
        "session_created": user.created_at.isoformat(),
        "session_expires": user.expires_at.isoformat(),
        "last_activity": user.last_activity.isoformat()
    }


# Protected test endpoint
@app.get("/api/test/protected")
async def protected_test(user: UserSession = Depends(get_current_user)):
    """
    Test endpoint that requires authentication.

    Used to verify authentication is working correctly.

    Args:
        user: Current user session (from dependency)

    Returns:
        Test message with username
    """
    return {
        "message": f"Hello {user.username}, you are authenticated!",
        "username": user.username
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# Import routers
from routers import approvals, inbox, stats, whitelist, emails, interviews, notifications, checklist, schedule, role_settings, callback_requests, approval_links, gate_review

# Register routers
app.include_router(approvals.router, prefix="/api/approvals", tags=["approvals"])
app.include_router(inbox.router, prefix="/api/inbox", tags=["inbox"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(whitelist.router, prefix="/api/whitelist", tags=["whitelist"])
app.include_router(emails.router, prefix="/api/emails", tags=["emails"])
app.include_router(interviews.router, prefix="/api/interviews", tags=["interviews"])
app.include_router(role_settings.router, prefix="/api/roles", tags=["roles"])
app.include_router(callback_requests.router, prefix="/api/callbacks", tags=["callbacks"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(approval_links.router, prefix="/api/approve-links", tags=["approve-links"])   # no login: the token in the emailed link is the key
app.include_router(gate_review.router, prefix="/api/interview-gate", tags=["interview-gate"])
app.include_router(checklist.router, prefix="/api/checklist", tags=["checklist"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["schedule"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
