"""Technical Interview, Interview Follow-up, Client Screen and Job Machine follow Ali's labels workbook."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))

import classify_email as ce  # noqa: E402
import process_inbox_auto as pia  # noqa: E402
import subclassify_interview as si  # noqa: E402
import validate_classification as vc  # noqa: E402


def test_new_categories_are_approved_everywhere():
    for cat in ("Technical Interview", "Interview Follow-up"):
        assert cat in ce.APPROVED_CATEGORIES
        assert cat in vc.APPROVED_CATEGORIES
        assert f"**{cat}**" in ce.CLASSIFICATION_PROMPT or cat in ce.CLASSIFICATION_PROMPT


def test_new_categories_have_workbook_folders():
    assert pia.CATEGORY_TO_FOLDER["Technical Interview"] == "Technical Interview"
    assert pia.CATEGORY_TO_FOLDER["Interview Follow-up"] == "Interview follow up"


def test_follow_up_never_creates_an_interview_event():
    assert not pia.creates_interview_event({"category": "Interview Follow-up", "confidence": 0.99})


def test_technical_and_client_screens_create_events():
    assert pia.creates_interview_event({"category": "Technical Interview", "confidence": 0.9})
    assert pia.creates_interview_event({"category": "Client Screen", "confidence": 0.9})
    assert pia._CATEGORY_TO_SUB_TYPE["Technical Interview"] == "technical_interview"
    assert pia._CATEGORY_TO_SUB_TYPE["Client Screen"] == "client_screen"


def test_sub_classifier_reads_the_new_categories():
    for cat in ("Technical Interview", "Client Screen", "Job Machine"):
        assert si.is_interview_related(cat)
    assert not si.is_interview_related("Interview Follow-up")


def test_job_machine_needs_the_sub_classifier_to_call_it_an_interview():
    ok = {"sub_type_source": "subclassifier", "job_machine_sub_type": "interview"}
    assert pia._is_job_machine_interview(ok)
    assert pia._is_job_machine_interview({**ok, "job_machine_sub_type": "cancellation"})
    assert not pia._is_job_machine_interview({**ok, "job_machine_sub_type": "job_alert"})
    assert not pia._is_job_machine_interview({**ok, "sub_type_source": "category_fallback"})


def test_job_machine_that_is_not_an_interview_makes_no_event(monkeypatch):
    monkeypatch.setattr(pia, "get_db_session", lambda: object())
    monkeypatch.setattr(pia, "_build_sub_classification", lambda e, c: {
        "interview_sub_type": "Job Machine", "sub_type_source": "category_fallback"})
    cls = {"category": "Job Machine", "confidence": 0.9, "extracted_data": {}}
    assert pia.process_interview_email({"subject": "New jobs"}, 1, cls) is False
    assert cls.get("_not_an_interview") is True


def test_job_alert_still_creates_no_event():
    assert not pia.creates_interview_event({"category": "Job Alert", "confidence": 0.99})


# --- retired categories are re-filed by interview type ---------------------------------------------------------------

def test_schedule_becomes_interview_request():
    assert ce.remap_retired_category("Interview Schedule", {}, {}) == "Interview Request"


def test_confirmation_is_filed_by_type():
    r = ce.remap_retired_category
    assert r("Interview Confirmation", {"interview_type": "technical"}, {"subject": "Confirmed"}) == "Technical Interview"
    assert r("Interview Confirmation", {}, {"subject": "Client interview confirmed", "body_content": ""}) == "Client Screen"
    assert r("Final Interview Scheduled", {"interview_type": "phone"}, {"subject": "x"}) == "Phone Screen"
    assert r("Interview Confirmation", {}, {"subject": "Confirmed", "body_content": "see you then"}) == "Interview Request"


def test_other_categories_are_never_remapped():
    for cat in ("Job Alert", "Phone Screen", "Offer", "Other", "Interview Request"):
        assert ce.remap_retired_category(cat, {}, {"subject": "client technical phone"}) == cat


def _rules(monkeypatch, mode, category="Interview Confirmation"):
    monkeypatch.setenv("CATEGORY_REMAP_MODE", mode)
    c = {"category": category, "confidence": 0.95, "edge_case": {}, "extracted_data": {"interview_type": "technical"}}
    return ce.apply_business_rules(c, email_data={"sender_email": "a@b.com", "subject": "x"})


def test_shadow_mode_only_records_the_new_label(monkeypatch):
    r = _rules(monkeypatch, "shadow")
    assert r["category"] == "Interview Confirmation" and r["category_shadow"] == "Technical Interview"


def test_live_mode_uses_the_new_label(monkeypatch):
    r = _rules(monkeypatch, "live")
    assert r["category"] == "Technical Interview" and r["category_original"] == "Interview Confirmation"


def test_off_mode_changes_nothing(monkeypatch):
    r = _rules(monkeypatch, "off")
    assert r["category"] == "Interview Confirmation" and "category_shadow" not in r


def test_assessment_notice_says_test_not_interview_and_asks_for_done():
    import email_templates as et
    t = et.get_template_by_id("next_round_assessment")
    assert "not an interview" in t.body_template and '"done"' in t.body_template
    assert "assessment" in t.subject_template.lower()
