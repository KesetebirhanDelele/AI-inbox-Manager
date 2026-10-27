"""
Third screen for interview mail: is this email NEW interview news, or just a reply inside a thread?

Runs only on mail the earlier steps already called interview-related, so it is a few calls a day on gpt-4o-mini (about $0.0005 each).
It reads the NEW text of the email (the quoted thread under a reply is cut off, see quoted_text.py) plus a short history of the last
emails with the same sender, and says which of these it is:

  new_interview   a first, 2nd, 3rd or final round is being arranged           -> a student card
  reschedule      an announced interview moves to a new time                   -> a student card
  cancellation    an announced interview is cancelled                          -> a student card
  follow_up       reminder / logistics about an interview already announced    -> no card, linked to the original
  confirmation    repeats or confirms an interview already announced           -> no card, linked to the original
  not_interview   nothing about arranging an interview (a courtesy reply)      -> no card, no flag

INTERVIEW_GATE_MODE:  off (default) | shadow (record the verdict, change nothing) | live (the verdict decides).
Every doubt fails towards the existing behaviour: a model error, an unreadable answer or a confidence under CONFIDENCE_FLOOR never
hides a card. Prompt, parsing and the decision are pure functions; only `call_model` touches the network.
"""
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from quoted_text import split_reply

logger = logging.getLogger(__name__)

MODEL = os.getenv("INTERVIEW_GATE_MODEL", "gpt-4o-mini")
VERDICTS = ("new_interview", "reschedule", "cancellation", "follow_up", "confirmation", "not_interview")
SHOWS_CARD = ("new_interview", "reschedule", "cancellation")
LINKS_TO_ORIGINAL = ("follow_up", "confirmation")
ROUNDS = ("1st", "2nd", "3rd", "final", "unknown")
FORMATS = ("phone", "video", "in-person", "unknown")
CONFIDENCE_FLOOR = 0.7
# A test the candidate completes alone has its own notice (template next_round_assessment); "not an interview" must never suppress it.
SKIPPED_CATEGORIES = ("Assessment",)
HISTORY_LIMIT = 10
NEW_TEXT_LIMIT = 3000
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com", "live.com", "msn.com", "proton.me", "protonmail.com"}

PROMPT = """You screen interview-related emails for a career placement program. The email below was flagged as possibly about a job interview; that flag is often wrong (job-board
and lead-generation mailers, reminders, replies). Decide whether its NEW text (what the sender just wrote, without the older thread) brings NEWS about an interview.

Verdicts (choose exactly one):
- new_interview: arranges an interview that is not in the history yet (a first interview, or a 2nd / 3rd / final round).
- reschedule: moves an interview already in the history to a different date or time.
- cancellation: cancels or withdraws an INTERVIEW or meeting. A job opening, position, requisition or application that is closed, filled or cancelled is NOT a cancellation: answer not_interview.
- follow_up: a reminder, directions, a document, or logistics about an interview already in the history. No new time.
- confirmation: repeats or confirms an interview already in the history at the same time.
- not_interview: nothing about arranging, moving or cancelling an interview (a courtesy reply, thanks, an attachment, a job board mailer).

Rules:
- Judge ONLY the NEW text. A date that appears only in older history is not news.
- The history lines are earlier emails with the same sender, newest first. "notice=sent/approved/draft" means the student was told or is about to be.
- round: "1st", "2nd", "3rd" or "final" if the email or the history makes it clear, else "unknown". Never guess.
- format: "phone", "video", "in-person" or "unknown", from the NEW text.
- refers_to: the history number (the [n]) of the interview this is a follow_up/confirmation/reschedule/cancellation of, else null.
- The history lists earlier emails that match by sender, by company, or by the same interview date and time, newest first. If it already holds an interview with the
  same company at the same date and time, a new email about it is a follow_up or confirmation, NOT a new_interview.
- SENDER CHECK is an automatic, advisory test of whether the sender looks like a real employer or a job-board mailer. If it says likely_job_board and the email only asks
  the candidate to confirm availability, interest or a request, the answer is not_interview. If it says looks_genuine, that alone does not make the email news.
- If unsure, lower the confidence. Do not invent details.

Answer with JSON only: {{"verdict": "...", "round": "...", "format": "...", "refers_to": null, "confidence": 0.0, "reason": "one short sentence"}}

FROM: {sender}
SUBJECT: {subject}
SENDER CHECK: {sender_check}
HISTORY (earlier related emails, newest first):
{history}

NEW TEXT:
{new_text}
"""


