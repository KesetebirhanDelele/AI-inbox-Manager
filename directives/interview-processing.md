# Directive: Interview Email Processing & Student Notification

## Goal
Automatically process interview-classified emails, sub-classify them by interview type, identify the relevant student, draft a notification to the student's personal email, and either auto-send (high confidence) or queue for human review (lower confidence).

## Context
Colaberry manages job placement for students enrolled in its programs. Students each have an assigned Gmail (e.g., `student.name@gmail.com`) used for job applications, which forwards all received emails to `c_interviews@colaberry.com`. When an interview email arrives, the student needs to be notified on their **personal email** with details and next steps. This directive automates that notification pipeline.

**Key distinction:** Students have two email addresses:
- **Assigned Gmail** - used for job submissions, all forwarded to c_interviews@
- **Personal email** - where interview notifications are sent (stored in Google Drive)

## Inputs
- **email_data**: Email content dictionary (subject, body, from_address, headers)
- **email_db_id**: Database ID of the email in the `emails` table
- **classification**: Prior classification result showing `category = "Interview Request"` (or similar)

## Outputs
- **InterviewEvent**: Database record with sub-classification details
- **NotificationDraft**: Email and WhatsApp notification drafts
- **Send result**: Notification sent automatically (high confidence) or queued for review

## Sub-Classification Types (7 Total)

| Sub-Type | Key Signals |
|----------|-------------|
| Interview Request | "schedule your interview", time slot options, no confirmed date yet |
| Phone Screen | "phone interview scheduled", dial-in instructions, screening call |
| Client Screen | "client interview", "second round", 2+ attendees including client |
| Technical Interview | "technical round", "coding test", "system design", panel interview |
| Interview Cancelled | "cancelled", "will not occur", previously scheduled interview removed |
| Interview Rescheduled | "rescheduled", new date/time replacing a previous schedule |
| Job Machine | From Job Machine platform - further sub-typed as interview/reschedule/cancellation |

## Steps

### 1. Sub-Classify Interview Email
- Call `subclassify_interview()` with email data
- Uses OpenAI GPT-4o with structured JSON output, temperature=0
- Extracts: sub-type, company, position, contact info, interview date/time/format, confidence score
- If sub-classification returns no result, skip the email

### 2. Resolve Student
- Parse email headers for original recipient (Delivered-To, X-Forwarded-To, envelope-to)
- Extract the student's assigned Gmail address from forwarding headers
- Derive `student_username` from the Gmail local part (before @)
- Fallback: scan email body for student name patterns

### 3. Fetch Student Info from Google Drive
- Look up student's folder in shared Google Drive (folder ID: `1VZqhosCZNC4Ni-6jDN6ynpCSpAn1hYn4`)
- Parse the student's spreadsheet for personal email, full name, phone number
- Cache student data for 4 hours to minimize API calls
- Upsert student record in dashboard database

### 4. Log Interview Event
- Create `InterviewEvent` record in dashboard DB
- Store all extracted details: sub-type, company, position, contact, date/time, confidence
- Store raw AI extraction as JSON for audit purposes
- Link to source email and student record

### 5. Draft Notification
- Select email template deterministically based on sub-type + flags (Job Machine, next round, etc.)
- Populate template with extracted data and student info
- Generate short WhatsApp summary message (2-3 sentences)
- Identify missing required fields
- Set draft status: `ready` or `needs_review`

### 6. Auto-Send Decision
- **Auto-send** if ALL conditions met:
  - Confidence >= 0.95
  - All required template fields present
  - Recipient personal email available
  - Draft status is `ready`
- **Queue for review** otherwise
- Log notification draft to database with `auto_send_eligible` flag

### 7. Send or Queue
- If auto-send: send email via Gmail SMTP to student's personal email, BCC c_interviews@
- If queued: save as draft for human review in dashboard inbox view
- Update notification status (sent/queued/failed)

## Edge Cases

### Unknown Student
- **Scenario**: Cannot identify student from email headers or body
- **Handling**: Log interview event without student link, queue notification for manual review with missing recipient

### Missing Personal Email
- **Scenario**: Student found but no personal email in Google Drive spreadsheet
- **Handling**: Draft notification but mark as `needs_review`, flag `recipient_email` as missing

### Job Machine Emails
- **Scenario**: Interview from Job Machine platform (automated scheduling system)
- **Handling**: Detect via sender domain or body patterns, set `is_job_machine = true`, resolve Job Machine sub-type (interview/reschedule/cancellation), route to appropriate template

