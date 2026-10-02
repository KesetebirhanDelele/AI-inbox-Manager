# GHL Conversations and calls: what is verified, what is not

Reference for anything that READS what happened in a candidate's GoHighLevel (GHL) Conversations: replies,
call results, transcripts. Companion to the portable kit in `.claude/skills/ghl-integration/KIT.md` (which covers
writing fields, tokens, DND and safety). Written 2026-10-02.

**Source of every "verified" fact below:** the code, tests, specs and notes in Kes's separate Cora project
(`C:\Users\keset\cora-recap-engine`), read only, nothing there was changed. Those facts were confirmed live against
the Colaberry GHL account by that project. Nothing here has been run from this repo yet. Treat "verified" as
"verified on this GHL account by Cora", and re-check anything that matters in a shadow rehearsal.

## 1. Verified (on the Colaberry GHL account, by Cora)

| Topic | Fact | Cora source |
|---|---|---|
| Token | Reading conversations needs the **second** Private Integration token (`GHL_CONVERSATIONS_API_KEY`: conversations.readonly, conversations/message.readonly, conversations/message.write). The contacts token returns 401 "not authorized for this scope". | `spec/23`, `ghl.py` |
| Find conversations | `GET /conversations/search` with `locationId`, `contactId`, `limit`. Newest first by default. | `ghl.py` |
| Cursor trap | `startAfterDate` is a **pagination cursor, not a "since" filter**, and the default sort is descending, so a lookback timestamp silently walks backward into old data. Use `sortBy=last_message_date&sort=asc` if you page by time. We avoid it by searching per `contactId`. | `spec/23` |
| Note masking | `lastMessageType` filters on the conversation's **last** message only; a note written after a call hides the call. Never filter on it; walk each conversation's messages. | `spec/23` |
| Messages | `GET /conversations/{id}/messages?limit=`. The response is **double-nested**: `{"messages": {"lastMessageId":..., "nextPage":..., "messages": [...]}}`. | `ghl.py` |
| Message fields | `id`, `direction` (inbound/outbound), `messageType` (`TYPE_SMS`, `TYPE_EMAIL`, `TYPE_CALL`; older code saw `SMS`/`Email`/`Call`), `body`, `dateAdded`, `status`, `userId`, `source`, `meta`. | `ghl.py`, kit |
| Call message | Call status and length are at **`meta.call.status`** and **`meta.call.duration`** (seconds), not at the top level. "Connected" in Cora = `status == "completed"` AND `duration >= 20`. A call with no connection (busy, no answer, voicemail) is not connected. | `staff_call_quality_jobs.py` |
| Email delivery | Not in the message list. Take `meta.email.messageIds[0]`, call `GET /conversations/messages/email/{id}` with `Version: 2021-04-15` (conversations token). | `ghl.py` |
| Recording | `GET /conversations/messages/{id}/locations/{loc}/recording` returns `audio/x-wav`. A 422 means no recording (for example a busy call). | `ghl.py` |
| **Transcript** | `GET /conversations/locations/{loc}/messages/{id}/transcription` returns sentence entries `{mediaChannel, sentenceIndex, startTime, endTime, transcript, confidence}`. **On this account GHL does not generate native transcripts**: it returns 400 `CONVERSATIONS_MSG_RECORDING_NOT_FOUND` even for a completed 4-month-old call. Cora's working path is recording to OpenAI Whisper (`whisper-1`, about 6 s for a 49 s call), which returns **plain text with no speaker labels**. | `spec/23`, `ghl.py` |
| Contact search | `GET /contacts/?locationId=&query=<E.164>` is a **free-text query**: it can return near matches, and callers needing an exact match must filter themselves. Contact `phone` is stored E.164 (`+15551234567`). | `ghl.py`, tests |
| One thread | GHL puts every message for a contact into one conversation, whichever token or mechanism wrote it. | memory note |
| Staff-only notes | `POST /conversations/messages` with `{"contactId", "type": "InternalComment", "message"}` (conversations token) creates a yellow staff-only note in the thread. Cora uses it to put call transcripts into the conversation. | `ghl_internal_comment.py` |
| Resilience | HTTP 401 with body "Command timed out" is a disguised timeout: retry it. Bursts return 429. | `ghl.py` |
| Field triggers | A workflow triggered by a custom field fires when the field **changes**; the same value written again does not re-trigger. (Confirmed by Kes 2026-10-02.) | Kes |
| Text rules Cora applies | No links; 3+ words; lead-local 8 AM to 9 PM (TCPA); daily cap 999 segments (T-Mobile); Cora's ledger counts only texts Cora sends. | `spec/34` |

## 2. Findings that change what we do
1. **Do not rely on GHL transcripts.** Expect the transcript call to return nothing. A transcript can be made from the
   recording with Whisper, but it has **no speaker labels**, so it cannot be used to read only the student's words.