def gate_mode() -> str:
    mode = (os.getenv("INTERVIEW_GATE_MODE") or "off").strip().lower()
    return mode if mode in ("off", "shadow", "live") else "off"


def _domain(address: str) -> str:
    match = re.search(r"@([A-Za-z0-9.-]+)", address or "")
    return match.group(1).lower() if match else ""


def _plain_address(address: str) -> str:
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", address or "")
    return match.group(0).lower() if match else (address or "").lower()


def normalize_subject(subject: str) -> str:
    s = (subject or "").lower()
    while True:
        t = re.sub(r"^\s*(re|fw|fwd|aw)\s*:\s*", "", s)
        if t == s:
            break
        s = t
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def history_line(n: int, row: Dict[str, Any]) -> str:
    """One compact line for an earlier email. `row` keys: received, from_address, subject, category, sub_type, date, time, company, status, snippet."""
    bits = [f"[{n}] {row.get('received') or '?'} | {row.get('subject') or '(no subject)'}"]
    if row.get("sub_type"):
        when = " ".join(x for x in (row.get("date"), row.get("time")) if x)
        bits.append(f"event={row['sub_type']}" + (f" {when}" if when else "") + (f" at {row['company']}" if row.get("company") else ""))
    elif row.get("category"):
        bits.append(f"category={row['category']}")
    if row.get("status"):
        bits.append(f"notice={row['status']}")
    line = " | ".join(bits)
    snippet = re.sub(r"\s+", " ", row.get("snippet") or "").strip()
    return line + (f"\n     {snippet[:300]}" if snippet else "")


def sender_check_line(check: Optional[Dict[str, Any]]) -> str:
    """The authenticity check as one line of facts for the model (it never decides; the model weighs it)."""
    if not check:
        return "(not available)"
    reasons = "; ".join((check.get("against") or [])[:3] + (check.get("for") or [])[:3])
    return f"{check.get('verdict')}" + (f" ({reasons})" if reasons else "")


def build_prompt(subject: str, sender: str, new_text: str, history: List[Dict[str, Any]], sender_check: Optional[Dict[str, Any]] = None) -> str:
    lines = [history_line(i + 1, row) for i, row in enumerate(history)] or ["(no earlier related emails)"]
    return PROMPT.format(sender=sender or "?", subject=subject or "(no subject)", history="\n".join(lines),
                         new_text=(new_text or "(empty)")[:NEW_TEXT_LIMIT], sender_check=sender_check_line(sender_check))


