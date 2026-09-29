"""
Schedule configuration API endpoints.

Provides endpoints to manage the automated email processing schedule.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import subprocess
import os
from pathlib import Path

from database import get_db
from auth import get_current_user
from models import UserSession, SystemConfig

router = APIRouter()


class ScheduleConfig(BaseModel):
    interval_minutes: int
    batch_size: int
    last_updated: Optional[str] = None
    updated_by: Optional[str] = None


class UpdateScheduleRequest(BaseModel):
    interval_minutes: Optional[int] = None
    batch_size: Optional[int] = None


@router.get("/config", response_model=ScheduleConfig)
async def get_schedule_config(
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Get current schedule configuration.

    Returns the current processing interval and batch size.
    """
    interval_config = db.query(SystemConfig).filter(
        SystemConfig.key == "processing_interval_minutes"
    ).first()

    batch_config = db.query(SystemConfig).filter(
        SystemConfig.key == "email_batch_size"
    ).first()

    # Use defaults if not set. The interval default must match the real
    # scheduler (crontab `0 */2 * * *`, i.e. 120 min): the dashboard countdown
    # is computed from this value, so a wrong default shows a wrong "Next run in".
    interval_minutes = int(interval_config.value) if interval_config else 120
    batch_size = int(batch_config.value) if batch_config else 20

    # Use most recent update timestamp
    last_updated = None
    updated_by = None
    if interval_config and interval_config.updated_at:
        last_updated = interval_config.updated_at
        updated_by = interval_config.updated_by
    if batch_config and batch_config.updated_at:
        if not last_updated or batch_config.updated_at > last_updated:
            last_updated = batch_config.updated_at
            updated_by = batch_config.updated_by

    return ScheduleConfig(
        interval_minutes=interval_minutes,
        batch_size=batch_size,
        last_updated=last_updated.isoformat() if last_updated else None,
        updated_by=updated_by
    )


@router.post("/config")
async def update_schedule_config(
    request: UpdateScheduleRequest,
    db: Session = Depends(get_db),
    user: UserSession = Depends(get_current_user)
):
    """
    Update schedule configuration.

    Updates the processing interval and/or batch size.

    Args:
        request: interval_minutes (5, 10, 15, 30, 60) and/or batch_size (10, 20, 30, 50, 75, 100)

    Returns:
        Success message and new configuration
    """
    valid_intervals = [5, 10, 15, 30, 60, 120]
    valid_batch_sizes = [10, 20, 30, 50, 75, 100]

    if request.interval_minutes is None and request.batch_size is None:
        raise HTTPException(
            status_code=400,
            detail="Must provide interval_minutes and/or batch_size"
        )

    # Validate interval if provided
    if request.interval_minutes is not None and request.interval_minutes not in valid_intervals:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid interval. Must be one of: {valid_intervals}"
        )

    # Validate batch_size if provided
    if request.batch_size is not None and request.batch_size not in valid_batch_sizes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid batch_size. Must be one of: {valid_batch_sizes}"
        )

    task_warning = None

    # Update interval_minutes if provided
    if request.interval_minutes is not None:
        interval_config = db.query(SystemConfig).filter(
            SystemConfig.key == "processing_interval_minutes"
        ).first()

        if interval_config:
            interval_config.value = str(request.interval_minutes)
            interval_config.updated_at = datetime.utcnow()
            interval_config.updated_by = user.username
        else:
            interval_config = SystemConfig(
                key="processing_interval_minutes",
                value=str(request.interval_minutes),
                updated_at=datetime.utcnow(),
                updated_by=user.username
            )
            db.add(interval_config)

        # Try to update Windows scheduled task (non-fatal if it fails)
        try:
            update_scheduled_task(request.interval_minutes)
        except Exception as e:
            task_warning = str(e)

    # Update batch_size if provided
    if request.batch_size is not None:
        batch_config = db.query(SystemConfig).filter(
            SystemConfig.key == "email_batch_size"
        ).first()

        if batch_config:
            batch_config.value = str(request.batch_size)
            batch_config.updated_at = datetime.utcnow()
            batch_config.updated_by = user.username
        else:
            batch_config = SystemConfig(
                key="email_batch_size",
                value=str(request.batch_size),
                updated_at=datetime.utcnow(),
                updated_by=user.username
            )
            db.add(batch_config)

    db.commit()

    result = {
        "message": "Schedule updated successfully",
        "interval_minutes": request.interval_minutes,
        "batch_size": request.batch_size,
        "updated_by": user.username,
        "updated_at": datetime.utcnow().isoformat()
    }

    if task_warning:
        result["task_warning"] = (
            f"Config saved but Windows task update failed: {task_warning}. "
            "The scheduled task may need to be updated manually."
        )

    return result


def update_scheduled_task(interval_minutes: int):
    """
    Update the Windows scheduled task with new interval.

    Args:
        interval_minutes: New interval in minutes
    """
    # Path to PowerShell script
    project_root = Path(__file__).parent.parent.parent.parent.parent
    ps_script = project_root / "scripts" / "update_schedule.ps1"

    # Run PowerShell script to update task
    cmd = [
        "powershell",
        "-ExecutionPolicy", "Bypass",
        "-File", str(ps_script),
        "-IntervalMinutes", str(interval_minutes)
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:
        raise Exception(f"PowerShell script failed: {result.stderr}")