2. **Outbound Synthflow calls are not TYPE_CALL messages in GHL** (Cora's delivery-health test notes "outbound calls
   come from call_events, not GHL"). If our voice agent is Synthflow behind a GHL workflow, the call result may only
   appear as a note a handler writes into the thread, or arrive by a Synthflow webhook. See open question A.
3. **Connected must be a positive test** (completed and long enough), never "not in a list of bad statuses".

## 2b. Voice AI (verified from GHL's own docs and live on the Colaberry account, 2026-10-02)
The Colaberry voice agent is GHL's built-in Voice AI. Its calls are best read from Voice AI call logs, not from
Conversations transcripts.

| Topic | Fact | Source |
|---|---|---|
| Call logs | `GET /voice-ai/dashboard/call-logs` (scope `voice-ai-dashboard.readonly`; the contacts token works once it has the scope). Filters: `contactId`, `agentId`, `callType` (LIVE/TRIAL), `startDate`/`endDate` (unix, together), `actionType`, `page`, `pageSize` (max 50), `sortBy` (duration/createdAt), `sort`. Response: `callLogs`, `page`, `pageSize`, `total`. | GHL API docs; live |
| Log fields | `id`, `contactId`, `agentId`, `fromNumber`, `createdAt`, `duration` (s), `transcript`, `summary`, `executedCallActions`, `extractedData`, `messageId`, `agentTransferOccurred`, `trialCall`, `translation`. **No status or outcome field.** | live |
| Transcript | Plain text of `bot:` and `human:` prefixed lines (no structured roles). `human:` is the contact. | GHL API docs; live |
| Call-end webhook | `VoiceAiCallEnd` carries call id, location, agent, contact, duration, summary and transcript. | GHL webhook docs |
| Outbound action | Workflow action "Voice AI Outbound Call": pick the agent and a From number. How contact data reaches the prompt is **not documented**. | GHL help |
| Outbound limits | 8 AM to 8 PM in the contact's phone-number zone (others are rescheduled); **one call per number per day, 14 per 14 days**; 10 per minute and 5,000 per day per location; domestic only. | GHL help |
| Compliance | GHL does **not** validate consent or DND. We must. | GHL help |
| Same agent in and out | Yes with the right prompt. Same number: not stated in the docs. | GHL help |

Sources: help.gohighlevel.com "Voice AI Outbound Calling" (article 155000006598) and "Voice AI Outbound Calling Compliance
Checks" (155000006679); marketplace.gohighlevel.com docs "List Call Logs" and "VoiceAiCallEnd".

## 3. NOT verified for our use (needs a look at the real account)
A. **How the `interview_notification` value reaches the voice agent's prompt.** Needs a test on a test contact.
B. **Whether the existing number is an eligible From number** for the outbound action.
C. **Whether the one-call-per-number-per-day limit also counts other Voice AI calls** to the same student (for example
   Admissions).
D. **How voicemail appears** in the call logs, since there is no status field (we treat "no human speech" as no
   conversation).
E. **The shortest call that can still be a real conversation.** We default to 10 s (`NOTIFY_CALL_MIN_SECONDS`).

(Answered 2026-10-02: the engine is GHL Voice AI; the student's words are the `human:` lines; calls are read from the
call-log API; GHL enforces 8 AM to 8 PM and one call per number per day; GHL does not check DND or consent.)

## 4. What is missing from `.claude/skills/ghl-integration/KIT.md` (for Kes to add)
1. The conversation search and message-list endpoints, their parameters, and the double-nested messages response.
   Also the Voice AI call-log endpoint and its fields (section 2b): it is the real source of call transcripts.
2. That call status and duration are in `meta.call`, and the connected rule (completed plus a minimum length).
3. The transcript sentence shape (`mediaChannel`, `sentenceIndex`, `transcript`), that it has no speaker labels, and
   that native transcripts may be off on the account so the Whisper-from-recording fallback is the real path.
4. `startAfterDate` is a cursor, and `lastMessageType` hides a call behind a later note (both traps).
5. Contact search by phone is free-text and returns near matches: always filter for an exact number.
6. Re-trigger rule: a field-change trigger needs a CHANGED value, so make every write unique per attempt.
7. Where results of an externally placed (Synthflow) call appear in GHL, and the InternalComment write. Section 8 of the
   kit can now be answered for GHL's own Voice AI: results come from the call-log API or the `VoiceAiCallEnd` webhook,
   and GHL enforces 8 AM to 8 PM, one call per number per day, and checks neither consent nor DND.
8. A daily text budget shared with another app is invisible to each app's own ledger.
9. A polling recipe: handle each message id once, group open items per contact, wait a grace period for transcripts,
   never act on a transcript whose speakers you cannot tell apart.