### Multiple Interviews in One Email
- **Scenario**: Email contains details for multiple interview rounds
- **Handling**: Sub-classify based on primary/next interview, note complexity in extraction, queue for review

### Low Confidence Sub-Classification
- **Scenario**: AI confidence below 0.70 on the sub-type
- **Handling**: Require manual review, do not auto-send, flag in dashboard

### Google Drive Unavailable
- **Scenario**: Drive API error or service account issue
- **Handling**: Continue with what we have (username from headers), mark student info as incomplete, queue for review

### Duplicate Processing
- **Scenario**: Same email processed twice (rerun, retry)
- **Handling**: Check for existing InterviewEvent with same `email_id`, skip if already processed

## Safety Constraints

- **Never send notification to wrong student** - Verify student-email mapping before sending
- **Always BCC c_interviews@colaberry.com** - All outgoing notifications must BCC the main inbox for audit
- **Never auto-send if confidence < 0.95** - Queue for human review instead
- **Never auto-send with missing required fields** - Draft must be complete
- **Never modify original email** - Preserve exact content in database for reference
- **Never expose student personal info in logs** - Redact phone numbers and personal emails in non-production logs
- **Always validate recipient email format** - Check for valid email address before attempting send
- **Never send to assigned Gmail** - Notifications go to personal email only

## Confidence Calibration

### Auto-Send (0.95-1.0)
- Clear interview sub-type
- All required fields extracted
- Student resolved with complete info
- Action: Auto-send notification to personal email

### Auto-Send + Audit (0.80-0.94)
- Strong signals, minor ambiguity
- Most fields extracted
- Action: Auto-send but flag for audit review in dashboard

### Queue for Review (0.70-0.79)
- Moderate signals
- Some fields missing or ambiguous
- Action: Save as draft, require human approval before sending

### Require Manual Review (<0.70)
- Weak signals
- Significant ambiguity
- Action: Draft notification but do NOT auto-send, require full manual review

## Template Selection Logic

Templates are selected deterministically (no AI) based on sub-type and flags:

| Sub-Type | Job Machine? | Next Round? | Template |
|----------|-------------|-------------|----------|
| Interview Request | No | No | Interview Request (First) |
| Interview Request | Yes | No | Interview Request (First) via Job Machine |
| Interview Request | No/Yes | Yes | Second/Third Interview Request |
| Phone Screen | No | - | Phone Screening Scheduled |
| Phone Screen | Yes | - | Phone Screening Scheduled via Job Machine |
| Client Screen | No | - | Client Screening Scheduled |
| Client Screen | Yes | - | Client Screening Scheduled via Job Machine |
| Technical Interview | No | - | Technical Round Scheduled |
| Technical Interview | Yes | - | Technical Round Scheduled via Job Machine |
| Cancelled | - | - | Heads Up - Reschedule Needed |
| Rescheduled | - | - | Interview Rescheduled |

## Related Scripts

### Execution Scripts
- `execution/subclassify_interview.py` - AI sub-classification (7 types)
- `execution/resolve_student.py` - Student identification from email headers
- `execution/google_drive_client.py` - Google Drive/Sheets API wrapper
- `execution/fetch_student_info.py` - Student data retrieval orchestrator
- `execution/email_templates.py` - Template storage and selection
- `execution/draft_notification.py` - Template population and WhatsApp generation
- `execution/send_notification.py` - Gmail SMTP sending
- `execution/log_interview.py` - Database logging (students, events, drafts)
- `execution/process_interviews.py` - Pipeline orchestrator

### API & Dashboard
- `services/dashboard/api/routers/notifications.py` - Notification review API
- `services/dashboard/api/models.py` - Student, InterviewEvent, NotificationDraft models
- `services/dashboard/frontend/src/pages/InboxPage.tsx` - Inline notification panel

### Tests
- `tests/execution/test_subclassify_interview.py` - 59 tests
- `tests/execution/test_resolve_student.py` - 39 tests
- `tests/execution/test_google_drive_client.py` - 21 tests
- `tests/execution/test_draft_notification.py` - 50 tests
- `tests/execution/test_send_notification.py` - 25 tests
- `tests/execution/test_log_interview.py` - 21 tests

## Environment Variables

Required in `.env` file:

