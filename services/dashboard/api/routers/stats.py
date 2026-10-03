"""
Statistics and metrics API endpoints.

Provides processing statistics, trends, and accuracy metrics.
"""

import logging
import os
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, select
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_CENTRAL = ZoneInfo("America/Chicago")


def _today_start_utc() -> datetime:
    """Return midnight Central Time today as a naive UTC datetime for DB queries."""
    now_central = datetime.now(_CENTRAL)
    midnight_central = now_central.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_central.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

from database import get_db
from utils_text import clean_preview
from auth import get_current_user
from models import ProcessRun, Classification, Approval, Email, UserSession, InterviewEvent, Student, NotificationDraft
from integration.process_runner import run_email_processing, get_run_lock_status

router = APIRouter()

# Neon's free tier (0.5 GB) is the historical default, so the Render/Neon
# deployment behaves exactly as before. On the Hetzner server set
# DB_STORAGE_CAP_MB in the root .env to the disk budget for Postgres.
DEFAULT_DB_STORAGE_CAP_MB = 512


def _db_storage_cap_bytes() -> int:
    """Storage cap for the countdown card, from DB_STORAGE_CAP_MB.

    Unset, blank, non-numeric or non-positive values fall back to the default
    rather than raising -- a bad env var must never break the KPI endpoint.
    """
    raw = os.getenv("DB_STORAGE_CAP_MB", "").strip()
    try:
        cap_mb = float(raw) if raw else DEFAULT_DB_STORAGE_CAP_MB
    except ValueError:
        cap_mb = DEFAULT_DB_STORAGE_CAP_MB
    if cap_mb <= 0:
        cap_mb = DEFAULT_DB_STORAGE_CAP_MB
    return int(cap_mb * 1024 * 1024)


# Pydantic models
class SummaryStats(BaseModel):
    today_total_emails: int
    today_interview_requests: int
    total_interview_requests: int
    today_organized: int
    today_spam_deleted: int
    week_total_emails: int
    week_interview_requests: int
    last_run_timestamp: Optional[datetime]
    pending_approvals: int
    inbox_count: int
    yesterday_total_emails: int = 0


class CategoryBreakdown(BaseModel):
    category: str
    count: int


class AccuracyMetrics(BaseModel):
    total_approvals: int
    approved: int
    overridden: int
    rejected: int
    override_rate: float
    avg_confidence: float
    low_confidence_count: int


class EngineeringKPIs(BaseModel):
    ai_cost_today_usd: float
    avg_duration_seconds_7d: Optional[float]
    failure_rate_7d: float       # 0.0–100.0 percent
    run_count_7d: int
    failed_run_count_7d: int
    # Database size vs a configurable cap (DB_STORAGE_CAP_MB; default 512 = Neon's
    # free tier, which blocks new writes once full — see RUNBOOK.md §4b/§4c). These
    # are None on non-Postgres DBs (e.g. local SQLite dev fallback). (A
    # "days until full" estimate used to live here; removed 2026-09-29.)
    db_storage_used_bytes: Optional[int] = None
    db_storage_cap_bytes: Optional[int] = None
    db_storage_pct: Optional[float] = None


