"""Small text helpers shared across connectors.

Job descriptions from ATS APIs arrive as HTML. For storage, matching, and LLM
tailoring we want readable plain text, so we strip tags here rather than pulling in
a heavy dependency.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: object) -> None:
        # Turn block-level breaks into newlines so paragraphs/lists stay readable.
        if tag in {"br", "p", "li", "div", "tr", "h1", "h2", "h3", "h4", "ul", "ol"}:
            self._parts.append("\n")

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(raw: str | None) -> str:
    """Convert (possibly entity-encoded) HTML into collapsed plain text."""
    if not raw:
        return ""
    # Greenhouse double-encodes: the content field is HTML with escaped entities.
    unescaped = html.unescape(raw)
    parser = _TextExtractor()
    parser.feed(unescaped)
    text = parser.text()
    # Collapse runs of blank lines and trailing whitespace.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()
