"""
Classification validation script.

Validates email classification results to ensure they meet structural
and business requirements.

This is pure deterministic logic - no API calls, no I/O mixing.
Easily testable with comprehensive validation rules.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Approved categories (must match classify_email.py)
APPROVED_CATEGORIES = [
    "Interview Request",
    "Interview Schedule",
    "Interview Reschedule",
    "Interview Cancelled",
    "Final Interview Scheduled",
    "Rejection",
    "Job Alert",
    "Application Notification",
    "More Information Request",
    "Offer",
    "Background Check",
    "Assessment",
    "Phone Screen",
    "Technical Interview",
    "Interview Follow-up",
    "Other"
]

# Approved edge case types
APPROVED_EDGE_CASE_TYPES = [
    "multi-intent",
    "unclear",
    "chain",
    "spam",
    "non-english",
    "time-sensitive",
    "missing-critical-data",
    None  # null is valid
]

# Required top-level fields
REQUIRED_FIELDS = [
    "category",
    "confidence",
    "requires_manual_review",
    "reasoning",
    "edge_case",
    "extracted_data"
]

# Required edge_case fields
REQUIRED_EDGE_CASE_FIELDS = [
    "is_edge_case",
    "type",
    "confidence",
    "reasoning"
]

# Optional extracted_data fields (all optional, but must be present)
EXTRACTED_DATA_FIELDS = [
    "company_name",
    "position_title",
    "contact_name",
    "contact_email",
    "interview_date",
    "interview_time",
    "interview_timezone",
    "interview_type",
    "interview_location",
    "action_required",
    "deadline"
]


class ValidationError(Exception):
    """Raised when classification validation fails."""
    pass


def validate_structure(classification: Dict[str, Any]) -> List[str]:
    """
    Validate the structure of classification result.

    Args:
        classification: Classification result dictionary

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Check top-level required fields
    for field in REQUIRED_FIELDS:
        if field not in classification:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors  # Return early if required fields missing

    # Validate category
    category = classification.get("category")
    if category not in APPROVED_CATEGORIES:
        errors.append(
            f"Invalid category: '{category}'. Must be one of: {', '.join(APPROVED_CATEGORIES)}"
        )

    # Validate confidence
    confidence = classification.get("confidence")
    if not isinstance(confidence, (int, float)):
        errors.append(f"Confidence must be a number, got: {type(confidence).__name__}")
    elif not (0.0 <= confidence <= 1.0):
        errors.append(f"Confidence must be between 0.0 and 1.0, got: {confidence}")

    # Validate requires_manual_review
    manual_review = classification.get("requires_manual_review")
    if not isinstance(manual_review, bool):
        errors.append(
            f"requires_manual_review must be boolean, got: {type(manual_review).__name__}"
        )

    # Validate reasoning
    reasoning = classification.get("reasoning")
    if not isinstance(reasoning, str):
        errors.append(f"reasoning must be string, got: {type(reasoning).__name__}")
    elif len(reasoning.strip()) == 0:
        errors.append("reasoning cannot be empty")

    # Validate edge_case structure
    edge_case = classification.get("edge_case")
    if not isinstance(edge_case, dict):
        errors.append(f"edge_case must be dict, got: {type(edge_case).__name__}")
    else:
        for field in REQUIRED_EDGE_CASE_FIELDS:
            if field not in edge_case:
                errors.append(f"Missing edge_case field: {field}")

        # Validate edge case type
        edge_type = edge_case.get("type")
        if edge_type not in APPROVED_EDGE_CASE_TYPES:
            errors.append(
                f"Invalid edge_case.type: '{edge_type}'. "
                f"Must be one of: {', '.join(str(t) for t in APPROVED_EDGE_CASE_TYPES)}"
            )

        # Validate edge case confidence
        edge_confidence = edge_case.get("confidence")
        if edge_confidence is not None:
            if not isinstance(edge_confidence, (int, float)):
                errors.append(
                    f"edge_case.confidence must be a number, got: {type(edge_confidence).__name__}"
                )
            elif not (0.0 <= edge_confidence <= 1.0):
                errors.append(
                    f"edge_case.confidence must be between 0.0 and 1.0, got: {edge_confidence}"
                )

    # Validate extracted_data structure
    extracted_data = classification.get("extracted_data")
    if not isinstance(extracted_data, dict):
        errors.append(
            f"extracted_data must be dict, got: {type(extracted_data).__name__}"
        )
    else:
        # All extracted data fields are optional, but check for unexpected fields
        unexpected_fields = set(extracted_data.keys()) - set(EXTRACTED_DATA_FIELDS)
        if unexpected_fields:
            errors.append(
                f"Unexpected extracted_data fields: {', '.join(unexpected_fields)}"
            )

    return errors


