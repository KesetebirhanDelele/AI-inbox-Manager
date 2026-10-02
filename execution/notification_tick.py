"""
Run one pass of the student notification escalation: send what is due, alert Rob, end finished sequences.

Does nothing unless NOTIFY_ESCALATION_ENABLED is 1/true/yes, so deploying this is safe. Channels
default to dry_run (nothing delivered); see notify_channels.py.

Run it every 5 minutes from a host cron entry once escalation is enabled, for example:
    */5 * * * * root docker exec -u appuser -w /repo inboxgenius-cron-1 python execution/notification_tick.py >> /opt/ai-inbox-manager/logs/notify_tick.log 2>&1
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger("notification_tick")


def enabled() -> bool:
    return os.getenv("NOTIFY_ESCALATION_ENABLED", "").strip().lower() in ("1", "true", "yes")


def run(now: datetime = None):
    if not enabled():
        print("Escalation is disabled (NOTIFY_ESCALATION_ENABLED not set). Nothing to do.")
        return None
    import escalation_engine as engine
    import notify_channels
    from process_inbox_auto import get_db_session

    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")
    base = os.getenv("NOTIFY_ACK_BASE_URL", "https://2-29-47-89.nip.io/api/notifications/ack")
    report = engine.tick(db, now or datetime.utcnow(), notify_channels.channels_from_env(), engine.RobAlerts(), base)
    print(f"tick: sent={report.sent} dry_run={report.dry_run} failed={report.failed} skipped={report.skipped} "
          f"rob_no_response={report.rob_no_response} ended={report.ended}")
    for line in report.details:
        print(f"  problem: {line}")
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()
