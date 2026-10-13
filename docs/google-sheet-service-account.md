# Give an app read-only access to a live Google Sheet

> Also available as the local Claude skill `.claude/skills/google-sheet-service-account/` (the `.claude/` folder is not tracked in git, so this file is the shared copy).

Google calls this a **service account** (Azure and Entra call it a service principal). It is a robot identity with an email address and a key file. It can open only the sheets that are shared with it. It needs no Google Cloud billing for the Sheets API.

Use this when the data is a **live** document people keep editing and the app must always read the current version. Do not use it for a one-off export (export a CSV instead) or for sheets that must be written by the app (this recipe is read-only).

## 0. Decide what the app may see (do this first)

The app should see only the columns and rows it needs, never the master. Put a **values-only copy** in a second sheet and share only that. Every viewer of a sheet, and any AI tool acting for them, can read cell formulas, and a formula such as `IMPORTRANGE("<master url>")` reveals the master's link. So do not copy with a formula. Use the Apps Script in section 2.

## 1. Google Cloud (about 10 minutes, once per project)

Sign in with the company Google account at https://console.cloud.google.com.

1. **Project:** the project picker, then New Project (for example `inboxgenius`). Leave billing unlinked ("This project has no billing account" is fine and means it cannot incur charges). A banner on another billing account is about other projects, not this one.
2. **Enable the API:** Menu, APIs & Services, Library, search **Google Sheets API**, Enable. Nothing else is needed for reading.
3. **Create the service account:**
   - APIs & Services, Credentials, **Create credentials**. If the wizard asks "Which API?" choose Google Sheets API, then **Application data** (the text says "This will create a service account"). Do not choose "User data" (that makes an OAuth client).
   - Name it for its job, for example `inboxgenius-roster-reader`. Skip the optional role and access steps (Continue, Done). It needs no project role, because access comes from sharing the sheet.
4. **Create the key:** Menu, IAM & Admin, Service Accounts, click the account, **Keys** tab, Add key, Create new key, **JSON**, Create. A `.json` file downloads. It is a password.
   - If the console says key creation is disabled, an organisation policy blocks it; a Workspace admin must lift it (or use a keyless method).
5. **Copy the account's email** (Details tab): `name@<project-id>.iam.gserviceaccount.com`. The email is an address, not a secret.

## 2. The values-only copy (Apps Script)

1. Create a new sheet (for example `student_roster`) with one tab named `roster`.
2. Extensions, Apps Script. Paste a script that copies chosen columns by **header name**, with an optional row filter, as plain values. Header names make it survive columns being moved; it fails loudly if a header is renamed.
3. Put the master's ID in **Project Settings, Script Properties** (`MASTER_ID`), not in the code. The ID is the part of the URL between `/d/` and `/edit`.
4. Run it once and accept the permissions (the "Untitled project" name and the "see, edit, create and delete all your spreadsheets" wording are Apps Script's standard consent for opening another sheet by ID; the script only reads the master and writes its own tab).
5. Triggers (clock icon), Add Trigger: the copy function, Time-driven, hourly (free; quota use is seconds per day). Keep Apps Script editors to the sheet owner.

Skeleton:

```javascript
const SOURCE_TAB = 'Sheet1', TARGET_TAB = 'roster';
const COLUMNS = ['Name', 'STATUS', 'New Email Address', 'Personal Email Address'];   // exact header text in the master
const FILTER_COLUMN = 'STATUS', FILTER_VALUES = ['active', 'in progress'];            // lower-case

function syncRoster() {
  const masterId = PropertiesService.getScriptProperties().getProperty('MASTER_ID');
  if (!masterId) throw new Error('Set the MASTER_ID script property first.');
  const rows = SpreadsheetApp.openById(masterId).getSheetByName(SOURCE_TAB).getDataRange().getValues();
  const header = rows[0].map(h => String(h).trim().toLowerCase());
  const idx = COLUMNS.map(c => { const i = header.indexOf(c.toLowerCase()); if (i < 0) throw new Error('Column not found in master: ' + c); return i; });
  const f = header.indexOf(FILTER_COLUMN.toLowerCase());
  if (f < 0) throw new Error('Filter column not found: ' + FILTER_COLUMN);
  const out = [COLUMNS];
  rows.slice(1).forEach(r => { if (FILTER_VALUES.includes(String(r[f]).trim().toLowerCase())) out.push(idx.map(i => r[i])); });
  const sh = SpreadsheetApp.getActive().getSheetByName(TARGET_TAB);
  sh.clearContents();
  sh.getRange(1, 1, out.length, COLUMNS.length).setValues(out);
}
```

Common errors: "Column not found" (header text differs: check spelling, spaces), "Cannot read properties of null" (a tab name in the constants does not exist), `#REF!` in an IMPORTRANGE formula (the one-time "Allow access" was not clicked).

## 3. Share and wire up

1. Share the **copy** sheet (not the master) with the service account's email as **Viewer**; untick "Notify people"; "Share anyway" if Google warns the address is outside the organisation.
2. Put the key file in the app's gitignored config folder (here `config/service-account-key.json`; confirm with `git check-ignore -v <path>`). Move it out of Downloads so no copy remains. Copy it to the server with `scp`, restrict it (`chmod 600`), and never print or paste its contents.
3. `.env` (local and server): the sheet ID (here `STUDENT_ROSTER_SHEET_ID`), the key path (`GOOGLE_SERVICE_ACCOUNT_KEY_PATH`), optionally the account email for messages. Check they are set with a character count (`... | wc -c`), never by printing them. Keep the ID separate from any other sheet's ID (for example the audit log) so one is never written into by mistake.
4. Reading from code needs only `google-auth` and an authorised session with the scope `https://www.googleapis.com/auth/spreadsheets.readonly` and a GET on `https://sheets.googleapis.com/v4/spreadsheets/<id>/values/<tab>`. See `execution/student_roster.py` (`fetch_roster`) for a header-driven reader with a cache, a near-empty-sheet guard and fail-soft behaviour.

## 4. Verify (read-only) and test safely

- Fetch the tab once and print only the header and row counts, never cell values.
- A 403/404 means the sheet is not shared with the service account (or the ID is wrong).
- Tests must never reach the real sheet: set the sheet ID and any other live credentials to empty in an autouse fixture, and inject a fake session (see `tests/execution/test_student_roster.py`).
- The app must not break when the sheet is down: cache for a while, keep the last good copy, and ignore a sheet with too few rows.

## Safety and cost

- **Cost:** service accounts, keys and the Sheets API read volume of an hourly poll are free. Apps Script time triggers are free.
- **Secrets:** the key file and the sheet ID are not printed, logged, committed or pasted into chats or tickets.
- **Least access:** Viewer only; the copy sheet only; the key lives on the server and the developer's machine only.
- **Visibility:** an LLM or person with Viewer access reads what a person with Viewer access reads, including formulas; that is why the copy holds values only. Access is controlled by who the sheet is shared with, not by any LLM setting.
- **Rotation and removal:** to revoke, delete the key in Service Accounts, Keys (or unshare the sheet). To rotate, create a new key, replace the file, then delete the old key.
- **Document it:** record the project, account name, sheet and who owns the master in `progress.md`/`RUNBOOK.md`; never the key or IDs beyond what the repo already allows.
