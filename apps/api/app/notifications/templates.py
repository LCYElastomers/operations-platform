"""Restricted template rendering and validation.

Only ``{{variable.path}}`` placeholders against an allowlisted registry are
accepted. No Python, JavaScript, SQL, or property traversal beyond the registry.
Administrator HTML is sanitized with nh3 before storage and before send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import nh3

from app.notifications.registry import allowed_variables

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_.]*)\s*\}\}")

# Tags and attributes administrators may use in email HTML.
_ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "*": {"style"},
}
_ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    unresolved_variables: tuple[str, ...]
    unsupported_variables: tuple[str, ...]
    unsafe_content_findings: tuple[str, ...]
    missing_required: tuple[str, ...]


def extract_variables(text: str) -> list[str]:
    return list(dict.fromkeys(PLACEHOLDER.findall(text or "")))


def sanitize_html(html: str) -> str:
    return nh3.clean(
        html or "",
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_ALLOWED_URL_SCHEMES,
        strip_comments=True,
    )


def html_to_text(html: str) -> str:
    """Best-effort plain text from HTML when no explicit text template is given."""

    class _Collector(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            if data.strip():
                self.parts.append(data)

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
                self.parts.append("\n")

    parser = _Collector()
    parser.feed(html or "")
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
    return text


def validate_templates(
    *,
    event_type_code: str,
    subject: str,
    html: str,
    text: str,
) -> ValidationResult:
    allowed = allowed_variables(event_type_code)
    used = extract_variables(subject) + extract_variables(html) + extract_variables(text)
    unsupported = tuple(sorted({name for name in used if name not in allowed}))
    missing: list[str] = []
    if not (subject or "").strip():
        missing.append("subject")
    if not (html or "").strip() and not (text or "").strip():
        missing.append("body")
    cleaned = sanitize_html(html)
    unsafe: list[str] = []
    # If sanitization removed script-like content, surface a finding when raw differed.
    if "javascript:" in (html or "").lower() or "<script" in (html or "").lower():
        unsafe.append("Script or javascript: URLs are not allowed.")
    if "onerror=" in (html or "").lower() or "onclick=" in (html or "").lower():
        unsafe.append("Event-handler attributes are not allowed.")
    if cleaned != (html or "") and not unsafe:
        # Harmless normalization (e.g. attribute order) is fine; only warn on tag strip.
        raw_tags = set(re.findall(r"</?([a-zA-Z0-9]+)", html or ""))
        if raw_tags - _ALLOWED_TAGS - {t.upper() for t in _ALLOWED_TAGS}:
            unsafe.append("Disallowed HTML tags were removed.")
    return ValidationResult(
        valid=not unsupported and not missing and not unsafe,
        unresolved_variables=(),
        unsupported_variables=unsupported,
        unsafe_content_findings=tuple(unsafe),
        missing_required=tuple(missing),
    )


def render(template: str, context: dict[str, Any]) -> str:
    """Substitute ``{{path}}`` from a flat or dotted context. Missing keys raise."""

    def lookup(path: str) -> str:
        node: Any = context
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(path)
            node = node[part]
        if node is None:
            return ""
        return str(node)

    missing: list[str] = []

    def repl(match: re.Match[str]) -> str:
        path = match.group(1)
        try:
            return lookup(path)
        except KeyError:
            missing.append(path)
            return match.group(0)

    out = PLACEHOLDER.sub(repl, template or "")
    if missing:
        raise KeyError(", ".join(dict.fromkeys(missing)))
    return out


def render_email(
    *,
    subject_template: str,
    html_template: str,
    text_template: str,
    context: dict[str, Any],
) -> tuple[str, str, str]:
    subject = render(subject_template, context)
    html = sanitize_html(render(html_template, context))
    if text_template and text_template.strip():
        text = render(text_template, context)
    else:
        text = html_to_text(html)
    return subject, html, text
