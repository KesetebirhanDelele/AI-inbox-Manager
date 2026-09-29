"""
Schedule information API endpoint (read-only).

The processing schedule is NOT editable from the dashboard: it is the cron
entry in execution/crontab.server (`0 */2 * * *`) and the per-run email cap is
the MAX_EMAILS_PER_RUN environment variable in the server's root .env. This
endpoint reports those real values so the UI (Settings page, "Next run in"
countdown) never shows something the scheduler isn't actually doing.

(Earlier versions stored editable interval/batch values in system_config and
tried to update a Windows scheduled task; neither ever affected the real
scheduler, so that write path was removed.)
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_current_user
from models import UserSession

router = APIRouter()

# Must match the cron schedule in execution/crontab.server ("0 */2 * * *").
# The frontend countdown derives the next run from this value.
SCHEDULE_INTERVAL_MINUTES = 120

# Must match the default in execution/process_inbox_auto.py.
DEFAULT_MAX_EMAILS_PER_RUN = 100


class ScheduleConfig(BaseModel):
    interval_minutes: int
    batch_size: int
    last_updated: Optional[str] = None
    updated_by: Optional[str] = None


def _max_emails_per_run() -> int:
    """Per-run email cap from MAX_EMAILS_PER_RUN.

    Unset, blank, non-numeric or non-positive values fall back to the pipeline's
    default rather than raising -- a bad env var must not break the page.
    """
    raw = os.getenv("MAX_EMAILS_PER_RUN", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_EMAILS_PER_RUN
    except ValueError:
        value = DEFAULT_MAX_EMAILS_PER_RUN
    return value if value > 0 else DEFAULT_MAX_EMAILS_PER_RUN


@router.get("/config", response_model=ScheduleConfig)
async def get_schedule_config(user: UserSession = Depends(get_current_user)):
    """Return the real processing interval and per-run email cap (read-only)."""
    return ScheduleConfig(
        interval_minutes=SCHEDULE_INTERVAL_MINUTES,
        batch_size=_max_emails_per_run(),
    )
