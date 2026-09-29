# Email Integration Setup Guide

This guide will help you set up automatic email fetching and classification for your inbox.

## Prerequisites

- Python 3.9+ installed
- All dependencies installed (`pip install -r requirements.txt`)
- OpenAI API key configured
- Access to an email account (Gmail, Outlook, or IMAP-compatible)

## Quick Start

### 1. Configure Email Credentials

Edit your `.env` file and add your email settings:

```bash
# For Gmail
EMAIL_SERVER=imap.gmail.com
EMAIL_PORT=993
EMAIL_ADDRESS=your-email@gmail.com
EMAIL_PASSWORD=your-app-password-here
EMAIL_FOLDER=INBOX
EMAIL_SEARCH_CRITERIA=UNSEEN
```

### 2. Test Email Connection

```bash
python execution/fetch_emails.py tmp/fetched_emails.json --limit 5
```

This will fetch up to 5 unread emails and save them to a JSON file.

### 3. Process Inbox (Fetch + Classify)

```bash
python execution/process_inbox.py tmp/inbox_results --limit 10
```

This will:
- Fetch up to 10 unread emails
- Classify each one using OpenAI
- Save results to `tmp/inbox_results/`
- Print a summary report

---

## Detailed Setup Instructions

### Gmail Setup

Gmail requires an "App Password" for IMAP access (not your regular password).

#### Step 1: Enable 2-Factor Authentication

1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable "2-Step Verification" if not already enabled

#### Step 2: Generate App Password

