"""notification_tick must read the .env file itself: cron starts it with only the container's own environment."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _enabled_with(env_text, tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text(env_text, encoding="utf-8")
    code = "import sys; sys.path.insert(0, 'execution'); import notification_tick as t; print(t.enabled())"
    env = {**os.environ, "NOTIFY_TICK_ENV_FILE": str(env_file)}
    env.pop("NOTIFY_ESCALATION_ENABLED", None)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60, env=env)
    return out.stdout.strip().splitlines()[-1], out.stdout + out.stderr


def test_the_tick_sees_a_flag_that_is_only_in_the_dotenv_file(tmp_path):
    answer, output = _enabled_with("NOTIFY_ESCALATION_ENABLED=true\n", tmp_path)
    assert answer == "True", output


def test_without_the_flag_the_tick_stays_off(tmp_path):
    answer, output = _enabled_with("SOMETHING_ELSE=1\n", tmp_path)
    assert answer == "False", output
