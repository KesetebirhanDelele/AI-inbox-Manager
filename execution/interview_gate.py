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
HISTORY_LIMIT = 10
NEW_TEXT_LIMIT = 3000
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com", "live.com", "msn.com", "proton.me", "protonmail.com"}

PROMPT = """You screen interview-related emails for a career placement program. The email below was already thought to be about a job interview.
Decide whether its NEW text (what the sender just wrote, without the older thread) brings NEWS about an interview.

Verdicts (choose exactly one):
- new_interview: arranges an interview that is not in the history yet (a first interview, or a 2nd / 3rd / final round).
- reschedule: moves an interview already in the history to a different date or time.
- cancellation: cancels an interview.
- follow_up: a reminder, directions, a document, or logistics about an interview already in the history. No new time.
- confirmation: repeats or confirms an interview already in the history at the same time.
- not_interview: nothing about arranging, moving or cancelling an interview (a courtesy reply, thanks, an attachment, a job board mailer).

Rules:
- Judge ONLY the NEW text. A date that appears only in older history is not news.
- The history lines are earlier emails with the same sender, newest first. "notice=sent/approved/draft" means the student was told or is about to be.
- round: "1st", "2nd", "3rd" or "final" if the email or the history makes it clear, else "unknown". Never guess.
- format: "phone", "video", "in-person" or "unknown", from the NEW text.
- refers_to: the history number (the [n]) of the interview this is a follow_up/confirmation/reschedule/cancellation of, else null.
- If unsure, lower the confidence. Do not invent details.

Answer with JSON only: {{"verdict": "...", "round": "...", "format": "...", "refers_to": null, "confidence": 0.0, "reason": "one short sentence"}}

FROM: {sender}
SUBJECT: {subject}
HISTORY (last emails from this sender, newest first):
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


def build_prompt(subject: str, sender: str, new_text: str, history: List[Dict[str, Any]]) -> str:
    lines = [history_line(i + 1, row) for i, row in enumerate(history)] or ["(no earlier emails from this sender)"]
    return PROMPT.format(sender=sender or "?", subject=subject or "(no subject)", history="\n".join(lines),
                         new_text=(new_text or "(empty)")[:NEW_TEXT_LIMIT])


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


def load_history(db, subject: str, from_address: str, before: Optional[datetime] = None,
                 exclude_email_id: Optional[int] = None, limit: int = HISTORY_LIMIT) -> List[Dict[str, Any]]:
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
    picked = []
    for e in candidates:
        same_sender = (_plain_address(e.from_address) == address) if (not domain or domain in FREE_MAIL) else (_domain(e.from_address) == domain)
        same_thread = bool(subject_key) and normalize_subject(e.subject) == subject_key
        if same_sender or same_thread:
            picked.append(e)
        if len(picked) >= limit:
            break
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
           exclude_email_id: Optional[int] = None, call: Callable[[str], Dict[str, Any]] = call_model) -> Dict[str, Any]:
    """
    The gate's answer for one email. Never raises: on any failure `result` is None and `error` says why, which the caller treats as "do nothing".
    Returns {"result", "error", "new_text", "quoted_chars", "history", "cost_usd"}.
    """
    from text_cleaning import clean_email_text

    out: Dict[str, Any] = {"result": None, "error": None, "new_text": "", "quoted_chars": 0, "history": [], "cost_usd": 0.0}
    try:
        new_text, quoted = split_reply(clean_email_text(body or ""))
        out["new_text"], out["quoted_chars"] = new_text, len(quoted)
        history = load_history(db, subject, from_address, before=received, exclude_email_id=exclude_email_id)
        out["history"] = history
        reply = call(build_prompt(subject, from_address, new_text, history))
        out["cost_usd"] = round(reply.get("input_tokens", 0) * 0.15 / 1e6 + reply.get("output_tokens", 0) * 0.60 / 1e6, 6)
        result = parse_response(reply.get("text"), history_size=len(history))
        if result is None:
            out["error"] = "unreadable answer"
        else:
            result["refers_to_event_id"] = history[result["refers_to"] - 1].get("event_id") if result["refers_to"] else None
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
