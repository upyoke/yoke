"""Locate and rewrite one Markdown section of a strategy document.

A strategy document is one row, so refreshing a single section meant
sending the whole document back. On a 70KB plan that is a splice the
caller performs by hand on every update — fifteen of them in one steering
session — and each one risks carrying an unrelated edit, or losing one,
because the transport is the entire body either way.

Section identity is the heading text, matched case-insensitively at any
heading level, and a section runs until the next heading at the same level
or shallower. A nested deeper heading belongs to the section it sits
under, so replacing "Live status" replaces its subsections with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class StrategyDocSectionMissingError(LookupError):
    """The named heading is not in the document."""


@dataclass(frozen=True)
class SectionSpan:
    """Where one section's heading and body sit in a document's lines."""

    #: Index of the heading line itself.
    heading_index: int
    #: Heading depth, which decides where the section ends.
    level: int
    #: First line after the heading, and first line that is no longer inside.
    body_start: int
    body_end: int


def section_headings(content: str) -> tuple[str, ...]:
    """Every heading in the document, in order, as written."""
    return tuple(
        match.group(2).strip()
        for match in (_HEADING_RE.match(line) for line in content.splitlines())
        if match is not None
    )


def find_section(content: str, heading: str) -> SectionSpan | None:
    """The span of the first section titled *heading*, or ``None``."""
    lines = content.splitlines()
    wanted = heading.strip().casefold()
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match is None or match.group(2).strip().casefold() != wanted:
            continue
        level = len(match.group(1))
        body_end = len(lines)
        for ahead in range(index + 1, len(lines)):
            next_heading = _HEADING_RE.match(lines[ahead])
            if next_heading is not None and len(next_heading.group(1)) <= level:
                body_end = ahead
                break
        return SectionSpan(
            heading_index=index,
            level=level,
            body_start=index + 1,
            body_end=body_end,
        )
    return None


def replace_section(content: str, heading: str, body: str) -> str:
    """Return *content* with the body of *heading* replaced by *body*.

    Refuses a heading the document does not have. A section replace that
    quietly appended a new section would report success for a heading the
    caller misspelled, and the document the caller believed it had edited
    would still say the old thing.
    """
    span = find_section(content, heading)
    if span is None:
        present = ", ".join(section_headings(content)) or "none"
        raise StrategyDocSectionMissingError(
            f"strategy document has no section titled {heading!r}; its "
            f"headings are: {present}. Use `strategy.doc.replace` to add a "
            "new section."
        )
    lines = content.splitlines()
    kept_heading = lines[span.heading_index]
    replacement = body.strip().splitlines()
    tail = lines[span.body_end :]
    rebuilt = [
        *lines[: span.heading_index],
        kept_heading,
        "",
        *replacement,
    ]
    if tail:
        rebuilt.extend(["", *tail])
    return "\n".join(rebuilt).rstrip() + "\n"


__all__ = [
    "SectionSpan",
    "StrategyDocSectionMissingError",
    "find_section",
    "replace_section",
    "section_headings",
]
