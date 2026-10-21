"""The logged GPT cost must use the classifier's real model (gpt-4o-mini) rates."""

import sys
from pathlib import Path

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import classify_email  # noqa: E402
import process_inbox_auto as pia  # noqa: E402


def test_classifier_model_is_the_one_priced():
    assert classify_email.call_claude_api.__defaults__ is not None
    import inspect
    default_model = inspect.signature(classify_email.call_claude_api).parameters["model"].default
    assert default_model == "gpt-4o-mini"


def test_compute_cost_uses_mini_rates():
    # 1M input tokens = $0.15, 1M output tokens = $0.60
    assert pia._compute_cost(1_000_000, 0) == 0.15
    assert pia._compute_cost(0, 1_000_000) == 0.60
    assert round(pia._compute_cost(3500, 650), 6) == round(0.000525 + 0.00039, 6)


def test_per_email_estimate_matches_compute_cost():
    assert abs(pia._EST_COST_PER_EMAIL_USD - pia._compute_cost(3500, 650)) < 1e-12
