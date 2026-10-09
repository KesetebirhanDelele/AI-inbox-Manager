"""
Unit tests for classify_email.py

Demonstrates comprehensive testing of email classification logic
with mocked API calls and various edge cases.
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from execution.classify_email import (
    format_email_for_prompt,
    parse_classification_response,
    apply_business_rules,
    classify_email,
    load_email_from_file,
    save_classification_result,
    APPROVED_CATEGORIES,
    call_claude_api
)


class TestFormatEmailForPrompt:
    """Test prompt formatting."""

    def test_format_complete_email(self):
        """Test formatting email with all fields."""
        email_data = {
            "subject": "Interview Invitation",
            "sender_email": "hr@company.com",
            "sender_name": "Jane Smith",
            "email_date": "2024-01-15",
            "body_content": "We'd like to schedule an interview."
        }

        prompt = format_email_for_prompt(email_data)

        assert "Subject: Interview Invitation" in prompt
        assert "From: hr@company.com" in prompt
        assert "Sender Name: Jane Smith" in prompt
        assert "We'd like to schedule an interview." in prompt

    def test_format_minimal_email(self):
        """Test formatting with minimal fields."""
        email_data = {
            "subject": "Test",
            "body_content": "Test content"
        }

        prompt = format_email_for_prompt(email_data)

        assert "Subject: Test" in prompt
        assert "Test content" in prompt
        # Should handle missing optional fields gracefully
        assert "From:" in prompt


class TestParseClassificationResponse:
    """Test JSON response parsing."""

    def test_parse_valid_json(self):
        """Test parsing valid JSON response."""
        response_text = json.dumps({
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Clear interview request",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        })

        result = parse_classification_response(response_text)

        assert result["category"] == "Interview Request"
        assert result["confidence"] == 0.95

    def test_parse_json_with_markdown(self):
        """Test parsing JSON wrapped in markdown code blocks."""
        json_content = {
            "category": "Other",
            "confidence": 0.5,
            "requires_manual_review": True,
            "reasoning": "Test",
            "edge_case": {"is_edge_case": False, "type": None, "confidence": 1.0, "reasoning": ""},
            "extracted_data": {}
        }
        response_text = f"```json\n{json.dumps(json_content)}\n```"

        result = parse_classification_response(response_text)

        assert result["category"] == "Other"

    def test_parse_json_with_backticks(self):
        """Test parsing JSON with generic backticks."""
        json_content = {"category": "Other", "confidence": 0.5, "requires_manual_review": True,
                       "reasoning": "Test", "edge_case": {"is_edge_case": False, "type": None,
                       "confidence": 1.0, "reasoning": ""}, "extracted_data": {}}
        response_text = f"```\n{json.dumps(json_content)}\n```"

        result = parse_classification_response(response_text)

        assert result["category"] == "Other"

    def test_parse_invalid_json(self):
        """Test that invalid JSON raises JSONDecodeError."""
        response_text = "This is not JSON"

        with pytest.raises(json.JSONDecodeError):
            parse_classification_response(response_text)


class TestApplyBusinessRules:
    """Test business rule application."""

    def test_low_confidence_flags_manual_review(self):
        """Test that confidence < 0.70 triggers manual review."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.65,
            "requires_manual_review": False,
            "reasoning": "Uncertain",
            "edge_case": {"is_edge_case": False, "type": None, "confidence": 1.0, "reasoning": ""},
            "extracted_data": {}
        }

        result = apply_business_rules(classification)

        assert result["requires_manual_review"] is True

    def test_high_confidence_no_manual_review(self):
        """Test that high confidence doesn't auto-flag review."""
        classification = {
            "category": "Interview Schedule",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Clear schedule",
            "edge_case": {"is_edge_case": False, "type": None, "confidence": 1.0, "reasoning": ""},
            "extracted_data": {}
        }

        result = apply_business_rules(classification)

        assert result["requires_manual_review"] is False

    def test_other_category_flags_manual_review(self):
        """Test that 'Other' category always requires review."""
        classification = {
            "category": "Other",
            "confidence": 0.80,
            "requires_manual_review": False,
            "reasoning": "Unclear",
            "edge_case": {"is_edge_case": False, "type": None, "confidence": 1.0, "reasoning": ""},
            "extracted_data": {}
        }

        result = apply_business_rules(classification)

        assert result["requires_manual_review"] is True

    def test_edge_case_flags_manual_review(self):
        """Test that edge cases trigger manual review."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.85,
            "requires_manual_review": False,
            "reasoning": "Multi-intent detected",
            "edge_case": {
                "is_edge_case": True,
                "type": "multi-intent",
                "confidence": 0.9,
                "reasoning": "Contains both application and interview request"
            },
            "extracted_data": {}
        }

        result = apply_business_rules(classification)

        assert result["requires_manual_review"] is True

    def test_adds_processing_timestamp(self):
        """Test that processing timestamp is added."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Clear",
            "edge_case": {"is_edge_case": False, "type": None, "confidence": 1.0, "reasoning": ""},
            "extracted_data": {}
        }

        result = apply_business_rules(classification)

        assert "processing_timestamp" in result
        assert result["processing_timestamp"].endswith("Z")

    def test_does_not_mutate_input(self):
        """Test that original classification is not mutated."""
        classification = {
            "category": "Other",
            "confidence": 0.50,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {"is_edge_case": False, "type": None, "confidence": 1.0, "reasoning": ""},
            "extracted_data": {}
        }

        result = apply_business_rules(classification)

        # Original should not have processing_timestamp
        assert "processing_timestamp" not in classification
        # But result should
        assert "processing_timestamp" in result

    # ── Sender-domain enforcement tests ──────────────────────────────────────

    def _base_classification(self, category: str) -> dict:
        return {
            "category": category,
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "AI decision",
            "edge_case": {"is_edge_case": False, "type": None, "confidence": 1.0, "reasoning": ""},
            "extracted_data": {},
        }

    def test_gmail_notification_non_google_sender_overridden(self):
        """AI returning Gmail Notification for a non-Google sender must be corrected to Other."""
        classification = self._base_classification("Gmail Notification")
        email_data = {"sender_email": "noreply@indeed.com", "subject": "New jobs for you"}

        result = apply_business_rules(classification, email_data=email_data)

        assert result["category"] == "Other"
        assert result["requires_manual_review"] is True

    def test_gmail_notification_google_sender_kept(self):
        """Gmail Notification from an official Google domain should not be overridden."""
        classification = self._base_classification("Gmail Notification")
        email_data = {"sender_email": "no-reply@accounts.google.com", "subject": "Security alert"}

        result = apply_business_rules(classification, email_data=email_data)

        assert result["category"] == "Gmail Notification"

    def test_gmail_notification_google_com_sender_kept(self):
        """Gmail Notification from @google.com should not be overridden."""
        classification = self._base_classification("Gmail Notification")
        email_data = {"sender_email": "noreply@google.com", "subject": "Gmail forwarding confirmation"}

        result = apply_business_rules(classification, email_data=email_data)

        assert result["category"] == "Gmail Notification"

    def test_linkedin_notification_non_linkedin_sender_overridden(self):
        """AI returning LinkedIn Notification for a non-LinkedIn sender must be corrected."""
        classification = self._base_classification("LinkedIn Notification")
        email_data = {"sender_email": "recruiter@ziprecruiter.com", "subject": "Job match for you"}

        result = apply_business_rules(classification, email_data=email_data)

        assert result["category"] == "Other"
        assert result["requires_manual_review"] is True

    def test_linkedin_notification_linkedin_sender_kept(self):
        """LinkedIn Notification from @e.linkedin.com should not be overridden."""
        classification = self._base_classification("LinkedIn Notification")
        email_data = {"sender_email": "jobs-noreply@linkedin.com", "subject": "You have a new connection"}

        result = apply_business_rules(classification, email_data=email_data)

        assert result["category"] == "LinkedIn Notification"

    def test_domain_override_uses_from_key_fallback(self):
        """Domain override should fall back to 'from' key when sender_email is absent."""
        classification = self._base_classification("Gmail Notification")
        email_data = {"from": "promo@retailer.com", "subject": "Sale today"}

        result = apply_business_rules(classification, email_data=email_data)

        assert result["category"] == "Other"

    def test_no_email_data_skips_domain_check(self):
        """Without email_data, domain enforcement is skipped (backward compat)."""
        classification = self._base_classification("Gmail Notification")

        result = apply_business_rules(classification)  # no email_data

        assert result["category"] == "Gmail Notification"


