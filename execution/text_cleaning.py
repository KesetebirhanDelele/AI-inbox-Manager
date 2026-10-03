"""
Turn an HTML email body into readable text.

The old conversion only removed tags, so the CSS and <head> of marketing emails (fonts, media queries) ended up in the stored
preview and in what Rob reads ("<!DOCTYPE html> <html ... @import url(...) body{font-size:14px..."). This drops head, style, script and
comment blocks, keeps line breaks where the layout had them, decodes entities and collapses whitespace.
"""
import html
import re

_BLOCKS = re.compile(r"<(head|style|script|title)\b.*?</\1\s*>", re.I | re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BREAKS = re.compile(r"<\s*(?:br|/p|/div|/tr|/li|/h[1-6]|/table)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]*>")
_HTML_HINT = re.compile(r"<!doctype html|<html\b|<head\b|<body\b|<style\b|<table\b|<div\b|<p[ >]", re.I)


def looks_like_html(text: str) -> bool:
    return bool(text) and bool(_HTML_HINT.search(text[:3000]))


def clean_email_text(raw: str) -> str:
    """Readable text from an HTML (or plain) body. Plain text passes through with whitespace tidied."""
    if not raw:
        return ""
    text = raw
    if looks_like_html(raw):
        text = _COMMENT.sub(" ", text)
        text = _BLOCKS.sub(" ", text)
        text = _BREAKS.sub("\n", text)
        text = _TAG.sub(" ", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines()]
    out, blank = [], False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def clean_preview(preview: str, full_body: str = "", limit: int = 500) -> str:
    """The list preview: the stored one if it is already text, otherwise rebuilt from the full body."""
    if preview and not looks_like_html(preview):
        return preview
    return clean_email_text(full_body or preview or "")[:limit]
