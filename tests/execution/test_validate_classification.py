"""
Unit tests for validate_classification.py

Comprehensive testing of classification validation logic.
"""

import pytest
from execution.validate_classification import (
    validate_structure,
    validate_business_rules,
    validate_data_extraction,
    validate_classification,
    validate_and_report,
    _is_valid_date_format,
    _is_valid_time_format,
    ValidationError,
    APPROVED_CATEGORIES,
    APPROVED_EDGE_CASE_TYPES
)


class TestValidateStructure:
    """Test structural validation."""

    def test_valid_classification(self):
        """Test that valid classification passes structure validation."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Clear interview request with explicit language",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "company_name": "TechCorp",
                "position_title": "Software Engineer"
            }
        }

        errors = validate_structure(classification)

        assert len(errors) == 0

    def test_missing_required_field(self):
        """Test that missing required fields are detected."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            # Missing: requires_manual_review, reasoning, edge_case, extracted_data
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("requires_manual_review" in error for error in errors)
        assert any("reasoning" in error for error in errors)

    def test_invalid_category(self):
        """Test that invalid category is detected."""
        classification = {
            "category": "Invalid Category",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("Invalid category" in error for error in errors)

    def test_confidence_out_of_range(self):
        """Test that confidence outside 0-1 range is detected."""
        classification = {
            "category": "Interview Request",
            "confidence": 1.5,  # Invalid: > 1.0
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("between 0.0 and 1.0" in error for error in errors)

    def test_confidence_negative(self):
        """Test that negative confidence is detected."""
        classification = {
            "category": "Interview Request",
            "confidence": -0.1,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("between 0.0 and 1.0" in error for error in errors)

    def test_confidence_wrong_type(self):
        """Test that non-numeric confidence is detected."""
        classification = {
            "category": "Interview Request",
            "confidence": "high",  # Should be float
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("must be a number" in error for error in errors)

    def test_requires_manual_review_wrong_type(self):
        """Test that non-boolean requires_manual_review is detected."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": "yes",  # Should be bool
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("must be boolean" in error for error in errors)

    def test_empty_reasoning(self):
        """Test that empty reasoning is detected."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "   ",  # Empty/whitespace only
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("cannot be empty" in error for error in errors)

    def test_invalid_edge_case_type(self):
        """Test that invalid edge case type is detected."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": True,
                "type": "invalid-type",  # Not in approved list
                "confidence": 0.9,
                "reasoning": "Test"
            },
            "extracted_data": {}
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("Invalid edge_case.type" in error for error in errors)

    def test_edge_case_missing_field(self):
        """Test that missing edge_case fields are detected."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                # Missing: type, confidence, reasoning
            },
            "extracted_data": {}
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("Missing edge_case field" in error for error in errors)

    def test_extracted_data_unexpected_field(self):
        """Test that unexpected extracted_data fields trigger warning."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "unknown_field": "value"  # Not in expected fields
            }
        }

        errors = validate_structure(classification)

        assert len(errors) > 0
        assert any("Unexpected extracted_data fields" in error for error in errors)


class TestValidateBusinessRules:
    """Test business rule validation."""

    def test_low_confidence_without_manual_review(self):
        """Test warning for low confidence without manual review flag."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.65,
            "requires_manual_review": False,  # Should be True
            "reasoning": "Uncertain classification",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        warnings = validate_business_rules(classification)

        assert len(warnings) > 0
        assert any("Low confidence" in warning for warning in warnings)

    def test_other_category_without_manual_review(self):
        """Test warning for 'Other' category without manual review."""
        classification = {
            "category": "Other",
            "confidence": 0.80,
            "requires_manual_review": False,  # Should be True
            "reasoning": "Unclear intent",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        warnings = validate_business_rules(classification)

        assert len(warnings) > 0
        assert any("Category 'Other'" in warning for warning in warnings)

    def test_edge_case_without_manual_review(self):
        """Test warning for edge case without manual review."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.85,
            "requires_manual_review": False,  # Should be True
            "reasoning": "Multi-intent detected",
            "edge_case": {
                "is_edge_case": True,
                "type": "multi-intent",
                "confidence": 0.9,
                "reasoning": "Contains both request and confirmation"
            },
            "extracted_data": {}
        }

        warnings = validate_business_rules(classification)

        assert len(warnings) > 0
        assert any("Edge case detected" in warning for warning in warnings)

    def test_high_confidence_short_reasoning(self):
        """Test warning for high confidence with insufficient reasoning."""
        classification = {
            "category": "Interview Schedule",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Clear",  # Too short
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        warnings = validate_business_rules(classification)

        assert len(warnings) > 0
        assert any("detailed reasoning" in warning for warning in warnings)

    def test_interview_schedule_missing_date(self):
        """Test warning for Interview Schedule without date."""
        classification = {
            "category": "Interview Schedule",
            "confidence": 0.90,
            "requires_manual_review": False,
            "reasoning": "Interview scheduled",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                # Missing interview_date
                "company_name": "TechCorp"
            }
        }

        warnings = validate_business_rules(classification)

        assert len(warnings) > 0
        assert any("extract interview_date" in warning for warning in warnings)

    def test_offer_low_confidence(self):
        """Test warning for Offer classification with low confidence."""
        classification = {
            "category": "Offer",
            "confidence": 0.75,  # Should be >= 0.85
            "requires_manual_review": False,
            "reasoning": "Possible offer",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        warnings = validate_business_rules(classification)

        assert len(warnings) > 0
        assert any("Offer classification" in warning for warning in warnings)


class TestValidateDataExtraction:
    """Test data extraction validation."""

    def test_valid_date_format(self):
        """Test that valid date format passes."""
        classification = {
            "category": "Interview Schedule",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "interview_date": "2024-01-15"
            }
        }

        issues = validate_data_extraction(classification)

        assert len(issues) == 0

    def test_invalid_date_format(self):
        """Test that invalid date format is detected."""
        classification = {
            "category": "Interview Schedule",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "interview_date": "01/15/2024"  # Wrong format
            }
        }

        issues = validate_data_extraction(classification)

        assert len(issues) > 0
        assert any("YYYY-MM-DD format" in issue for issue in issues)

    def test_valid_time_format(self):
        """Test that valid time format passes."""
        classification = {
            "category": "Interview Schedule",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "interview_time": "14:30"
            }
        }

        issues = validate_data_extraction(classification)

        assert len(issues) == 0

    def test_invalid_time_format(self):
        """Test that invalid time format is detected."""
        classification = {
            "category": "Interview Schedule",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "interview_time": "2:30 PM"  # Wrong format
            }
        }

        issues = validate_data_extraction(classification)

        assert len(issues) > 0
        assert any("HH:MM format" in issue for issue in issues)

    def test_valid_interview_type(self):
        """Test that valid interview types pass."""
        for valid_type in ["phone", "video", "in-person", "technical"]:
            classification = {
                "category": "Interview Schedule",
                "confidence": 0.95,
                "requires_manual_review": False,
                "reasoning": "Test",
                "edge_case": {
                    "is_edge_case": False,
                    "type": None,
                    "confidence": 1.0,
                    "reasoning": ""
                },
                "extracted_data": {
                    "interview_type": valid_type
                }
            }

            issues = validate_data_extraction(classification)
            assert len(issues) == 0

    def test_invalid_interview_type(self):
        """Test that invalid interview type is detected."""
        classification = {
            "category": "Interview Schedule",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "interview_type": "zoom-call"  # Invalid
            }
        }

        issues = validate_data_extraction(classification)

        assert len(issues) > 0
        assert any("interview_type" in issue for issue in issues)

    def test_valid_email_format(self):
        """Test that valid email passes."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "contact_email": "hr@company.com"
            }
        }

        issues = validate_data_extraction(classification)

        assert len(issues) == 0

    def test_invalid_email_format(self):
        """Test that invalid email is detected."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "contact_email": "not-an-email"
            }
        }

        issues = validate_data_extraction(classification)

        assert len(issues) > 0
        assert any("email appears invalid" in issue for issue in issues)


class TestIsValidDateFormat:
    """Test date format validation helper."""

    def test_valid_dates(self):
        """Test various valid date formats."""
        valid_dates = [
            "2024-01-15",
            "2024-12-31",
            "2025-06-01",
            "1999-01-01"
        ]

        for date_str in valid_dates:
            assert _is_valid_date_format(date_str) is True

    def test_invalid_date_formats(self):
        """Test invalid date formats."""
        invalid_dates = [
            "01/15/2024",  # Wrong separator
            "2024-1-15",   # Missing zero padding
            "2024-13-01",  # Invalid month
            "2024-00-01",  # Invalid month
            "2024-01-32",  # Invalid day
            "2024-01-00",  # Invalid day
            "24-01-15",    # Wrong year format
            "not-a-date",  # Not a date
        ]

        for date_str in invalid_dates:
            assert _is_valid_date_format(date_str) is False


class TestIsValidTimeFormat:
    """Test time format validation helper."""

    def test_valid_times(self):
        """Test various valid time formats."""
        valid_times = [
            "00:00",
            "09:30",
            "14:45",
            "23:59"
        ]

        for time_str in valid_times:
            assert _is_valid_time_format(time_str) is True

    def test_invalid_time_formats(self):
        """Test invalid time formats."""
        invalid_times = [
            "9:30",      # Missing zero padding
            "14:5",      # Missing zero padding
            "24:00",     # Invalid hour
            "14:60",     # Invalid minute
            "2:30 PM",   # 12-hour format
            "not-time",  # Not a time
        ]

        for time_str in invalid_times:
            assert _is_valid_time_format(time_str) is False


class TestValidateClassification:
    """Test comprehensive validation function."""

    def test_valid_classification_passes(self):
        """Test that fully valid classification passes."""
        classification = {
            "category": "Interview Schedule",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Clear interview schedule with date and time provided",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {
                "company_name": "TechCorp",
                "interview_date": "2024-01-15",
                "interview_time": "14:00",
                "interview_type": "video"
            }
        }

        is_valid, errors, warnings = validate_classification(classification)

        assert is_valid is True
        assert len(errors) == 0

    def test_structural_errors_fail_validation(self):
        """Test that structural errors cause validation failure."""
        classification = {
            "category": "Invalid Category",  # Error
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        is_valid, errors, warnings = validate_classification(classification)

        assert is_valid is False
        assert len(errors) > 0

    def test_warnings_dont_fail_non_strict(self):
        """Test that warnings don't fail validation in non-strict mode."""
        classification = {
            "category": "Other",
            "confidence": 0.80,
            "requires_manual_review": False,  # Warning: should be True
            "reasoning": "Unclear intent",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        is_valid, errors, warnings = validate_classification(classification, strict=False)

        assert is_valid is True  # Passes in non-strict mode
        assert len(errors) == 0
        assert len(warnings) > 0

    def test_warnings_fail_strict_mode(self):
        """Test that warnings fail validation in strict mode."""
        classification = {
            "category": "Other",
            "confidence": 0.80,
            "requires_manual_review": False,  # Warning: should be True
            "reasoning": "Unclear intent",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        is_valid, errors, warnings = validate_classification(classification, strict=True)

        assert is_valid is False  # Fails in strict mode
        assert len(warnings) > 0


class TestValidateAndReport:
    """Test validation with logging."""

    def test_valid_classification_returns_true(self):
        """Test that valid classification returns True."""
        classification = {
            "category": "Interview Request",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Clear interview request with explicit scheduling language",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        result = validate_and_report(classification)

        assert result is True

    def test_invalid_classification_returns_false(self):
        """Test that invalid classification returns False."""
        classification = {
            "category": "Invalid",
            "confidence": 0.95,
            "requires_manual_review": False,
            "reasoning": "Test",
            "edge_case": {
                "is_edge_case": False,
                "type": None,
                "confidence": 1.0,
                "reasoning": ""
            },
            "extracted_data": {}
        }

        result = validate_and_report(classification)

        assert result is False


class TestConstants:
    """Test constant definitions."""

    def test_approved_categories_count(self):
        """Test that we have 16 approved categories (14 + Technical Interview, Interview Follow-up)."""
        assert len(APPROVED_CATEGORIES) == 16

    def test_approved_edge_case_types_include_none(self):
        """Test that None is in approved edge case types."""
        assert None in APPROVED_EDGE_CASE_TYPES

    def test_no_duplicate_categories(self):
        """Test no duplicate categories."""
        assert len(APPROVED_CATEGORIES) == len(set(APPROVED_CATEGORIES))