@router.get("/summary", response_model=SummaryStats)
async def get_summary_stats(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get summary statistics for the dashboard home page.

    Returns real-time stats aggregated from ProcessRun records (written after every scheduled run).
    """
    now = datetime.utcnow()
    today_start = _today_start_utc()
    yesterday_start = today_start - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    # Aggregate today's stats from ProcessRun records (always populated by processing script)
    today_runs = db.query(ProcessRun).filter(
        ProcessRun.run_timestamp >= today_start
    ).all()

    yesterday_runs = db.query(ProcessRun).filter(
        ProcessRun.run_timestamp >= yesterday_start,
        ProcessRun.run_timestamp < today_start
    ).all()
    yesterday_total = sum(r.total_emails for r in yesterday_runs)

    today_total = sum(r.total_emails for r in today_runs)
    today_organized = sum(r.organized for r in today_runs)
    today_spam = sum(r.spam_deleted for r in today_runs)

    # Use actual email/classification table for interview counts (prevents double-counting
    # caused by unread interview emails being re-processed on every run)
    today_interview = db.query(Email).join(
        Classification, Email.id == Classification.email_id
    ).filter(
        Classification.category == "Interview Request",
        Email.fetch_timestamp >= today_start
    ).count()

    # Total interview requests (all time) — used for dashboard card
    total_interview = db.query(Email).join(
        Classification, Email.id == Classification.email_id
    ).filter(
        Classification.category == "Interview Request"
    ).count()

    # Week stats from ProcessRun records
    week_runs = db.query(ProcessRun).filter(
        ProcessRun.run_timestamp >= week_ago
    ).all()

    week_total = sum(r.total_emails for r in week_runs)

    # Use actual email table for week interview count too
    week_interview = db.query(Email).join(
        Classification, Email.id == Classification.email_id
    ).filter(
        Classification.category == "Interview Request",
        Email.fetch_timestamp >= week_ago
    ).count()

    # Last run (still from ProcessRun for countdown timer)
    last_run = db.query(ProcessRun).order_by(
        ProcessRun.run_timestamp.desc()
    ).first()

    # Pending approvals
    pending = db.query(Approval).filter(
        Approval.status == "pending"
    ).count()

    # Current inbox count
    inbox_count = db.query(Email).filter(
        Email.current_folder == "INBOX"
    ).count()

    result = SummaryStats(
        today_total_emails=today_total,
        today_interview_requests=today_interview,
        total_interview_requests=total_interview,
        today_organized=today_organized,
        today_spam_deleted=today_spam,
        week_total_emails=week_total,
        week_interview_requests=week_interview,
        last_run_timestamp=last_run.run_timestamp if last_run else None,
        pending_approvals=pending,
        inbox_count=inbox_count,
        yesterday_total_emails=yesterday_total,
    )

    return result


@router.get("/categories", response_model=List[CategoryBreakdown])
async def get_category_breakdown(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get category breakdown over a time period.

    Aggregates category counts from ProcessRun.categories_breakdown JSON field.

    Args:
        start_date: Start date for filtering (defaults to 7 days ago)
        end_date: End date for filtering (defaults to now)

    Returns:
        List of categories with counts
    """
    # Parse dates
    if start_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")
    else:
        start = datetime.utcnow() - timedelta(days=60)

    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end = datetime.utcnow()

    # Aggregate from ProcessRun.categories_breakdown JSON
    runs = db.query(ProcessRun).filter(
        and_(
            ProcessRun.run_timestamp >= start,
            ProcessRun.run_timestamp <= end
        )
    ).all()

    EXCLUDED_CATEGORIES = {'Job Alert', 'Application Notification'}

    aggregated: Dict[str, int] = {}
    for run in runs:
        breakdown = run.categories_breakdown or {}
        for category, count in breakdown.items():
            if category in EXCLUDED_CATEGORIES:
                continue
            aggregated[category] = aggregated.get(category, 0) + int(count)

    return [
        CategoryBreakdown(category=cat, count=count)
        for cat, count in sorted(aggregated.items(), key=lambda x: -x[1])
    ]


@router.get("/accuracy", response_model=AccuracyMetrics)
async def get_accuracy_metrics(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get accuracy and approval metrics.

    Returns:
        Metrics about approval override rate, confidence distribution, etc.
    """
    # Total approvals
    total = db.query(Approval).count()

    # Breakdown by status
    approved = db.query(Approval).filter(Approval.status == "approved").count()
    overridden = db.query(Approval).filter(Approval.status == "overridden").count()
    rejected = db.query(Approval).filter(Approval.status == "rejected").count()

    # Override rate
    override_rate = (overridden / total) if total > 0 else 0.0

    # Average confidence
    avg_conf = db.query(
        func.avg(Classification.confidence)
    ).scalar() or 0.0

    # Low confidence count (< 0.70)
    low_conf = db.query(Classification).filter(
        Classification.confidence < 0.70
    ).count()

    return AccuracyMetrics(
        total_approvals=total,
        approved=approved,
        overridden=overridden,
        rejected=rejected,
        override_rate=override_rate,
        avg_confidence=float(avg_conf),
        low_confidence_count=low_conf
    )


@router.get("/engineering-kpis", response_model=EngineeringKPIs)
async def get_engineering_kpis(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Engineering-level KPIs for operational health monitoring.

    Returns:
        - AI cost incurred today (USD)
        - Average processing duration over the last 7 days (seconds)
        - Failure rate over the last 7 days (%)
    """
    now = datetime.utcnow()
    today_start = _today_start_utc()
    week_ago = now - timedelta(days=7)

    # AI Cost Today — sum gpt_cost_usd for all runs since midnight Central Time
    today_runs = db.query(ProcessRun).filter(
        ProcessRun.run_timestamp >= today_start
    ).all()
    ai_cost_today = sum(r.gpt_cost_usd or 0.0 for r in today_runs)

    # 7-day window for duration + failure rate
    week_runs = db.query(ProcessRun).filter(
        ProcessRun.run_timestamp >= week_ago
    ).all()

    run_count = len(week_runs)
    failed_count = sum(1 for r in week_runs if r.status != "success")
    failure_rate = (failed_count / run_count * 100.0) if run_count > 0 else 0.0

    durations = [
        r.duration_seconds for r in week_runs
        if r.duration_seconds is not None and r.duration_seconds > 0
    ]
    avg_duration = (sum(durations) / len(durations)) if durations else None

    # Database storage — Postgres only, best-effort (never let a monitoring
    # query break the KPI endpoint). Cap comes from DB_STORAGE_CAP_MB.
    storage_used = storage_cap = storage_pct = None
    try:
        if db.bind.dialect.name == "postgresql":
            storage_used = db.execute(
                select(func.pg_database_size(func.current_database()))
            ).scalar()
            storage_cap = _db_storage_cap_bytes()
            storage_pct = round(storage_used / storage_cap * 100.0, 2)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Could not compute DB storage KPIs: {e}")

    return EngineeringKPIs(
        ai_cost_today_usd=round(ai_cost_today, 4),
        avg_duration_seconds_7d=round(avg_duration, 1) if avg_duration is not None else None,
        failure_rate_7d=round(failure_rate, 1),
        run_count_7d=run_count,
        failed_run_count_7d=failed_count,
        db_storage_used_bytes=storage_used,
        db_storage_cap_bytes=storage_cap,
        db_storage_pct=storage_pct,
    )


@router.get("/processing-runs")
async def get_processing_runs(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get recent processing runs.

    Args:
        limit: Number of runs to return (1-100)

    Returns:
        List of recent ProcessRun objects
    """
    runs = db.query(ProcessRun).order_by(
        ProcessRun.run_timestamp.desc()
    ).limit(limit).all()

    return [
        {
            "id": run.id,
            "run_timestamp": run.run_timestamp.isoformat() + 'Z',  # Add Z to indicate UTC
            "total_emails": run.total_emails,
            "interview_requests": run.interview_requests,
            "organized": run.organized,
            "spam_deleted": run.spam_deleted,
            "categories_breakdown": run.categories_breakdown,
            "duration_seconds": run.duration_seconds,
            "status": run.status
        }
        for run in runs
    ]


@router.get("/offers")
async def get_offers(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """Return emails classified as Offer, most recent first."""
    rows = (
        db.query(Email, Classification)
        .join(Classification, Email.id == Classification.email_id)
        .filter(Classification.category == "Offer")
        .order_by(Classification.classification_timestamp.desc())
        .limit(limit)
        .all()
    )
    result = []
    for email, cls in rows:
        result.append({
            "id": email.id,
            "subject": email.subject,
            "from_address": email.from_address,
            "received_date": email.received_date.isoformat() + "Z",
            "body_preview": clean_preview(email.body_preview, email.full_body),
            "company_name": cls.company_name,
            "position": cls.position,
            "confidence": cls.confidence,
            "current_folder": email.current_folder,
        })
    return result


@router.get("/today-emails")
async def get_today_emails(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """Return all emails classified today (Central Time), most recent first.

    Uses classification_timestamp (not fetch_timestamp) so re-processed emails
    are included even if they were first fetched on a previous day.
    Deduplicates to the latest classification per email.
    """
    today_start = _today_start_utc()

    # Subquery: latest classification id per email classified today
    subq = (
        db.query(
            Classification.email_id,
            func.max(Classification.id).label("max_cls_id")
        )
        .filter(Classification.classification_timestamp >= today_start)
        .group_by(Classification.email_id)
        .subquery()
    )

    rows = (
        db.query(Email, Classification)
        .join(subq, Email.id == subq.c.email_id)
        .join(Classification, Classification.id == subq.c.max_cls_id)
        .order_by(Classification.classification_timestamp.desc())
        .all()
    )

    result = []
    for email, cls in rows:
        result.append({
            "id": email.id,
            "subject": email.subject,
            "from_address": email.from_address,
            "received_date": email.received_date.isoformat() + "Z" if email.received_date else None,
            "fetch_timestamp": cls.classification_timestamp.isoformat() + "Z" if cls.classification_timestamp else None,
            "category": cls.category,
            "company_name": cls.company_name,
            "confidence": cls.confidence,
            "current_folder": email.current_folder,
        })
    return result


@router.get("/hourly-volume")
async def get_hourly_volume(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """Email volume by hour of day (last 30 days, Central Time)."""
    since = datetime.utcnow() - timedelta(days=30)
    rows = db.query(
        func.extract('hour', Classification.classification_timestamp).label('hour'),
        func.count(Classification.id).label('count')
    ).filter(
        Classification.classification_timestamp >= since
    ).group_by('hour').order_by('hour').all()

    hourly = {int(r.hour): r.count for r in rows}
    return [{"hour": h, "count": hourly.get(h, 0)} for h in range(24)]


@router.get("/rejection-trend")
async def get_rejection_trend(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """Daily rejection counts over last 30 days."""
    since = datetime.utcnow() - timedelta(days=30)
    rows = db.query(
        func.date(Classification.classification_timestamp).label('date'),
        func.count(Classification.id).label('count')
    ).filter(
        Classification.category == 'Rejection',
        Classification.classification_timestamp >= since
    ).group_by(func.date(Classification.classification_timestamp)).order_by('date').all()

    return [{"date": str(r.date), "count": r.count} for r in rows]


@router.get("/trends")
async def get_trends(
    days: int = Query(30, ge=1, le=90, description="Number of days to analyze"),
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get email processing trends over time.

    Args:
        days: Number of days to analyze (1-30)

    Returns:
        Daily statistics for the specified period
    """
    start_date = datetime.utcnow() - timedelta(days=days)

    runs = db.query(ProcessRun).filter(
        ProcessRun.run_timestamp >= start_date
    ).order_by(
        ProcessRun.run_timestamp.asc()
    ).all()

    # Group by date
    daily_stats = {}
    for run in runs:
        date_key = run.run_timestamp.date().isoformat()
        if date_key not in daily_stats:
            daily_stats[date_key] = {
                "date": date_key,
                "total_emails": 0,
                "interview_requests": 0,
                "organized": 0,
                "spam_deleted": 0,
                "run_count": 0
            }

        daily_stats[date_key]["total_emails"] += run.total_emails
        daily_stats[date_key]["interview_requests"] += run.interview_requests
        daily_stats[date_key]["organized"] += run.organized
        daily_stats[date_key]["spam_deleted"] += run.spam_deleted
        daily_stats[date_key]["run_count"] += 1

    return {"trends": list(daily_stats.values())}


@router.get("/student-activity")
async def get_student_activity(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """Student activity: interview counts, notification status per student."""
    from sqlalchemy import case
    results = db.query(
        Student.id,
        Student.full_name,
        Student.personal_email,
        Student.is_active,
        func.count(InterviewEvent.id).label("total_interviews"),
        func.sum(case((NotificationDraft.email_status == "sent", 1), else_=0)).label("notified"),
        func.max(InterviewEvent.created_at).label("last_interview_at"),
    ).outerjoin(
        InterviewEvent, InterviewEvent.student_id == Student.id
    ).outerjoin(
        NotificationDraft, NotificationDraft.interview_event_id == InterviewEvent.id
    ).group_by(Student.id).order_by(func.count(InterviewEvent.id).desc()).all()

    return [
        {
            "student_id": r.id,
            "student_name": r.full_name or "Unknown",
            "personal_email": r.personal_email,
            "is_active": r.is_active,
            "total_interviews": r.total_interviews or 0,
            "notified": r.notified or 0,
            "not_notified": (r.total_interviews or 0) - (r.notified or 0),
            "last_interview_at": r.last_interview_at.isoformat() if r.last_interview_at else None,
        }
        for r in results
    ]


@router.get("/company-tracker")
async def get_company_tracker(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """Top companies/recruiters reaching out with interview requests."""
    results = db.query(
        Classification.company_name,
        func.count(Classification.id).label("total"),
        func.max(Email.received_date).label("last_seen"),
    ).join(
        Email, Email.id == Classification.email_id
    ).filter(
        Classification.category == "Interview Request",
        Classification.company_name != None,
        Classification.company_name != "",
    ).group_by(Classification.company_name).order_by(func.count(Classification.id).desc()).limit(50).all()

    return [
        {
            "company_name": r.company_name,
            "total_requests": r.total,
            "last_seen": r.last_seen.isoformat() + "Z" if r.last_seen else None,
        }
        for r in results
    ]


@router.get("/missed-interviews")
async def get_missed_interviews(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """Interview emails where student was never notified."""
    results = db.query(
        Email, Classification, InterviewEvent, Student, NotificationDraft
    ).join(
        Classification, Classification.email_id == Email.id
    ).outerjoin(
        InterviewEvent, InterviewEvent.email_id == Email.id
    ).outerjoin(
        Student, Student.id == InterviewEvent.student_id
    ).outerjoin(
        NotificationDraft, NotificationDraft.interview_event_id == InterviewEvent.id
    ).filter(
        Classification.category == "Interview Request",
    ).filter(
        (NotificationDraft.id == None) |
        (NotificationDraft.email_status.notin_(["sent", "approved"]))
    ).order_by(Email.received_date.desc()).all()

    return [
        {
            "email_id": e.id,
            "subject": e.subject,
            "from_address": e.from_address,
            "received_date": e.received_date.isoformat() + "Z",
            "company_name": c.company_name,
            "position": c.position,
            "student_name": s.full_name if s else "Unknown",
            "notification_status": n.email_status if n else "not_created",
        }
        for e, c, ie, s, n in results
    ]


@router.get("/weekly-summary")
async def get_weekly_summary(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """One-page weekly summary for stakeholders."""
    from datetime import date
    today = datetime.utcnow()
    week_start = today - timedelta(days=7)

    runs = db.query(ProcessRun).filter(ProcessRun.run_timestamp >= week_start).all()

    total_emails = sum(r.total_emails for r in runs)
    total_interviews = sum(r.interview_requests for r in runs)
    total_organized = sum(r.organized for r in runs)
    total_deleted = sum(r.spam_deleted for r in runs)
    successful_runs = sum(1 for r in runs if r.status == "success")

    # Notifications sent this week
    sent_count = db.query(NotificationDraft).filter(
        NotificationDraft.sent_at >= week_start
    ).count()

    # Top companies this week
    top_companies = db.query(
        Classification.company_name,
        func.count(Classification.id).label("cnt")
    ).join(Email, Email.id == Classification.email_id).filter(
        Classification.category == "Interview Request",
        Email.received_date >= week_start,
        Classification.company_name != None,
    ).group_by(Classification.company_name).order_by(func.count(Classification.id).desc()).limit(5).all()

    return {
        "week_start": week_start.date().isoformat(),
        "week_end": today.date().isoformat(),
        "total_emails_processed": total_emails,
        "interview_requests_found": total_interviews,
        "emails_organized": total_organized,
        "spam_deleted": total_deleted,
        "processing_runs": len(runs),
        "successful_runs": successful_runs,
        "students_notified": sent_count,
        "top_companies": [{"company": r.company_name, "count": r.cnt} for r in top_companies],
    }


@router.get("/pipeline")
async def get_interview_pipeline(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """Interview pipeline funnel: emails → classified → notified → scheduled."""
    total_emails = db.query(Email).count()
    classified_interviews = db.query(Classification).filter(
        Classification.category == "Interview Request"
    ).count()
    events_created = db.query(InterviewEvent).count()
    notifications_sent = db.query(NotificationDraft).filter(
        NotificationDraft.email_status.in_(["sent", "approved"])
    ).count()
    interviews_scheduled = db.query(InterviewEvent).filter(
        InterviewEvent.interview_date != None
    ).count()

    return {
        "total_emails": total_emails,
        "classified_as_interview": classified_interviews,
        "events_created": events_created,
        "students_notified": notifications_sent,
        "interviews_scheduled": interviews_scheduled,
    }


@router.get("/run-processing/status")
async def get_processing_status(
    user: UserSession = Depends(get_current_user)
):
    """
    Return whether a processing run is currently active.

    The frontend uses this to disable the Run Now button and show a spinner
    while a run is in progress.

    Returns:
        { "locked": bool, "lock_info": { pid, started_at, triggered_by, elapsed_seconds } | null }
    """
    lock_info = get_run_lock_status()
    return {
        "locked": lock_info is not None,
        "lock_info": lock_info,
    }


@router.post("/run-processing")
async def trigger_manual_processing(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Manually trigger email processing.

    Returns 409 Conflict if a run is already active (run lock held).
    Runs the process_inbox_auto.py script and imports the results
    into the database.

    Returns:
        Processing results with status, duration, and summary data

    Raises:
        HTTPException 409: If another run is already in progress
        HTTPException 500: If processing fails
    """
    # Guard: reject immediately if a run is already active
    lock_info = get_run_lock_status()
    if lock_info:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"A processing run is already active "
                    f"(triggered by '{lock_info['triggered_by']}', "
                    f"running for {lock_info['elapsed_seconds']:.0f}s)"
                ),
                "lock_info": lock_info,
            }
        )

    try:
        result = run_email_processing(db, triggered_by=user.username)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
