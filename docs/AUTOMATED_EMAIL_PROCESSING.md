# Automated Email Processing System

> ⚠️ **Partly obsolete (2026-09-29).** Production no longer runs from a Windows
> scheduled task, and not hourly: the pipeline runs **every 2 hours, on the hour
> (UTC)** from the `cron` container on the Hetzner server — see
> [`RUNBOOK.md`](../RUNBOOK.md) §4c. The Windows Task Scheduler setup described
> below (`scripts/setup_hourly_task.*`, `Register-/Get-ScheduledTask …`) was
> removed from the repo; do **not** recreate it, or two schedulers would process the
> same mailbox. The safety-feature sections (whitelist, folder rules) still apply.

## Overview

This system automatically processes emails from the c_interviews@colaberry.com inbox hourly, organizing them into folders and keeping genuine interview requests in the inbox for manual review.

## Critical Safety Features

### 1. Known Company Whitelist

The system maintains a whitelist of companies that have sent genuine interview requests. **Emails from these companies are NEVER moved or deleted**, regardless of how the AI classifies them.

**Current Whitelist:**
- Ask Consulting
- United Global Technologies
- Excelon Solutions
- Wesco
- VDart
- Refocus
- Empiric

**To add a company to the whitelist:**
Edit [execution/process_inbox_auto.py](../execution/process_inbox_auto.py) and add the company name (lowercase) to the `KNOWN_INTERVIEW_COMPANIES` set.

### 2. UNSEEN-Only Processing

The automated script ONLY processes unread (UNSEEN) emails. This prevents:
- Re-processing of already-handled emails
- Accidental deletion of interview requests you've already seen
- Double-processing issues

### 3. Dual Detection Logic

Emails are kept in inbox if EITHER:
1. The AI classifies them as "Interview Request" with high confidence (>=80%), OR
2. They're from a known interview company (safety net)

### 4. Comprehensive Logging

All processing is logged to `logs/inbox_auto_YYYYMMDD.log` with:
- Which emails were processed
- Classification results
- Whether safety checks triggered
- What action was taken (keep/move/delete)

## How It Works

### Processing Flow

1. **Fetch unread emails** from INBOX
2. **Classify each email** using OpenAI API (gpt-4o)
3. **Apply safety checks**:
   - Is it from a known company? → Keep in inbox
   - Is it a genuine interview request? → Keep in inbox
   - Is it spam (category: "Other")? → Delete
   - Is it another category? → Move to folder
4. **Execute actions** on email server
5. **Log results** and save summary

### What Happens to Each Email Type

| Email Type | Action | Reason |
|------------|--------|--------|
| **Interview Request** (genuine) | KEPT IN INBOX | Needs immediate response |
| **From Known Company** | KEPT IN INBOX | Safety protection |
| **Job Alert** | Moved to "Job Alerts" folder | Informational only |
| **Application Notification** | Moved to folder | FYI |
| **Spam/Other** | DELETED | Not relevant |
| **Other Categories** | Moved to category folder | Organized for reference |

## Running the System

### Manual Execution

To process emails manually:

```bash
cd "C:\Users\ali_m\OneDrive\Business\Colaberry Novedea\AI Projects\ClaudeTest"
python execution/process_inbox_auto.py
```

### Automated Hourly Execution

#### Setup (One-Time)

1. **Right-click** on `scripts/setup_hourly_task.bat`
2. Select **"Run as Administrator"**
3. Confirm the task was created

This creates a Windows Task Scheduler task that runs every hour.

#### Managing the Scheduled Task

**View task status:**
```powershell
Get-ScheduledTask -TaskName "ColaberryEmailProcessing"
```

**Run immediately:**
```powershell
Start-ScheduledTask -TaskName "ColaberryEmailProcessing"
```

**Disable (pause) task:**
```powershell
Disable-ScheduledTask -TaskName "ColaberryEmailProcessing"
```

**Enable task:**
```powershell
Enable-ScheduledTask -TaskName "ColaberryEmailProcessing"
```

**Remove task:**
```powershell
Unregister-ScheduledTask -TaskName "ColaberryEmailProcessing"
```

## Testing

### Unit Tests

Tests the interview request detection logic:

```bash
python tests/test_interview_detection.py
```

### Integration Tests

Tests the full processing flow:

```bash
python tests/test_inbox_processing_integration.py
```

### Diagnostic

To see what's currently in the inbox and how each email would be classified:

```bash
python execution/diagnose_inbox.py
```

## Exit Codes

The script returns different exit codes for monitoring:

| Exit Code | Meaning |
|-----------|---------|
| 0 | Success - no interview requests detected |
| 10 | Success - interview requests detected (requires attention) |
| 1 | Error occurred |

## Logs and Summaries

### Logs

Daily log files: `logs/inbox_auto_YYYYMMDD.log`

Contains detailed processing information for debugging.

### Summaries

Processing summaries: `tmp/auto_process_YYYYMMDD_HHMMSS/summary.json`

Contains:
- Total emails processed
- Interview requests detected
- Emails organized/deleted
- Category breakdown

## Troubleshooting

### Interview Request Missing

1. **Check the whitelist** - Is the company in `KNOWN_INTERVIEW_COMPANIES`?
2. **Check logs** - What was the classification? Did safety checks trigger?
3. **Check summary** - Was it detected but the email server didn't sync?
4. **Run diagnostic** - Use `diagnose_inbox.py` to see current inbox state