```
# Google Drive (student info lookup)
GOOGLE_SERVICE_ACCOUNT_KEY_PATH=config/service-account-key.json
GOOGLE_DRIVE_STUDENTS_FOLDER_ID=1VZqhosCZNC4Ni-6jDN6ynpCSpAn1hYn4
STUDENT_CACHE_TTL_HOURS=4

# SMTP (sending notifications)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=<sending email address>
SMTP_PASSWORD=<app password>
SMTP_FROM_NAME=Colaberry Interview Support

# WhatsApp (manual sending reference)
WHATSAPP_DEFAULT_SENDER=Jackie
WHATSAPP_SENDER_JACKIE=214-607-8702
WHATSAPP_SENDER_ALI=682-597-5784

# Notification config
STUDENT_ASSISTANT_NAME=Robelyn
OPENAI_API_KEY=<api key for sub-classification>
```

## Monitoring & Success Metrics

### Target Metrics
- **Sub-Classification Accuracy**: 90%+ correct sub-type assignment
- **Student Resolution Rate**: 95%+ emails matched to correct student
- **Auto-Send Rate**: 60%+ of notifications sent without human review
- **Notification Delivery Rate**: 99%+ emails delivered (no SMTP failures)
- **False Send Rate**: <1% (notifications sent to wrong student or with wrong info)

### Logging Requirements
- Log every sub-classification attempt with confidence
- Track student resolution success/failure rates
- Monitor auto-send vs queued ratio
- Alert if delivery failure rate exceeds 5%
- Track WhatsApp status progression (draft -> copied -> sent)

## Testing Strategy

### Unit Tests
- Sub-classification with mocked OpenAI responses (all 7 types)
- Student resolution from various header formats
- Google Drive client with mocked API responses
- Template selection matrix (all sub-type combinations)
- Draft population and missing field detection
- SMTP sending with mocked connection
- Database logging (all CRUD operations)

### Integration Tests
- Full pipeline dry run with real sample emails
- Student resolution against known student list
- Google Drive read with read-only service account
- Template output review (side-by-side with expected)

### End-to-End Validation
- Process batch of real interview emails in dry-run mode
- Verify notification drafts match expected output
- Send test emails to personal/test inbox
- Review WhatsApp summary text quality

## Self-Annealing Loop

When the pipeline fails or produces incorrect results:

1. **Identify root cause**: Sub-classification wrong? Student mismatched? Template incorrect?
2. **Fix the system**: Update prompt, improve header parsing, fix template logic
3. **Add tests**: Ensure this failure type is covered
4. **Update this directive**: Document new edge case or handling rule
5. **Verify improvement**: Run full test suite, check metrics

## Production Deployment Checklist

Before deploying to production:
- [ ] All unit tests pass (297+)
- [ ] Google Cloud service account configured with Drive API access
- [ ] SMTP credentials configured and tested
- [ ] Student spreadsheet column structure confirmed
- [ ] Test email sent to personal/test inbox successfully
- [ ] Dashboard notification panel renders correctly
- [ ] Alembic migration run (`001_add_interview_notification_tables.py`)
- [ ] Dry-run batch processing completed without errors
- [ ] Logging configured and producing expected output
- [ ] WhatsApp message format reviewed and approved

## Third screen: the interview gate (2026-10-26, branch `feat/interview-gate`, not deployed)

Runs only on mail the earlier steps already called interview-related. `execution/interview_gate.py` (gpt-4o-mini, about $0.0005 per email) reads the sender's NEW
text (the quoted thread under a reply is cut off by `execution/quoted_text.py`) plus the last 10 emails from the same sender, and answers: `new_interview`, `reschedule`,
`cancellation` (a student card), `follow_up`, `confirmation` (no card, linked to the original event) or `not_interview` (no card, no flag), with the round (1st/2nd/3rd/final)
and format (phone/video/in-person). It hides a card only when it is at least 70% sure; a model error or an unreadable answer never hides anything.

`INTERVIEW_GATE_MODE`: `off` (default, nothing runs), `shadow` (verdict saved in `interview_gate_reviews`, behaviour unchanged), `live` (the verdict decides, and the sub-classifier and the
authenticity check read only the sender's new text). Past mail is replayed with `execution/interview_gate_replay.py`; Review > "Gate review (testing)" lets a person mark each email
real / not real, and the totals (agree, hid a real one, showed a non-interview) are the evidence for switching to live.

Why: a one-line courtesy reply carried the whole confirmed-interview thread under it, so the extractor read a date and a card was made (Rutendo / Lorena Ortiz, 2026-10-26).

## Revision History

- **v1.0** (2026-01-28): Initial directive created with full pipeline specification