class TestClassifyEmail:
    """Test main classification function."""

    def test_classify_with_validate_only(self):
        """Test classification in validate-only mode (no API call)."""
        email_data = {
            "subject": "Test Subject",
            "body_content": "Test content",
            "sender_email": "test@example.com"
        }

        result = classify_email(email_data, validate_only=True)

        assert result["category"] == "Other"
        assert result["requires_manual_review"] is True
        assert "processing_timestamp" in result
        assert "email_metadata" in result

    def test_classify_missing_required_fields(self):
        """Test that missing required fields raises ValueError."""
        email_data = {
            "sender_email": "test@example.com"
            # Missing subject and body_content
        }

        with pytest.raises(ValueError, match="Missing required fields"):
            classify_email(email_data, validate_only=True)

    @patch('execution.classify_email.call_claude_api')
    def test_classify_with_api_call(self, mock_api):
        """Test classification with mocked API call."""
        # Mock API response
        mock_api.return_value = {
            "response": json.dumps({
                "category": "Interview Schedule",
                "confidence": 0.98,
                "requires_manual_review": False,
                "reasoning": "Clear interview schedule with date and time",
                "edge_case": {
                    "is_edge_case": False,
                    "type": None,
                    "confidence": 1.0,
                    "reasoning": ""
                },
                "extracted_data": {
                    "company_name": "TechCorp",
                    "interview_date": "2024-01-15",
                    "interview_time": "14:00"
                }
            }),
            "usage": {"input_tokens": 100, "output_tokens": 50}
        }

        email_data = {
            "subject": "Interview Scheduled",
            "body_content": "Your interview is on Jan 15 at 2 PM",
            "sender_email": "hr@techcorp.com"
        }

        result = classify_email(email_data, api_key="test-key", validate_only=False)

        # Verify API was called
        mock_api.assert_called_once()

        # Verify result
        assert result["category"] == "Interview Schedule"
        assert result["confidence"] == 0.98
        assert result["extracted_data"]["company_name"] == "TechCorp"

    @patch('execution.classify_email.call_claude_api')
    def test_classify_handles_api_error(self, mock_api):
        """Test that API errors are propagated."""
        mock_api.side_effect = RuntimeError("API Error")

        email_data = {
            "subject": "Test",
            "body_content": "Test content"
        }

        with pytest.raises(RuntimeError, match="API Error"):
            classify_email(email_data, api_key="test-key", validate_only=False)