def validate_business_rules(classification: Dict[str, Any]) -> List[str]:
    """
    Validate business rules for classification.

    Args:
        classification: Classification result dictionary

    Returns:
        List of validation warnings (not necessarily errors)
    """
    warnings = []

    # Rule 1: Low confidence should require manual review
    confidence = classification.get("confidence", 0)
    requires_review = classification.get("requires_manual_review", False)

    if confidence < 0.70 and not requires_review:
        warnings.append(
            f"Low confidence ({confidence}) should require manual review"
        )

    # Rule 2: "Other" category should require manual review
    if classification.get("category") == "Other" and not requires_review:
        warnings.append("Category 'Other' should require manual review")

    # Rule 3: Edge cases should require manual review
    edge_case = classification.get("edge_case", {})
    if edge_case.get("is_edge_case", False) and not requires_review:
        warnings.append(
            f"Edge case detected ({edge_case.get('type')}) should require manual review"
        )

    # Rule 4: High confidence classifications should have reasoning
    if confidence > 0.90:
        reasoning = classification.get("reasoning", "")
        if len(reasoning.strip()) < 20:
            warnings.append(
                "High confidence classification should have detailed reasoning"
            )

    # Rule 5: Interview Schedule should have date/time extracted
    if classification.get("category") == "Interview Schedule":
        extracted = classification.get("extracted_data", {})
        if not extracted.get("interview_date"):
            warnings.append(
                "Interview Schedule classification should extract interview_date"
            )

    # Rule 6: Offer classification should be high confidence
    if classification.get("category") == "Offer" and confidence < 0.85:
        warnings.append(
            "Offer classification should have high confidence (>= 0.85)"
        )

    return warnings


def validate_data_extraction(classification: Dict[str, Any]) -> List[str]:
    """
    Validate extracted data fields for consistency.

    Args:
        classification: Classification result dictionary

    Returns:
        List of validation errors/warnings for extracted data
    """
    issues = []
    extracted = classification.get("extracted_data", {})

    # Check date format (YYYY-MM-DD)
    for date_field in ["interview_date", "deadline"]:
        date_value = extracted.get(date_field)
        if date_value is not None:
            if not isinstance(date_value, str):
                issues.append(f"{date_field} must be string, got: {type(date_value).__name__}")
            elif not _is_valid_date_format(date_value):
                issues.append(
                    f"{date_field} must be in YYYY-MM-DD format, got: {date_value}"
                )

    # Check time format (HH:MM)
    time_value = extracted.get("interview_time")
    if time_value is not None:
        if not isinstance(time_value, str):
            issues.append(f"interview_time must be string, got: {type(time_value).__name__}")
        elif not _is_valid_time_format(time_value):
            issues.append(
                f"interview_time must be in HH:MM format, got: {time_value}"
            )

    # Check interview_type values
    interview_type = extracted.get("interview_type")
    valid_types = ["phone", "video", "in-person", "technical", None]
    if interview_type is not None and interview_type not in valid_types:
        issues.append(
            f"interview_type must be one of {valid_types}, got: {interview_type}"
        )

    # Check email format for contact_email
    contact_email = extracted.get("contact_email")
    if contact_email is not None:
        if not isinstance(contact_email, str):
            issues.append(
                f"contact_email must be string, got: {type(contact_email).__name__}"
            )
        elif "@" not in contact_email:
            issues.append(f"contact_email appears invalid: {contact_email}")

    return issues


