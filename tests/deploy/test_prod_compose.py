"""Guardrail tests for the Hetzner production compose file.

These parse services/dashboard/docker-compose.prod.yml (no Docker needed) and
lock in the security-relevant decisions: Postgres is never published, only the
web service exposes ports, the scheduler is opt-in, and no secret values are
hard-coded in the file.
"""
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "services" / "dashboard" / "docker-compose.prod.yml"


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_expected_services_exist(compose):
    assert set(compose["services"]) == {"postgres", "api", "web", "cron"}


def test_postgres_is_not_published(compose):
    assert "ports" not in compose["services"]["postgres"]


def test_only_web_publishes_ports(compose):
    published = {
        name for name, svc in compose["services"].items() if svc.get("ports")
    }
    assert published == {"web"}
    assert set(compose["services"]["web"]["ports"]) == {"80:80", "443:443"}


def test_cron_is_opt_in_profile(compose):
    """Scheduler must never start with a plain `up` -- avoids double-processing
    the mailbox while GitHub Actions is still the live scheduler."""
    assert compose["services"]["cron"]["profiles"] == ["scheduler"]


def test_api_runs_non_root_in_production_mode(compose):
    api = compose["services"]["api"]
    assert api["user"] == "1000:1000"
    assert api["environment"]["ENVIRONMENT"] == "production"


def test_all_services_restart_unless_stopped(compose):
    for name, svc in compose["services"].items():
        assert svc.get("restart") == "unless-stopped", name


def test_postgres_password_is_required_not_hardcoded(compose):
    pw = compose["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"]
    assert pw.startswith("${POSTGRES_PASSWORD:?")


def test_no_hardcoded_secrets_in_compose_file():
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    # every password/secret/key value must be an ${...} interpolation
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.search(r"(PASSWORD|SECRET|API_KEY|TOKEN)\s*[:=]", stripped):
            assert "${" in stripped, f"possible hard-coded secret: {stripped}"


def test_database_url_uses_internal_hostname(compose):
    for name in ("api", "cron"):
        url = compose["services"][name]["environment"]["DATABASE_URL"]
        assert "@postgres:5432/" in url, name
