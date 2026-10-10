"""The made-up-students simulation of the notification cadence must keep passing: it guards the schedule, quiet hours, stops and alerts."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))

import simulate_notifications as sim  # noqa: E402


def test_the_simulation_passes_every_check_and_leaves_the_environment_alone():
    before = os.environ.get("DATABASE_URL")
    result = sim.run()
    failed = [(name, detail) for name, ok, detail in sim.checks(result) if not ok]
    assert not failed, failed
    assert os.environ.get("DATABASE_URL") == before
    assert len(result["people"]) == 10


def test_nothing_in_the_simulation_is_a_real_message():
    result = sim.run()
    statuses = {a.status for p in result["people"].values() for a in p["seq"].attempts}
    assert "sent" not in statuses
    assert all(m["recipient_email"].endswith("@example.test") for m in result["mail"].sent)
