"""
Integration wrapper for running the automated email processing script.

This module provides a function to manually trigger the process_inbox_auto.py
script from the dashboard.
"""

import subprocess
import sys
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from dotenv import dotenv_values

from models import ProcessRun


def get_run_lock_status() -> Optional[Dict[str, Any]]:
    """
    Return current run lock info, or None if no active lock.

    Reads the lock file written by run_lock.py without importing it directly,
    so this function is safe to call from any Python path.

    Returns:
        Dict with pid, started_at, triggered_by, elapsed_seconds — or None.
    """
    import json

    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent.parent.parent
    lock_path = project_root / "tmp" / "process.lock"

    if not lock_path.exists():
        return None

    try:
        with open(lock_path, "r") as f:
            lock_data = json.load(f)

        pid = lock_data.get("pid")
        started_str = lock_data.get("started_at", "")

        # Check if the PID is still alive
        if pid:
            try:
                os.kill(int(pid), 0)
            except OSError:
                return None  # dead PID — stale lock

        elapsed = 0.0
        if started_str:
            try:
                started = datetime.fromisoformat(started_str)
                elapsed = (datetime.utcnow() - started).total_seconds()
            except Exception:
                pass

        return {
            "pid": pid,
            "started_at": started_str,
            "triggered_by": lock_data.get("triggered_by", "unknown"),
            "elapsed_seconds": round(elapsed, 1),
        }
    except Exception:
        return None


REQUEST_MAX_AGE_SECONDS = 30 * 60      # an unserved request older than this is ignored by the server (execution/run_now_watcher.py)


def _project_root() -> Path:
    return Path(__file__).parent.parent.parent.parent.parent


def request_run_on_server(triggered_by: str) -> Dict[str, Any]:
    """
    Production "Run Now": never run the pipeline inside the web process (it would compete with the scheduler for CPU and the
    mailbox). Instead leave a request file that the server's one-minute watcher (execution/run_now_watcher.py, host cron
    /etc/cron.d/inboxgenius-runnow) turns into the SAME run the scheduler does, under the same run lock, so it can never
    overlap a scheduled run or another manual one.
    """
    import json

    lock = get_run_lock_status()
    if lock:
        return {
            "status": "locked",
            "message": (
                f"A processing run is already active (started by '{lock['triggered_by']}', running for "
                f"{lock['elapsed_seconds']:.0f}s). Wait for it to finish, then look at Recent Processing Runs."
            ),
            "lock_info": lock,
            "triggered_by": triggered_by,
        }

    request_path = _project_root() / "tmp" / "run_now.request"
    try:
        if request_path.exists():
            age = time.time() - request_path.stat().st_mtime
            if age < REQUEST_MAX_AGE_SECONDS:
                return {"status": "queued", "message": "A run was already requested. The server starts it within a minute.",
                        "triggered_by": triggered_by}
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(json.dumps({"requested_by": triggered_by, "requested_at": datetime.utcnow().isoformat()}))
    except OSError as exc:
        return {"status": "error", "message": f"Could not request a run: {exc}", "triggered_by": triggered_by}
    return {
        "status": "queued",
        "message": "Run requested. The server starts it within a minute and it takes about 3 minutes; then refresh the dashboard.",
        "triggered_by": triggered_by,
    }


