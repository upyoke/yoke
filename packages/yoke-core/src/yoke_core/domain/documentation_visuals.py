"""Require readable Markdown alongside site-only explanatory visuals."""

from __future__ import annotations

import re

from markdown_it import MarkdownIt

from yoke_core.domain.documentation_navigation import NavigationRefusal

_MARKER = re.compile(r"^<!-- yoke:visual ([a-z0-9-]+) -->$", re.MULTILINE)


def validate_visual_fallbacks(page: str, markdown: str) -> list[NavigationRefusal]:
    """Each marked section needs prose, a list or a table readable on GitHub.

    Headings, comments, code, images and link-only paragraphs do not explain
    a visual. Parse Markdown so example markers in fenced code are inert.
    A heading starts a new section; text may precede or follow its visual.
    """
    refusals: list[NavigationRefusal] = []
    markers: list[tuple[str, int]] = []
    readable = False
    heading = False

    def finish() -> None:
        if readable:
            return
        for name, line in markers:
            refusals.append(
                NavigationRefusal(
                    "VISUAL_FALLBACK_MISSING",
                    f"{page}:{line}",
                    f"visual {name!r} has no readable text fallback in its section",
                    "add explanatory prose, a list or a table in the same section "
                    "so GitHub readers receive the explanation",
                )
            )

    for token in MarkdownIt("commonmark", {"html": True}).enable("table").parse(markdown):
        if token.type == "heading_open":
            finish()
            markers, readable, heading = [], False, True
        elif token.type == "heading_close":
            heading = False
        elif token.type == "html_block":
            for match in _MARKER.finditer(token.content):
                line = (token.map or [0])[0] + token.content[: match.start()].count("\n") + 1
                markers.append((match.group(1), line))
        elif token.type == "inline" and not heading:
            link_depth = 0
            for child in token.children or []:
                if child.type == "link_open":
                    link_depth += 1
                elif child.type == "link_close":
                    link_depth -= 1
                elif child.type == "text" and not link_depth:
                    readable |= any(char.isalpha() for char in child.content)
    finish()
    return refusals