1. Go to [App Passwords](https://myaccount.google.com/apppasswords)
2. Select "Mail" and "Windows Computer" (or Other)
3. Click "Generate"
4. Copy the 16-character password (e.g., `abcd efgh ijkl mnop`)

#### Step 3: Configure .env

```bash
EMAIL_SERVER=imap.gmail.com
EMAIL_PORT=993
EMAIL_ADDRESS=your-email@gmail.com
EMAIL_PASSWORD=abcdefghijklmnop  # No spaces
EMAIL_FOLDER=INBOX
```

---

### Outlook/Microsoft 365 Setup

#### Step 1: Enable IMAP

1. Go to [Outlook Settings](https://outlook.live.com/mail/0/options/mail/accounts)
2. Go to Sync email → POP and IMAP
3. Enable IMAP access

#### Step 2: Configure .env

```bash
EMAIL_SERVER=outlook.office365.com
EMAIL_PORT=993
EMAIL_ADDRESS=your-email@outlook.com
EMAIL_PASSWORD=your-password-here
EMAIL_FOLDER=INBOX
```

**Note**: Microsoft may require OAuth2 for some accounts. If password doesn't work, you may need to generate an app-specific password.

---

### Other Email Providers

For other providers, find their IMAP settings:

| Provider | Server | Port |
|----------|--------|------|
| Yahoo | imap.mail.yahoo.com | 993 |
| AOL | imap.aol.com | 993 |
| iCloud | imap.mail.me.com | 993 |

---

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EMAIL_SERVER` | - | IMAP server address (required) |
| `EMAIL_PORT` | 993 | IMAP port (993 for SSL) |
| `EMAIL_ADDRESS` | - | Your email address (required) |
| `EMAIL_PASSWORD` | - | App password (required) |
| `EMAIL_FOLDER` | INBOX | Folder to monitor |
| `EMAIL_SEARCH_CRITERIA` | UNSEEN | Search filter (UNSEEN, ALL, etc.) |
| `EMAIL_BATCH_SIZE` | 50 | Max emails per batch |
| `EMAIL_MARK_AS_READ` | false | Auto-mark as read after fetch |

### Search Criteria Options

- `UNSEEN` - Only unread emails (default)
- `ALL` - All emails in folder
- `SEEN` - Only read emails
- `SINCE "01-Jan-2024"` - Emails since specific date
- `FROM "company.com"` - From specific domain

---

## Usage Examples

### Example 1: Fetch Unread Emails (Don't Mark as Read)

```bash
python execution/fetch_emails.py tmp/emails.json --limit 10
```

### Example 2: Fetch and Mark as Read

```bash
python execution/fetch_emails.py tmp/emails.json --limit 10 --mark-read
```

### Example 3: Process Entire Workflow

```bash
python execution/process_inbox.py tmp/results --limit 20
```

### Example 4: Test Without API Calls

```bash
python execution/process_inbox.py tmp/results --limit 5 --validate-only
```

### Example 5: Process and Mark as Read

```bash
python execution/process_inbox.py tmp/results --mark-read
```

---

## Output Files

### Fetched Emails JSON

Location: `tmp/fetched_emails.json`

```json
[
  {
    "subject": "Interview Request - Data Analyst",
    "sender_email": "hr@company.com",
    "sender_name": "Jane Smith",
    "email_date": "2024-01-15T10:30:00-05:00",
    "body_content": "We'd like to schedule an interview...",
    "email_id": "12345",
    "message_id": "<abc@mail.company.com>"
  }
]
```

### Classification Results

Location: `tmp/inbox_results/<email_id>_classification.json`

```json
{
  "category": "Interview Request",
  "confidence": 0.95,
  "requires_manual_review": false,
  "reasoning": "Clear interview request...",
  "extracted_data": {
    "company_name": "Company Inc",
    "position_title": "Data Analyst"
  }
}
```

### Batch Summary

Location: `tmp/inbox_results/batch_summary.json`

```json
{
  "processing_timestamp": "2024-01-15T12:00:00Z",
  "statistics": {
    "total_emails": 10,
    "classified_success": 9,
    "classification_failed": 1,
    "requires_manual_review": 2,
    "high_confidence": 7,
    "categories": {
      "Interview Request": 4,
      "Interview Schedule": 3,
      "Offer": 1,
      "Other": 1
    }
  }
}
```

---

## Troubleshooting

### Error: "Authentication failed"

**Cause**: Wrong password or username

**Solution**:
1. Verify EMAIL_ADDRESS is correct
2. For Gmail, use app password (not regular password)
3. Check password has no spaces or special characters
4. Ensure 2FA is enabled (Gmail)

### Error: "Connection failed"

**Cause**: Wrong server or port

**Solution**:
1. Verify EMAIL_SERVER is correct for your provider
2. Ensure EMAIL_PORT is 993 (for SSL)
3. Check firewall/network allows IMAP connections
4. Try accessing email via browser to confirm account works

### Error: "No emails found"

**Cause**: No emails match search criteria

**Solution**:
1. Change criteria to "ALL" to see all emails
2. Check correct folder (INBOX vs other folders)
3. Verify emails exist in that folder via webmail

### Error: "Failed to parse email"

**Cause**: Email has unusual encoding or format

**Solution**:
1. Check logs for specific email ID
2. Email will be skipped, others continue processing
3. Review individual email manually if needed

---

## Security Best Practices

### ✅ DO

- Use app-specific passwords (never your main password)
- Keep `.env` file secure and never commit to git
- Use SSL/TLS (port 993)
- Rotate passwords periodically
- Test with a dedicated test inbox first
- Set up usage alerts in OpenAI dashboard

### ❌ DON'T

- Don't share .env file
- Don't commit email passwords to version control
- Don't use plain text connections (port 143 without SSL)
- Don't give API keys excessive permissions
- Don't process production emails in dev environment

---

## Automated Processing

> **Production note (2026-09-29):** the live pipeline is scheduled by the `cron`
> container on the Hetzner server (`execution/crontab.server`, every 2 hours);
> see [`RUNBOOK.md`](../RUNBOOK.md) §4c. Never run a second scheduler against the
> production mailbox. The options below are generic reference for other setups;
> Option 2 (Windows Task Scheduler) is no longer used by this project.

### Option 1: Cron Job (Linux/Mac)

Add to crontab:

```bash
# Run every 15 minutes
*/15 * * * * cd /path/to/project && /path/to/venv/bin/python execution/process_inbox.py tmp/results --limit 50 --mark-read
```

### Option 2: Task Scheduler (Windows)

1. Open Task Scheduler
2. Create new task
3. Trigger: Every 15 minutes
4. Action: Run `python execution/process_inbox.py tmp/results --limit 50 --mark-read`

### Option 3: Worker Service

Create a long-running service in `/services/worker/email_worker.py` that polls inbox continuously.

---

## Next Steps

After emails are classified:

1. **Database Integration**: Store classifications in SQL Server
2. **WhatsApp Alerts**: Send notifications for important categories
3. **Dashboard**: Build reporting UI for classified emails
4. **Automation**: Auto-respond or forward based on classification

---

## Testing Checklist

Before going live:

- [ ] Test connection to email server
- [ ] Fetch 1-2 emails successfully
- [ ] Verify email parsing (subject, sender, body)
- [ ] Test classification with real emails
- [ ] Confirm marking as read works (if enabled)
- [ ] Check all credentials are in .env (not hardcoded)
- [ ] Review logs for errors
- [ ] Test error handling (wrong password, network issues)

---

## Support

For issues:
1. Check logs in console output
2. Verify .env configuration
3. Test email access via webmail
4. Review [directives/email-integration.md](../directives/email-integration.md)
5. Check OpenAI API usage/limits

---

**Last Updated**: 2026-01-27