### Task Not Running

1. **Check task status**: `Get-ScheduledTask -TaskName "ColaberryEmailProcessing"`
2. **Check task history**: Task Scheduler → Task History
3. **Check logs**: `logs/inbox_auto_YYYYMMDD.log`
4. **Verify Python path**: Task runs with the correct Python interpreter

### False Positives/Negatives

If the AI is misclassifying emails:

1. **Add company to whitelist** (immediate fix)
2. **Review classification prompt** in `execution/classify_email.py`
3. **Check confidence thresholds** in `is_genuine_interview_request()`

## Configuration

### Environment Variables

Required in `.env` file:

- `EMAIL_SERVER` - IMAP server (imap.gmail.com)
- `EMAIL_PORT` - IMAP port (993)
- `EMAIL_ADDRESS` - Email account
- `EMAIL_PASSWORD` - App-specific password
- `OPENAI_API_KEY` - OpenAI API key

### Folder Mapping

Server folder names are mapped in [execution/process_inbox_auto.py](../execution/process_inbox_auto.py):

```python
category_to_folder = {
    "Job Alert": "Job Alerts",  # Note: Plural on server
    "Application Notification": "Application Notification",
    # ... etc
}
```

## Safety Guidelines

1. **Never delete the whitelist** - It's your safety net
2. **Add companies promptly** - When you get a genuine interview, add the company immediately
3. **Monitor logs regularly** - Check for unexpected behavior
4. **Test before deploying** - Run diagnostic and manual processing first
5. **Keep backups** - The logs are your audit trail

## Interview Notification Pipeline

After the main email processing system classifies emails, interview-related emails go through a second pipeline that automatically notifies students about their interviews.

### How It Works

```
Interview email in inbox
  ↓
Sub-classify → identify interview type (Phone Screen, Client Screen, etc.)
  ↓
Resolve student → match email to student via forwarding headers
  ↓
Fetch student info → get personal email from Google Drive
  ↓
Draft notification → select template, populate fields, generate WhatsApp summary
  ↓
Auto-send (confidence >= 95%) or queue for review in dashboard
```

### Running the Interview Pipeline

```bash
cd "C:\Users\ali_m\OneDrive\Business\Colaberry Novedea\AI Projects\ClaudeTest"
python execution/process_interviews.py
```

This pipeline is orchestrated by `execution/process_interviews.py` and calls:
- `execution/subclassify_interview.py` - AI sub-classification
- `execution/resolve_student.py` - Student identification
- `execution/fetch_student_info.py` - Google Drive lookup
- `execution/draft_notification.py` - Template selection and population
- `execution/send_notification.py` - Gmail SMTP sending
- `execution/log_interview.py` - Database logging

### Dashboard Integration

Interview notification details appear **inline in the Inbox view** of the Email Dashboard. When you click on an interview email, you'll see:

- **Interview Details**: Sub-type, company, position, date/time, contact info, confidence
- **Student Info**: Name, personal email, assigned Gmail, phone
- **Email Notification**: Draft subject/body (editable if pending), status, send/approve/reject buttons
- **WhatsApp Message**: Short summary text with copy button and manual status tracking

### Notification Review

Notifications that don't qualify for auto-send appear in the dashboard as drafts. Reviewers can:
- **Approve & Send** - Send the notification as-is
- **Edit** - Modify subject, body, or recipient, then save or send
- **Reject** - Reject with an optional reason

### Auto-Send Criteria

A notification is auto-sent only when ALL conditions are met:
1. Sub-classification confidence >= 0.95
2. All required template fields are populated
3. Student's personal email is available
4. Draft status is "ready" (no missing fields)

### WhatsApp Messages

WhatsApp notifications are generated as text for manual sending. The dashboard provides:
- **Copy** button to copy the message to clipboard
- **Status toggle**: Draft -> Copied -> Sent (manual tracking)

### Additional Configuration

Additional environment variables required for the interview pipeline (in `.env`):

```
GOOGLE_SERVICE_ACCOUNT_KEY_PATH=config/service-account-key.json
GOOGLE_DRIVE_STUDENTS_FOLDER_ID=1VZqhosCZNC4Ni-6jDN6ynpCSpAn1hYn4
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=<sending email>
SMTP_PASSWORD=<app password>
STUDENT_ASSISTANT_NAME=Robelyn
```

### Database Migration

Three new tables support the pipeline (`students`, `interview_events`, `notification_drafts`). Run the Alembic migration:

```bash
cd services/dashboard/api
alembic upgrade head
```

### Interview Pipeline Tests

```bash
python -m pytest tests/execution/test_subclassify_interview.py tests/execution/test_resolve_student.py tests/execution/test_google_drive_client.py tests/execution/test_draft_notification.py tests/execution/test_send_notification.py tests/execution/test_log_interview.py -v
```

For full details, see [directives/interview-processing.md](../directives/interview-processing.md).

## Support

For issues or questions:

1. Check logs: `logs/inbox_auto_YYYYMMDD.log`
2. Run diagnostic: `python execution/diagnose_inbox.py`
3. Review tests: Run all tests to ensure system health
4. Check configuration: Verify `.env` settings
