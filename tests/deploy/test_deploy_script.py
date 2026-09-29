"""Tests for scripts/deploy_hetzner.sh.

Only the parts that need no server: the danger-window rule (a pure shell
function), --help, argument errors and bash syntax. Nothing here opens an SSH
connection or touches the server.

Background: on 2026-09-29 a deploy overlapped the 22:00 UTC scheduled run, starved
the server, and Gmail dropped the IMAP connection. The script now refuses to
deploy while a run is likely executing.
"""
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "scripts/deploy_hetzner.sh"  # relative: run with cwd=REPO_ROOT (works with Git Bash on Windows)

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def _bash(cmd: str):
    return subprocess.run(
        [BASH, "-c", cmd], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
    )


def _unsafe(hour, minute) -> bool:
    r = _bash(f'source {SCRIPT}; deploy_window_unsafe "{hour}" "{minute}"')
    assert r.returncode in (0, 1), r.stderr
    return r.returncode == 0


@pytest.mark.parametrize("hour, minute, expected_unsafe", [
    # even UTC hour, first 12 minutes: a scheduled run may still be executing
    ("00", "00", True),
    ("00", "05", True),
    ("00", "11", True),
    ("22", "00", True),
    ("12", "11", True),
    ("02", "03", True),
    # even hour but past the window
    ("00", "12", False),
    ("22", "12", False),
    ("22", "30", False),
    ("22", "59", False),
    # odd hours are always safe (no scheduled run)
    ("01", "00", False),
    ("01", "05", False),
    ("23", "05", False),
    ("13", "00", False),
    # leading zeros must not be parsed as octal ("08" and "09" are invalid octal)
    ("08", "05", True),
    ("09", "05", False),
    ("08", "09", True),
    ("08", "12", False),
])
def test_deploy_window(hour, minute, expected_unsafe):
    assert _unsafe(hour, minute) is expected_unsafe


def _safe(path) -> bool:
    r = _bash(f"source {SCRIPT}; is_safe_relpath {shlex.quote(path)}")
    assert r.returncode in (0, 1), r.stderr
    return r.returncode == 0


@pytest.mark.parametrize("path, expected", [
    ("scripts/update_schedule.ps1", True),
    ("services/dashboard/QUICKSTART.md", True),
    ("execution/old module.py", True),           # spaces are fine (quoted with %q)
    ("", False),
    ("/etc/passwd", False),                       # absolute
    ("../outside", False),                        # traversal
    ("a/../../b", False),
    ("-rf", False),                               # would be read as an option
    (".env", False),                              # server-only state
    (".env.compose", False),
    ("services/dashboard/.env.compose", False),   # the server's real compose env file
    ("services/dashboard/.env", False),
    (".env.example", True),                       # a tracked template may legitimately be deleted
    (".deployed_commit", False),
    ("logs/cron.log", False),
    ("tmp/process.lock", False),
    ("config/gmail_token.json", False),
    ("config/gmail_credentials.json", False),
    ("config/service-account-key.json", False),
])
def test_is_safe_relpath(path, expected):
    assert _safe(path) is expected


def test_script_has_valid_bash_syntax():
    r = _bash(f"bash -n {SCRIPT}")
    assert r.returncode == 0, r.stderr


def test_sourcing_does_not_run_main():
    """The unit tests source the file; that must not deploy or even print."""
    r = _bash(f"source {SCRIPT}; echo sourced-ok")
    assert r.returncode == 0
    assert r.stdout.strip() == "sourced-ok"


def test_help_needs_no_server():
    r = _bash(f"bash {SCRIPT} --help")
    assert r.returncode == 0
    assert "--dry-run" in r.stdout and "--force" in r.stdout and "--build-web" in r.stdout


def test_unknown_option_is_rejected():
    r = _bash(f"bash {SCRIPT} --bogus")
    assert r.returncode == 2
    assert "Unknown option" in r.stderr


def test_script_never_handles_secrets():
    """Guardrail: deploys must not read or print env files / credentials."""
    text = (REPO_ROOT / SCRIPT).read_text(encoding="utf-8")
    for forbidden in ("cat .env", "printenv", "echo $EMAIL_PASSWORD", "OPENAI_API_KEY"):
        assert forbidden not in text