def parse_response(text: str, history_size: int = 0) -> Optional[Dict[str, Any]]:
    """The model's answer as a clean dict, or None when it cannot be trusted."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("verdict") not in VERDICTS:
        return None
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence"))))
    except (TypeError, ValueError):
        confidence = 0.0
    refers = data.get("refers_to")
    refers = refers if isinstance(refers, int) and not isinstance(refers, bool) and 1 <= refers <= history_size else None
    rnd = data.get("round") if data.get("round") in ROUNDS else "unknown"
    fmt = data.get("format") if data.get("format") in FORMATS else "unknown"
    return {"verdict": data["verdict"], "round": rnd, "format": fmt, "refers_to": refers,
            "confidence": confidence, "reason": str(data.get("reason") or "")[:300]}


def call_model(prompt: str) -> Dict[str, Any]:
    """{"text", "input_tokens", "output_tokens"}. Raises on any failure; the caller fails open."""
    import openai
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    response = openai.OpenAI(api_key=api_key).chat.completions.create(
        model=MODEL, max_tokens=250, temperature=0.0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": "You screen interview emails. Reply with valid JSON only."},
                  {"role": "user", "content": prompt}])
    return {"text": response.choices[0].message.content,
            "input_tokens": response.usage.prompt_tokens, "output_tokens": response.usage.completion_tokens}


_POSITION_CLOSED = re.compile(
    r"\b(?:position|role|requisition|opening|vacancy|job|posting)\b[^.\n]{0,60}\b(?:cancel+ed|closed|filled|withdrawn|no longer (?:available|open))\b"
    r"|\b(?:cancel+ed|closed|filled|withdrawn)\b[^.\n]{0,30}\b(?:position|role|requisition|opening|vacancy|job|posting)\b", re.I)
_MEETING_WORD = re.compile(r"interview|phone screen|screening|meeting|\bcall\b|appointment|scheduled|invitation|invite", re.I)


def closes_a_position_not_an_interview(subject: str, new_text: str) -> bool:
    """True when the new text says a job/role/requisition was cancelled or filled and never mentions an interview, call or meeting."""
    text = f"{subject or ''}. {new_text or ''}"
    return bool(_POSITION_CLOSED.search(text)) and not _MEETING_WORD.search(text)


_ROUND_WORDS = (
    ("final", re.compile(r"\bfinal (?:round|interview|stage)\b|\blast round\b", re.I)),
    ("3rd", re.compile(r"\b(?:third|3rd) (?:round|interview|stage)\b|\bround (?:3|three)\b|\bR3\b", re.I)),
    ("2nd", re.compile(r"\b(?:second|2nd) (?:round|interview|stage)\b|\bround (?:2|two)\b|\bR2\b", re.I)),
    ("1st", re.compile(r"\b(?:first|1st) (?:round|interview|stage)\b|\bround (?:1|one)\b|\bR1\b|\binitial interview\b|\bintro(?:duction|ductory)? call\b", re.I)),
)
_NOT_A_ROUND = ("Interview Cancelled", "Assessment", "Job Machine")
_ANNOUNCED = ("draft", "approved", "sent")


def infer_round(subject: str, new_text: str, history: List[Dict[str, Any]], company: Optional[str]) -> str:
    """
    The round of an interview, from facts only: '1st', '2nd', '3rd', 'final' or 'unknown'.
    1. The words of the email ("R2", "second round", "final interview"). Two different rounds named in one email = unknown.
    2. Else the student's earlier ANNOUNCED interviews at the same company (distinct date/time, assessments and cancellations excluded):
       one earlier means this is the 2nd, two earlier the 3rd. Zero earlier does not prove a 1st (the history may be incomplete), so it stays unknown.
    """
    text = f"{subject or ''}. {(new_text or '')[:1500]}"
    found = {name for name, rx in _ROUND_WORDS if rx.search(text)}
    if len(found) == 1:
        return found.pop()
    if found:
        return "unknown"
    key = _company_key(company)
    if not key:
        return "unknown"
    moments = {(h.get("date"), (h.get("time") or "")[:5]) for h in history
               if _company_key(h.get("company")) == key and h.get("status") in _ANNOUNCED and h.get("sub_type") not in _NOT_A_ROUND and h.get("date")}
    return {1: "2nd", 2: "3rd"}.get(len(moments), "unknown")


def would_hide_card(result: Optional[Dict[str, Any]]) -> bool:
    """True when the verdict says there is no news for the student AND the model is sure. No result = never hide."""
    return bool(result) and result["verdict"] not in SHOWS_CARD and result["confidence"] >= CONFIDENCE_FLOOR


def label(result: Optional[Dict[str, Any]]) -> Optional[str]:
    """The flag shown on a card, e.g. "2nd round · Phone" or "Rescheduled · In-person". None when there is nothing to flag."""
    if not result or result["verdict"] not in SHOWS_CARD:
        return None
    fmt = {"phone": "Phone", "video": "Video", "in-person": "In-person"}.get(result.get("format"))
    if result["verdict"] == "reschedule":
        head = "Rescheduled"
    elif result["verdict"] == "cancellation":
        head = "Cancelled"
    else:
        head = {"1st": "1st interview", "2nd": "2nd round", "3rd": "3rd round", "final": "Final round"}.get(result.get("round"), "Interview")
    return f"{head} · {fmt}" if fmt else head


def _company_key(name: Optional[str]) -> str:
    n = re.sub(r"[^a-z0-9 ]+", "", (name or "").lower().replace("&", " and "))
    return " ".join(w for w in n.split() if w not in ("inc", "llc", "corp", "corporation", "co", "ltd", "company", "the"))


def related_event_email_ids(db, before, exclude_email_id, company, student_id, interview_date, interview_time) -> List[int]:
    """Emails that already made an interview event for the same company, or at the same date and time (only this student's when known), newest first."""
    from models import Email, InterviewEvent
    key = _company_key(company)
    if not key and not (interview_date and interview_time):
        return []
    query = db.query(InterviewEvent, Email).join(Email, Email.id == InterviewEvent.email_id)
    if before is not None:
        query = query.filter(Email.received_date < before)
    if exclude_email_id is not None:
        query = query.filter(Email.id != exclude_email_id)
    if student_id is not None:
        query = query.filter((InterviewEvent.student_id == student_id) | (InterviewEvent.student_id.is_(None)))
    ids: List[int] = []
    for event, email in query.order_by(Email.received_date.desc(), InterviewEvent.id.desc()).limit(400).all():
        same_company = bool(key) and _company_key(event.company_name) == key
        same_moment = bool(interview_date and interview_time) and (event.interview_date, (event.interview_time or "")[:5]) == (interview_date, (interview_time or "")[:5])
        if (same_company or same_moment) and email.id not in ids:
            ids.append(email.id)
    return ids


def load_history(db, subject: str, from_address: str, before: Optional[datetime] = None,
                 exclude_email_id: Optional[int] = None, limit: int = HISTORY_LIMIT, company: Optional[str] = None,
                 student_id: Optional[int] = None, interview_date: Optional[str] = None,
                 interview_time: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    The last `limit` emails from the same sender (same domain, or the exact address for free mail) or with the same subject thread,
    newest first, each with its interview event and notice status when it has one. `before` keeps a replay honest: only mail older than the email.
    """
    from models import Email, InterviewEvent, NotificationDraft
    from text_cleaning import clean_email_text

    domain, address, subject_key = _domain(from_address), _plain_address(from_address), normalize_subject(subject)
    query = db.query(Email)
    if before is not None:
        query = query.filter(Email.received_date < before)
    if exclude_email_id is not None:
        query = query.filter(Email.id != exclude_email_id)
    candidates = query.order_by(Email.received_date.desc(), Email.id.desc()).limit(600).all()
    related = related_event_email_ids(db, before, exclude_email_id, company, student_id, interview_date, interview_time)
    by_id = {e.id: e for e in db.query(Email).filter(Email.id.in_(related)).all()} if related else {}
    picked = [by_id[i] for i in related if i in by_id][:limit]               # same company / same moment first: they are the likeliest originals
    for e in candidates:
        if len(picked) >= limit:
            break
        if e.id in by_id:
            continue
        same_sender = (_plain_address(e.from_address) == address) if (not domain or domain in FREE_MAIL) else (_domain(e.from_address) == domain)
        same_thread = bool(subject_key) and normalize_subject(e.subject) == subject_key
        if same_sender or same_thread:
            picked.append(e)
    picked.sort(key=lambda x: (x.received_date, x.id), reverse=True)
    rows = []
    for e in picked:
        event = db.query(InterviewEvent).filter(InterviewEvent.email_id == e.id).order_by(InterviewEvent.id).first()
        draft = (db.query(NotificationDraft).filter(NotificationDraft.interview_event_id == event.id).order_by(NotificationDraft.id).first()
                 if event is not None else None)
        category = None
        if getattr(e, "classifications", None):
            category = e.classifications[-1].category
        rows.append({"email_id": e.id, "received": e.received_date.strftime("%Y-%m-%d %H:%M") if e.received_date else None,
                     "from_address": e.from_address, "subject": e.subject, "category": category,
                     "sub_type": event.sub_type if event else None, "date": event.interview_date if event else None,
                     "time": event.interview_time if event else None, "company": event.company_name if event else None,
                     "status": draft.email_status if draft else None, "event_id": event.id if event else None,
                     "snippet": split_reply(clean_email_text(e.full_body or e.body_preview or ""))[0][:300]})
    return rows


def assess(db, subject: str, from_address: str, body: str, received: Optional[datetime] = None,
           exclude_email_id: Optional[int] = None, call: Callable[[str], Dict[str, Any]] = call_model, company: Optional[str] = None,
           student_id: Optional[int] = None, interview_date: Optional[str] = None, interview_time: Optional[str] = None,
           category: Optional[str] = None) -> Dict[str, Any]:
    """
    The gate's answer for one email. Never raises: on any failure `result` is None and `error` says why, which the caller treats as "do nothing".
    Returns {"result", "error", "new_text", "quoted_chars", "history", "cost_usd"}.
    """
    from text_cleaning import clean_email_text

    out: Dict[str, Any] = {"result": None, "error": None, "new_text": "", "quoted_chars": 0, "history": [], "cost_usd": 0.0}
    if category in SKIPPED_CATEGORIES:
        out["error"] = f"{category}: not screened by the interview gate"       # no model call, no verdict: the existing notice stays as it is
        return out
    try:
        new_text, quoted = split_reply(clean_email_text(body or ""))
        out["new_text"], out["quoted_chars"] = new_text, len(quoted)
        history = load_history(db, subject, from_address, before=received, exclude_email_id=exclude_email_id, company=company,
                               student_id=student_id, interview_date=interview_date, interview_time=interview_time)
        out["history"] = history
        try:
            from email_authenticity import assess as sender_check
            check = sender_check(subject, from_address, clean_email_text(body or "")[:6000], company)
        except Exception:                                   # noqa: BLE001 - the hint is optional
            check = None
        out["sender_check"] = check
        reply = call(build_prompt(subject, from_address, new_text, history, check))
        out["cost_usd"] = round(reply.get("input_tokens", 0) * 0.15 / 1e6 + reply.get("output_tokens", 0) * 0.60 / 1e6, 6)
        result = parse_response(reply.get("text"), history_size=len(history))
        if result is None:
            out["error"] = "unreadable answer"
        else:
            result["refers_to_event_id"] = history[result["refers_to"] - 1].get("event_id") if result["refers_to"] else None
            if result["verdict"] in ("new_interview", "reschedule") and result["round"] == "unknown":
                result["round"] = infer_round(subject, new_text, history, company)         # facts fill what the model left unknown; it is never overruled
            if result["verdict"] == "cancellation" and closes_a_position_not_an_interview(subject, new_text):
                # The model reads "the role has been cancelled" as an interview cancellation (events 142, 143, 146); the words decide, not the label.
                result.update(verdict="not_interview", confidence=max(result["confidence"], 0.9), refers_to=None, refers_to_event_id=None,
                              reason="A job position was cancelled; no interview or meeting is mentioned.")
            out["result"] = result
    except Exception as e:                                  # noqa: BLE001 - the gate must never break the pipeline
        out["error"] = f"{type(e).__name__}: {e}"
        logger.warning(f"Interview gate skipped: {out['error']}")
    return out


def record_review(db, out: Dict[str, Any], email_id: int, event_id: Optional[int], mode: str, source: str = "live") -> Optional[int]:
    """
    Save the gate's answer for one email (one row per email; a rerun updates it but never erases a person's decision).
    Returns the row id, or None if it could not be saved (a failure here must never block the pipeline).
    """
    try:
        from models import InterviewGateReview
        result = out.get("result") or {}
        row = db.query(InterviewGateReview).filter(InterviewGateReview.email_id == email_id).first()
        if row is None:
            row = InterviewGateReview(email_id=email_id)
            db.add(row)
        row.event_id, row.source, row.mode = event_id, source, mode
        row.verdict, row.round, row.format = result.get("verdict"), result.get("round"), result.get("format")
        row.confidence, row.reason = result.get("confidence"), result.get("reason")
        row.refers_to_event_id = result.get("refers_to_event_id")
        row.would_hide = would_hide_card(out.get("result"))
        row.error = (out.get("error") or None) and out["error"][:300]
        row.new_text = (out.get("new_text") or "")[:3000]
        row.quoted_chars = out.get("quoted_chars")
        row.history = [{k: h.get(k) for k in ("received", "subject", "category", "sub_type", "date", "time", "company", "status", "event_id")}
                       for h in out.get("history") or []]
        row.cost_usd = out.get("cost_usd")
        row.created_at = datetime.utcnow()
        db.commit()
        return row.id
    except Exception as e:                                  # noqa: BLE001
        logger.warning(f"Could not save the interview gate review: {e}")
        try:
            db.rollback()
        except Exception:                                   # noqa: BLE001
            pass
        return None