def run_email_processing(db: Session, triggered_by: str = "manual") -> Dict[str, Any]:
    """
    Trigger the automated email processing script manually.

    This runs the execution/process_inbox_auto.py script and waits for completion.
    After the script completes, it imports the generated summary.json file into
    the database.

    Args:
        db: Database session
        triggered_by: Username or identifier of who triggered the process

    Returns:
        Dict with status, message, and processing results

    Raises:
        Exception: If the processing script fails
    """
    # In production the pipeline is run only by the server's scheduler (the Hetzner
    # `cron` container, every 2 hours on the hour, UTC — RUNBOOK.md §4c). Manual runs
    # from the dashboard are deliberately disabled there: they would let any
    # logged-in user start a run beside the scheduler (double-processing the
    # mailbox, extra OpenAI cost). To force a run, use the server command in §4c.
    if os.environ.get("ENVIRONMENT") == "production":
        return request_run_on_server(triggered_by)

    # Find the project root
    # From services/dashboard/api/integration, go up 4 levels to ClaudeTest
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent.parent.parent
    script_path = project_root / "execution" / "process_inbox_auto.py"

    if not script_path.exists():
        raise FileNotFoundError(f"Processing script not found at {script_path}")

    # ── Run lock check (pre-flight) ───────────────────────────────────────────
    # The subprocess also acquires the lock itself, but we check here first so
    # the API can return a clear 409-style response before even spawning a process.
    active_lock = get_run_lock_status()
    if active_lock:
        return {
            "status": "locked",
            "message": (
                f"A processing run is already active "
                f"(triggered by '{active_lock['triggered_by']}', "
                f"running for {active_lock['elapsed_seconds']:.0f}s)"
            ),
            "lock_info": active_lock,
            "triggered_by": triggered_by,
        }

    # Run the script
    start_time = datetime.utcnow()

    # Load environment variables from project root .env file
    env_file = project_root / ".env"
    env_vars = os.environ.copy()

    if env_file.exists():
        # Load and merge .env variables from project root
        dotenv_vars = dotenv_values(env_file)
        env_vars.update(dotenv_vars)

    # Per-run cap: the same MAX_EMAILS_PER_RUN the scheduled run uses (default 100).
    # (The editable "email_batch_size" DB setting was removed 2026-09-29 — it was
    # never applied to the real scheduler.)
    try:
        batch_size = int(env_vars.get("MAX_EMAILS_PER_RUN") or 100)
    except ValueError:
        batch_size = 100
    if batch_size <= 0:
        batch_size = 100

    try:
        result = subprocess.run(
            [sys.executable, str(script_path), "--limit", str(batch_size),
             "--triggered-by", triggered_by],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=900,  # 15 minute timeout
            env=env_vars  # Pass the correct environment variables
        )

        duration_seconds = (datetime.utcnow() - start_time).total_seconds()

        # Exit codes: 0 = success, 2 = already running (lock), 10 = success + interviews
        if result.returncode == 2:
            return {
                "status": "locked",
                "message": "Processing script reported another run is already active",
                "duration_seconds": duration_seconds,
                "triggered_by": triggered_by,
            }

        if result.returncode not in [0, 10]:
            # Script failed
            error_message = result.stderr or result.stdout or "Unknown error"
            return {
                "status": "error",
                "message": f"Processing script failed: {error_message}",
                "duration_seconds": duration_seconds,
                "triggered_by": triggered_by
            }

        # Script succeeded - parse output for summary
        output = result.stdout
        errors = result.stderr

        # Try to import the latest summary file
        summary_data = _import_latest_summary(db, project_root)

        # Determine if there were actually emails processed
        if summary_data.get("imported"):
            message = f"Email processing completed: {summary_data.get('total_emails', 0)} emails processed"
        elif summary_data.get("reason") == "Already imported":
            message = "Processing completed but results were already imported"
        elif summary_data.get("reason") == "No auto_process directories found":
            message = "Processing completed but no emails were found to process"
        else:
            message = f"Processing completed: {summary_data.get('reason', 'Unknown status')}"

        return {
            "status": "success" if summary_data.get("imported") else "info",
            "message": message,
            "duration_seconds": duration_seconds,
            "triggered_by": triggered_by,
            "output": output[:500] if output else None,  # Limit output size
            "errors": errors[:500] if errors else None,
            "summary": summary_data
        }

    except subprocess.TimeoutExpired:
        duration_seconds = (datetime.utcnow() - start_time).total_seconds()
        return {
            "status": "error",
            "message": "Processing script timed out after 5 minutes",
            "duration_seconds": duration_seconds,
            "triggered_by": triggered_by
        }
    except Exception as e:
        duration_seconds = (datetime.utcnow() - start_time).total_seconds()
        return {
            "status": "error",
            "message": f"Error running processing script: {str(e)}",
            "duration_seconds": duration_seconds,
            "triggered_by": triggered_by
        }


def _import_latest_summary(db: Session, project_root: Path) -> Dict[str, Any]:
    """
    Import the most recent summary.json file into the database.

    Args:
        db: Database session
        project_root: Path to project root

    Returns:
        Dict with import results
    """
    import json

    tmp_dir = project_root / "tmp"
    if not tmp_dir.exists():
        return {"imported": False, "reason": "tmp directory not found"}

    # Find the most recent auto_process directory
    auto_process_dirs = sorted(tmp_dir.glob("auto_process_*"), reverse=True)

    if not auto_process_dirs:
        return {"imported": False, "reason": "No auto_process directories found"}

    latest_dir = auto_process_dirs[0]
    summary_file = latest_dir / "summary.json"

    if not summary_file.exists():
        return {"imported": False, "reason": "summary.json not found in latest directory"}

    try:
        with open(summary_file, 'r') as f:
            summary = json.load(f)

        # Handle both old and new summary.json formats
        if 'statistics' in summary:
            # New format: data is under 'statistics' key
            stats = summary['statistics']
            run_timestamp = datetime.fromisoformat(summary['processing_timestamp'].replace('Z', '+00:00'))
            total_emails = stats['total_emails']
            categories = stats.get('categories', {})
            interview_count = stats.get('interview_requests', 0)
            organized = stats.get('organized', 0)
            spam_deleted = stats.get('spam_deleted', 0)
        else:
            # Old format: data at top level
            run_timestamp = datetime.fromisoformat(summary['run_timestamp'])
            total_emails = summary['total_emails']
            categories = summary.get('categories', {})
            interview_count = summary.get('categories', {}).get('Interview Request', 0)
            organized = sum(
                count for cat, count in categories.items()
                if cat not in ['Interview Request', 'Spam or Scam', 'Keep in Inbox']
            )
            spam_deleted = categories.get('Spam or Scam', 0)

        # Check if already imported — use a ±120-second window to handle minor
        # timestamp differences between _log_process_run() (which uses the folder
        # timestamp, second-precision) and this import (which uses processing_timestamp
        # with microsecond precision).
        from datetime import timedelta
        window = timedelta(seconds=120)
        existing = db.query(ProcessRun).filter(
            ProcessRun.run_timestamp >= run_timestamp - window,
            ProcessRun.run_timestamp <= run_timestamp + window,
        ).first()

        if existing:
            return {
                "imported": False,
                "reason": "Already imported",
                "run_id": existing.id
            }

        # Create new process run
        process_run = ProcessRun(
            run_timestamp=run_timestamp,
            total_emails=total_emails,
            interview_requests=interview_count,
            organized=organized,
            spam_deleted=spam_deleted,
            categories_breakdown=categories,
            duration_seconds=summary.get('duration_seconds', 0),
            status='success',
            error_log=None
        )

        db.add(process_run)
        db.commit()
        db.refresh(process_run)

        return {
            "imported": True,
            "run_id": process_run.id,
            "total_emails": process_run.total_emails,
            "interview_requests": process_run.interview_requests
        }

    except Exception as e:
        db.rollback()
        return {
            "imported": False,
            "reason": f"Error importing: {str(e)}"
        }