class TestCallClaudeAPI:
    """Test OpenAI API calling function."""

    def test_call_api_missing_key(self):
        """Test that missing API key raises ValueError."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="OPENAI_API_KEY not found"):
                call_claude_api("test prompt", api_key=None)

    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'})
    def test_call_api_success(self):
        """Test successful API call with mocked openai."""
        # We need to import and patch at the right level
        with patch('builtins.__import__') as mock_import:
            # Create mock openai module
            mock_openai = MagicMock()
            mock_client = MagicMock()
            mock_openai.OpenAI.return_value = mock_client

            # Mock the response
            mock_response = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = '{"result": "test"}'
            mock_response.choices = [mock_choice]
            mock_response.usage.prompt_tokens = 100
            mock_response.usage.completion_tokens = 50
            mock_client.chat.completions.create.return_value = mock_response

            # Make __import__ return our mock when 'openai' is imported
            def import_mock(name, *args, **kwargs):
                if name == 'openai':
                    return mock_openai
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = import_mock

            result = call_claude_api("test prompt")

            assert result["response"] == '{"result": "test"}'
            assert "usage" in result

    def test_call_api_library_not_installed(self):
        """Test that missing openai library raises RuntimeError."""
        # Mock the import to raise ImportError
        with patch('builtins.__import__', side_effect=ImportError("No module named 'openai'")):
            with pytest.raises(RuntimeError, match="openai library not installed"):
                call_claude_api("test prompt", api_key="test-key")


class TestLoadEmailFromFile:
    """Test email loading from file."""

    def test_load_valid_email(self, temp_dir):
        """Test loading valid email JSON file."""
        email_file = temp_dir / "email.json"
        email_data = {
            "subject": "Test Email",
            "body_content": "Test content",
            "sender_email": "test@example.com"
        }

        with open(email_file, 'w', encoding='utf-8') as f:
            json.dump(email_data, f)

        result = load_email_from_file(email_file)

        assert result == email_data

    def test_load_nonexistent_file(self, temp_dir):
        """Test that loading non-existent file raises FileNotFoundError."""
        missing_file = temp_dir / "missing.json"

        with pytest.raises(FileNotFoundError):
            load_email_from_file(missing_file)


class TestSaveClassificationResult:
    """Test saving classification results."""

    def test_save_creates_file(self, temp_dir):
        """Test that save creates the output file."""
        output_file = temp_dir / "result.json"
        result = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False
        }

        save_classification_result(result, output_file)

        assert output_file.exists()
        with open(output_file, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        assert saved_data == result

    def test_save_creates_directory(self, temp_dir):
        """Test that save creates parent directories."""
        output_file = temp_dir / "nested" / "dir" / "result.json"
        result = {"category": "Other"}

        save_classification_result(result, output_file)

        assert output_file.exists()
        assert output_file.parent.exists()

    def test_save_handles_unicode(self, temp_dir):
        """Test that save handles Unicode characters correctly."""
        output_file = temp_dir / "unicode.json"
        result = {
            "category": "Interview Request",
            "extracted_data": {
                "company_name": "Café München"
            }
        }

        save_classification_result(result, output_file)

        with open(output_file, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        assert saved_data["extracted_data"]["company_name"] == "Café München"


class TestApprovedCategories:
    """Test category constants."""

    def test_approved_categories_count(self):
        """Test that the approved-category list matches the documented taxonomy."""
        assert len(APPROVED_CATEGORIES) == 27

    def test_approved_categories_no_duplicates(self):
        """Test that there are no duplicate categories."""
        assert len(APPROVED_CATEGORIES) == len(set(APPROVED_CATEGORIES))

    def test_approved_categories_include_other(self):
        """Test that 'Other' is in approved categories."""
        assert "Other" in APPROVED_CATEGORIES


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_full_classification_pipeline_validate_only(self, temp_dir):
        """Test complete pipeline in validate-only mode."""
        # Setup
        input_file = temp_dir / "email.json"
        output_file = temp_dir / "result.json"

        email_data = {
            "subject": "Interview Request",
            "body_content": "We'd like to schedule an interview",
            "sender_email": "hr@company.com",
            "sender_name": "Jane Smith",
            "email_date": "2024-01-15"
        }

        with open(input_file, 'w', encoding='utf-8') as f:
            json.dump(email_data, f)

        # Execute
        loaded_email = load_email_from_file(input_file)
        result = classify_email(loaded_email, validate_only=True)
        save_classification_result(result, output_file)

        # Verify
        assert output_file.exists()
        with open(output_file, 'r', encoding='utf-8') as f:
            saved = json.load(f)

        assert saved["category"] == "Other"  # validate_only always returns Other
        assert saved["requires_manual_review"] is True
        assert "processing_timestamp" in saved
        assert saved["email_metadata"]["subject"] == "Interview Request"

    @patch('execution.classify_email.call_claude_api')
    def test_full_classification_pipeline_with_api(self, mock_api, temp_dir):
        """Test complete pipeline with mocked API."""
        # Mock API response
        mock_api.return_value = {
            "response": json.dumps({
                "category": "Offer",
                "confidence": 0.99,
                "requires_manual_review": False,
                "reasoning": "Clear job offer with compensation details",
                "edge_case": {
                    "is_edge_case": False,
                    "type": None,
                    "confidence": 1.0,
                    "reasoning": ""
                },
                "extracted_data": {
                    "company_name": "TechCorp",
                    "position_title": "Senior Engineer"
                }
            }),
            "usage": {}
        }

        # Setup
        input_file = temp_dir / "offer_email.json"
        output_file = temp_dir / "offer_result.json"

        email_data = {
            "subject": "Job Offer - Senior Engineer",
            "body_content": "We're pleased to offer you the position...",
            "sender_email": "hr@techcorp.com"
        }

        with open(input_file, 'w', encoding='utf-8') as f:
            json.dump(email_data, f)

        # Execute
        loaded_email = load_email_from_file(input_file)
        result = classify_email(loaded_email, api_key="test-key", validate_only=False)
        save_classification_result(result, output_file)

        # Verify
        assert output_file.exists()
        with open(output_file, 'r', encoding='utf-8') as f:
            saved = json.load(f)

        assert saved["category"] == "Offer"
        assert saved["confidence"] == 0.99
        assert saved["requires_manual_review"] is False
        assert saved["extracted_data"]["company_name"] == "TechCorp"
