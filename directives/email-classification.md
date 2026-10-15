# Directive: Email Classification and Data Extraction

## Goal
Automatically classify incoming job-related emails into standardized categories and extract structured data to support interview tracking, student notifications, and operational reporting.

## Context
Colaberry processes hundreds of job-related emails weekly. Manual processing takes ~5 minutes per email. This system aims to reduce processing time to <30 seconds with 95%+ accuracy by using AI classification while maintaining human oversight for edge cases.

## Inputs
- **email_subject**: Email subject line
- **email_sender**: Sender email address
- **sender_name**: Sender display name (if available)
- **email_date**: Email received timestamp
- **email_body**: Full email body content (plain text or HTML)

## Outputs
- **classification_result**: JSON object containing:
  - Category (one of 14 approved categories)
  - Confidence score (0.0 to 1.0)
  - Manual review flag
  - Reasoning for classification
  - Edge case detection
  - Extracted structured data

## Categories (14 Total)

### Primary Categories
1. **Interview Request** - Company requesting to schedule an interview
2. **Interview Schedule** - Confirmed interview with date/time
3. **Interview Reschedule** - Request to change existing interview
4. **Interview Cancelled** - Interview explicitly cancelled. A cancelled *role* with no interview mentioned (e.g. "the role has been cancelled") is a **Rejection**, not this: `role_cancelled_not_interview` in `execution/classify_email.py` re-files it, so it makes no interview event, student notice or alert.
5. **Final Interview Scheduled** - Last round interview confirmation
6. **Rejection** - Candidate not selected
7. **Job Alert** - Automated job posting notification
8. **Application Notification** - Application receipt confirmation
9. **More Information Request** - Company needs additional documents/info
10. **Offer** - Job offer extended
11. **Background Check** - Background/reference check request
12. **Assessment** - Request to complete test/assessment
13. **Phone Screen** - Initial phone screening request
14. **Other** - Does not fit above categories (always requires manual review)

## Steps

### 1. Prepare Email Input
- Sanitize email content (remove excessive whitespace, decode HTML entities)
- Extract plain text from HTML if needed
- Validate required fields are present (subject, sender, body)

### 2. Call Classification API
- Use Claude API with production classification prompt
- Pass email data in standardized format
- Set appropriate timeout (30 seconds)
- Handle API errors gracefully

### 3. Validate Response
- Ensure response is valid JSON
- Verify category matches approved list
- Check confidence score is between 0.0 and 1.0
- Validate extracted data fields

### 4. Apply Business Rules
- Flag for manual review if confidence < 0.70
- Flag for manual review if category is "Other"
- Flag for manual review if edge case detected
- Flag for priority if time-sensitive

### 5. Return Structured Result
- Return validated classification JSON
- Include all extracted data fields
- Preserve original email metadata
- Add processing timestamp

## Edge Cases

### Multi-Intent Emails
- **Scenario**: Email contains multiple distinct purposes (e.g., "Your application was received AND we'd like to schedule an interview")
- **Handling**: Choose primary intent based on required action, flag secondary intent in edge_case reasoning, require manual review

### Unclear Intent
- **Scenario**: Cannot determine primary intent with confidence >0.70
- **Handling**: Label as "Other", set requires_manual_review: true, provide reasoning

### Email Chains
- **Scenario**: Part of ongoing thread (Re: Re: Re:) without clear standalone context
- **Handling**: Extract what's possible from current message, flag for context review

### Spam/Irrelevant
- **Scenario**: Marketing spam, phishing, unrelated content
- **Handling**: Label as "Other", note spam in reasoning, require manual review

### Non-English Content
- **Scenario**: Email primarily in another language
- **Handling**: Note language in edge_case, attempt classification if possible, flag for review

### Time-Sensitive
- **Scenario**: Interview in <24 hours, expiring offer, urgent action required
- **Handling**: Classify correctly, set edge_case.type: "time-sensitive" for priority handling

### Missing Critical Data
- **Scenario**: Category is clear (e.g., Interview Schedule) but critical data missing (no date/time)
- **Handling**: Classify correctly, flag missing data in edge_case reasoning, require manual review

