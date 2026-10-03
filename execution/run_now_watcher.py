"""
Start a pipeline run that someone asked for with "Run Now" on the dashboard (production).

The dashboard only writes tmp/run_now.request. This script is started every minute by the host cron
(/etc/cron.d/inboxgenius-runnow, see execution/crontab.runnow). With no request it does nothing and exits at once. With a request it:
  * ignores (and deletes) a request older than 30 minutes,
  * leaves the request in place while a run is active (the run lock), so it starts right after that run ends,
  * otherwise deletes the request and runs exactly what the scheduler runs: python execution/process_inbox_auto.py
The pipeline takes the run lock itself, so two runs can never overlap.
"""
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "execution"))

MAX_AGE_SECONDS = 30 * 60
REQUEST = _ROOT / "tmp" / "run_now.request"


def decide(request_exists: bool, age_seconds: float, lock_active: bool) -> str:
    """'none' (nothing asked), 'expire' (too old), 'wait' (a run is active), or 'run'."""
    if not request_exists:
        return "none"
    if age_seconds > MAX_AGE_SECONDS:
        return "expire"
    if lock_active:
        return "wait"
    return "run"


def main(request: Path = REQUEST, now: Optional[float] = None, runner=None, lock_info=None) -> str:
    if not request.exists():
        return "none"
    now = time.time() if now is None else now
    if lock_info is None:
        from run_lock import get_lock_info
        lock_info = get_lock_info
    action = decide(True, now - request.stat().st_mtime, lock_info() is not None)
    if action == "expire":
        request.unlink(missing_ok=True)
    elif action == "run":
        who = "unknown"
        try:
            who = json.loads(request.read_text()).get("requested_by", "unknown")
        except (OSError, ValueError):
            pass
        request.unlink(missing_ok=True)
        print(f"run requested by {who}: starting the pipeline", flush=True)
        (runner or _run_pipeline)()
    return action


def _run_pipeline() -> None:
    log = _ROOT / "logs" / "cron.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as out:
        subprocess.run([sys.executable, str(_ROOT / "execution" / "process_inbox_auto.py")], cwd=str(_ROOT), stdout=out, stderr=out)


if __name__ == "__main__":
    print(main())
