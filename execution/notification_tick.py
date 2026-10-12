"""
Run one pass of the student notification escalation: send what is due, alert the approver, end finished sequences.

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

# The repo's .env must be read BEFORE `enabled()` looks at NOTIFY_ESCALATION_ENABLED: this script is started by cron with only the container's own
# environment, so without this the job answered "disabled" and did nothing even after the switch was turned on (found 2026-10-10).
try:
    from dotenv import load_dotenv
    load_dotenv(os.getenv("NOTIFY_TICK_ENV_FILE") or (_ROOT / ".env"))     # the override is only for tests
except Exception:                      # python-dotenv missing: fall back to whatever the process already has
    pass


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
    now = now or datetime.utcnow()
    alerts = engine.RoleAlerts(db=db)
    report = engine.tick(db, now, notify_channels.channels_from_env(), alerts, base)
    print(f"tick: sent={report.sent} dry_run={report.dry_run} failed={report.failed} skipped={report.skipped} "
          f"deferred={report.deferred} spaced={report.spaced} no_response_alerts={report.no_response_alerts} ended={report.ended}")
    for line in report.details:
        print(f"  problem: {line}")

    # Replies and calls are read from the student's GHL Conversations (needs GHL_CONVERSATIONS_API_KEY).
    import ghl_client
    config = ghl_client.GhlConfig.from_env()
    if config.can_read_conversations:
        polled = engine.poll_replies(db, now, ghl_client.GhlClient(config), alerts)
        print(f"poll: sequences={polled.sequences} new_messages={polled.new_messages} "
              f"stopped={polled.stopped} errors={polled.errors}")
        for line in polled.details:
            print(f"  problem: {line}")
    else:
        print("poll: skipped (GHL_CONVERSATIONS_API_KEY not set)")
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()