## Safety Constraints

- **Never modify original email content** - Preserve exact wording for audit trail
- **Never process production emails in test environment** - Always check ENVIRONMENT variable
- **Always validate API responses** - Never trust unvalidated external input
- **Always log classification attempts** - Include email ID, category, confidence for auditing
- **Never expose sensitive data in logs** - Redact email addresses and personal info in non-production logs
- **Always require human review for low confidence** - Never auto-process if confidence < 0.70

## Confidence Calibration

### High Confidence (0.95-1.0)
- Explicit category keywords present
- Clear, unambiguous intent
- All key data fields populated
- Action: Auto-process (no manual review unless other flags present)

### Medium-High Confidence (0.85-0.94)
- Strong signals present
- Minor ambiguity in wording
- Most data fields populated
- Action: Auto-process with post-processing audit

### Medium Confidence (0.70-0.84)
- Moderate signals present
- Some ambiguity
- Partial data present
- Action: Auto-process but flag for audit

### Low Confidence (<0.70)
- Weak signals or unclear intent
- Significant ambiguity
- Limited data available
- Action: **REQUIRE MANUAL REVIEW**

## Data Extraction Rules

### Extract Only If Confident (>80% certainty)
- company_name: Hiring company (not recruiting agency unless agency is employer)
- position_title: Job title/role
- contact_name: HR/recruiter name
- contact_email: Contact email address
- interview_date: Date in ISO 8601 format (YYYY-MM-DD)
- interview_time: Time in 24-hour format (HH:MM)
- interview_timezone: Timezone abbreviation (EST, PST, etc.)
- interview_type: "phone" | "video" | "in-person" | "technical"
- interview_location: Physical address or video link
- action_required: What candidate must do (1 sentence summary)
- deadline: Action deadline if specified (ISO 8601)

### Use null for Missing/Uncertain Fields
- Never guess or hallucinate data
- If uncertain, set field to null
- Explain in reasoning if critical data is missing

## Related Scripts

- `execution/classify_email.py` - Main classification logic and API integration
- `execution/validate_classification.py` - JSON validation and business rule checks
- `tests/execution/test_classify_email.py` - Unit tests for classification
- `tests/execution/test_validate_classification.py` - Tests for validation logic

## Monitoring & Success Metrics

### Target Metrics
- **Classification Accuracy**: 95%+ correct category assignment
- **Processing Time**: <30 seconds per email
- **Manual Review Rate**: <20% of emails
- **False Positive Rate**: <5% (incorrect auto-classification)

### Logging Requirements
- Log every classification attempt
- Track confidence score distribution
- Monitor manual review rate by category
- Alert if accuracy drops below 90%
- Track API latency and errors

## Testing Strategy

### Unit Tests
- Test with example emails for each of 14 categories
- Test confidence scoring logic
- Test edge case detection
- Test JSON validation
- Mock Claude API responses

### Integration Tests
- Test full classification pipeline
- Use real example emails (anonymized)
- Verify data extraction accuracy
- Test error handling and retries

### Manual Review Tests
- Periodic human validation of auto-classified emails
- Track disagreement rate
- Update prompts based on failure patterns

## Self-Annealing Loop

When classification fails or produces incorrect results:

1. **Identify root cause**: Was it prompt ambiguity? Missing training example? Edge case?
2. **Fix the system**: Update classification prompt, add test case, improve validation
3. **Add tests**: Ensure this failure type is covered
4. **Update this directive**: Document new edge case or handling rule
5. **Verify improvement**: Run full test suite, check metrics

Classification failures are learning opportunities to strengthen the system.

## Production Deployment Checklist

Before deploying to production:
- [ ] All unit tests pass
- [ ] Integration tests pass with >95% accuracy
- [ ] Manual review threshold validated (confidence < 0.70)
- [ ] API error handling tested
- [ ] Logging configured and working
- [ ] Monitoring alerts configured
- [ ] Human review process established
- [ ] Rollback plan documented

## Revision History

- **v1.0** (2026-01-27): Initial directive created with 14 categories and production prompt
