"""
Split an email reply into what the sender just wrote and the older messages quoted under it.

Why: a one-line reply ("I've attached the job description") carries the whole earlier thread below it, including an old
"Interview Date Confirmation: Thursday, October 29, 10:30 AM". Readers of the full body (the classifier, the date extractor, the
authenticity check) then see a complete interview in a message that has none (Rutendo / Lorena Ortiz, 2026-10-26). Pure text rules, no AI, no I/O.

Safe by construction: the text is cut only where a reply marker appears AFTER some new text. An email that STARTS with a marker is
a forward (the interview mail itself), so it is kept whole. If almost nothing is left after the cut, the whole text is returned.
"""
import re
from typing import Tuple

MIN_NEW_CHARS = 15            # fewer than this left over: do not trust the cut, keep everything

_RULE = re.compile(r"^\s*[_\-=]{5,}\s*$")
_ORIGINAL = re.compile(r"^\s*-{2,}\s*(original message|reply message)\s*-{2,}\s*$", re.I)
_FORWARD = re.compile(r"^\s*-{2,}\s*(forwarded message|begin forwarded message)\s*-{2,}\s*$|^\s*begin forwarded message:?\s*$", re.I)
_ON_WROTE = re.compile(r"^\s*on\b.{4,250}\bwrote:\s*$", re.I)
_ON_WROTE_START = re.compile(r"^\s*on\b.{4,250}$", re.I)
_WROTE_END = re.compile(r"\bwrote:\s*$", re.I)
_HEADER_FROM = re.compile(r"^\s*(from|de|von):\s*\S", re.I)
_HEADER_NEXT = re.compile(r"^\s*(sent|date|to|subject|cc):\s*", re.I)
_QUOTE_LINE = re.compile(r"^\s*>")


def _is_header_block(lines, i: int) -> bool:
    """`From: x` followed within four lines by two more header lines (Sent/To/Subject/Date/Cc): an Outlook-style reply header."""
    if not _HEADER_FROM.match(lines[i]):
        return False
    window = [ln for ln in lines[i + 1:i + 6] if ln.strip()][:4]
    return sum(1 for ln in window if _HEADER_NEXT.match(ln)) >= 2


def _marker_at(lines, i: int) -> bool:
    line = lines[i]
    if _ORIGINAL.match(line):
        return True
    if _ON_WROTE.match(line):
        return True
    if _ON_WROTE_START.match(line) and i + 1 < len(lines) and _WROTE_END.search(lines[i + 1]):   # the "wrote:" wrapped onto the next line
        return True
    if _RULE.match(line):
        nxt = next((ln for ln in lines[i + 1:i + 4] if ln.strip()), "")
        return bool(_HEADER_FROM.match(nxt))
    return _is_header_block(lines, i)


def split_reply(text: str) -> Tuple[str, str]:
    """(new_text, quoted_text). quoted_text is "" when nothing was cut."""
    if not text:
        return "", ""
    lines = text.splitlines()
    seen_new = False
    for i, line in enumerate(lines):
        if _FORWARD.match(line):
            return text.strip(), ""                 # what follows a forward banner is the message being forwarded: keep it
        if _marker_at(lines, i):
            if not seen_new:
                return text.strip(), ""             # starts with a header: a forward, not a reply; keep it whole
            new_text = "\n".join(lines[:i]).strip()
            if len(re.sub(r"\s+", "", new_text)) < MIN_NEW_CHARS:
                return text.strip(), ""
            return new_text, "\n".join(lines[i:]).strip()
        if line.strip() and not _QUOTE_LINE.match(line):
            seen_new = True
    return text.strip(), ""


def new_text_only(text: str) -> str:
    """What the sender wrote in this message, without the thread under it."""
    return split_reply(text)[0]
