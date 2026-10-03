import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))
import run_now_watcher as w  # noqa: E402


def make(tmp_path, age=10, who="admin"):
    req = tmp_path / "run_now.request"
    req.write_text(json.dumps({"requested_by": who}))
    return req, req.stat().st_mtime + age


def test_decisions():
    assert w.decide(False, 0, False) == "none"
    assert w.decide(True, 60, False) == "run"
    assert w.decide(True, 60, True) == "wait"
    assert w.decide(True, w.MAX_AGE_SECONDS + 1, False) == "expire"
    assert w.decide(True, w.MAX_AGE_SECONDS + 1, True) == "expire"


def test_no_request_does_nothing(tmp_path):
    ran = []
    assert w.main(tmp_path / "none.request", runner=lambda: ran.append(1), lock_info=lambda: None) == "none" and ran == []


def test_a_fresh_request_runs_once_and_is_consumed(tmp_path):
    req, now = make(tmp_path)
    ran = []
    assert w.main(req, now=now, runner=lambda: ran.append(1), lock_info=lambda: None) == "run"
    assert ran == [1] and not req.exists()
    assert w.main(req, now=now, runner=lambda: ran.append(1), lock_info=lambda: None) == "none" and ran == [1]


def test_a_request_waits_while_a_run_is_active_and_survives(tmp_path):
    req, now = make(tmp_path)
    ran = []
    assert w.main(req, now=now, runner=lambda: ran.append(1), lock_info=lambda: {"pid": 1}) == "wait"
    assert ran == [] and req.exists()


def test_an_old_request_is_dropped_without_running(tmp_path):
    req, now = make(tmp_path, age=w.MAX_AGE_SECONDS + 5)
    ran = []
    assert w.main(req, now=now, runner=lambda: ran.append(1), lock_info=lambda: None) == "expire"
    assert ran == [] and not req.exists()