def _is_valid_date_format(date_str: str) -> bool:
    """
    Check if string is in YYYY-MM-DD format.

    Args:
        date_str: Date string to validate

    Returns:
        True if valid format, False otherwise
    """
    import re
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    if not re.match(pattern, date_str):
        return False

    # Basic validation of ranges
    try:
        year, month, day = date_str.split('-')
        year, month, day = int(year), int(month), int(day)
        if not (1900 <= year <= 2100):
            return False
        if not (1 <= month <= 12):
            return False
        if not (1 <= day <= 31):
            return False
        return True
    except (ValueError, AttributeError):
        return False


def _is_valid_time_format(time_str: str) -> bool:
    """
    Check if string is in HH:MM format (24-hour).

    Args:
        time_str: Time string to validate

    Returns:
        True if valid format, False otherwise
    """
    import re
    pattern = r'^\d{2}:\d{2}$'
    if not re.match(pattern, time_str):
        return False

    try:
        hour, minute = time_str.split(':')
        hour, minute = int(hour), int(minute)
        if not (0 <= hour <= 23):
            return False
        if not (0 <= minute <= 59):
            return False
        return True
    except (ValueError, AttributeError):
        return False


def validate_classification(
    classification: Dict[str, Any],
    strict: bool = False
) -> Tuple[bool, List[str], List[str]]:
    """
    Comprehensive validation of classification result.

    Args:
        classification: Classification result dictionary
        strict: If True, treat warnings as errors

    Returns:
        Tuple of (is_valid, errors, warnings)
        - is_valid: True if classification passes validation
        - errors: List of validation errors
        - warnings: List of validation warnings
    """
    errors = []
    warnings = []

    # Structural validation
    struct_errors = validate_structure(classification)
    errors.extend(struct_errors)

    # Business rule validation
    rule_warnings = validate_business_rules(classification)
    warnings.extend(rule_warnings)

    # Data extraction validation
    data_issues = validate_data_extraction(classification)
    warnings.extend(data_issues)

    # Determine if valid
    if strict:
        is_valid = len(errors) == 0 and len(warnings) == 0
    else:
        is_valid = len(errors) == 0

    return is_valid, errors, warnings


def validate_and_report(classification: Dict[str, Any], strict: bool = False) -> bool:
    """
    Validate classification and log results.

    Args:
        classification: Classification result dictionary
        strict: If True, treat warnings as errors

    Returns:
        True if validation passes, False otherwise
    """
    is_valid, errors, warnings = validate_classification(classification, strict=strict)

    if errors:
        logger.error(f"Classification validation failed with {len(errors)} errors:")
        for error in errors:
            logger.error(f"  - {error}")

    if warnings:
        logger.warning(f"Classification has {len(warnings)} warnings:")
        for warning in warnings:
            logger.warning(f"  - {warning}")

    if is_valid:
        logger.info("Classification validation passed")

    return is_valid


def main() -> None:
    """
    CLI entry point for classification validation.

    Usage:
        python validate_classification.py <classification_file> [--strict]
    """
    import sys
    import json
    from pathlib import Path

    if len(sys.argv) < 2:
        print("Usage: python validate_classification.py <classification_file> [--strict]")
        print("\nValidates a classification result JSON file.")
        print("--strict: Treat warnings as errors")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    strict = "--strict" in sys.argv

    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    try:
        # Load classification
        with open(file_path, 'r', encoding='utf-8') as f:
            classification = json.load(f)

        # Validate
        is_valid, errors, warnings = validate_classification(classification, strict=strict)

        # Report results
        print(f"\nValidation Results for: {file_path.name}")
        print(f"{'=' * 60}")

        if errors:
            print(f"\n❌ ERRORS ({len(errors)}):")
            for error in errors:
                print(f"  - {error}")

        if warnings:
            print(f"\n⚠️  WARNINGS ({len(warnings)}):")
            for warning in warnings:
                print(f"  - {warning}")

        if is_valid:
            print("\n✅ Validation PASSED")
            if warnings:
                print(f"   (with {len(warnings)} warnings)")
        else:
            print("\n❌ Validation FAILED")

        # Exit with appropriate code
        sys.exit(0 if is_valid else 1)

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in file: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
