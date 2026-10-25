"""Authored strategy card fields, Markdown sections, and validation.

Section identity is the heading text, matched case-insensitively at any
heading level with any leading ``#`` marks ignored, and a section runs until
the next heading at the same level or shallower. Headings inside fenced
examples are not headings. The CLI section read and the strategy section
replace share this one scanner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SUMMARY_MAX_CHARS = 60
STATE_MAX_CHARS = 16
FIELD_LIMITS = {"Summary": SUMMARY_MAX_CHARS, "State": STATE_MAX_CHARS}
_FIELD = re.compile(r"^(Summary|State)(?:\s+\(\d+ chars max\))?$", re.I)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class StrategyDocFieldError(ValueError):
    """A document cannot save an invalid authored card field."""


def field_name(heading: str) -> str | None:
    match = _FIELD.fullmatch(heading.strip())
    return match.group(1).title() if match else None


def field_heading(name: str) -> str:
    return f"## {name} ({FIELD_LIMITS[name]} chars max)"


def fields_rule() -> str:
    """What every edit of a strategy document must keep."""
    return (
        f"The document must keep {field_heading('Summary')} and "
        f"{field_heading('State')} present, unique, non-empty, and one line "
        "each. State is free text."
    )


def fields_recipe() -> str:
    return (
        f"Create with --summary TEXT ({SUMMARY_MAX_CHARS} chars max) and "
        f"--state TEXT ({STATE_MAX_CHARS} chars max); edits and ingest must "
        f"keep {field_heading('Summary')} and {field_heading('State')} "
        "present, unique, non-empty, and one line each. State is free text."
    )


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """Markdown headings outside fenced examples, with index and depth."""
    result = []
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        match = _HEADING.match(line) if fence is None else None
        if match:
            result.append((index, len(match.group(1)), match.group(2)))
    return result


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


def section_spans(content: str) -> tuple[tuple[str, SectionSpan], ...]:
    """Every heading outside fenced examples, in order, with its span."""
    lines = content.splitlines()
    headings = _headings(lines)
    return tuple(
        (
            text,
            SectionSpan(
                heading_index=index,
                level=level,
                body_start=index + 1,
                body_end=next(
                    (i for i, depth, _ in headings[position + 1 :] if depth <= level),
                    len(lines),
                ),
            ),
        )
        for position, (index, level, text) in enumerate(headings)
    )


def section_headings(content: str) -> tuple[str, ...]:
    """Every heading in the document, in order, as written."""
    return tuple(text for _, _, text in _headings(content.splitlines()))


def _section_key(heading: str) -> str:
    text = heading.strip().lstrip("#").strip()
    return (field_name(text) or text).casefold()


def find_section(content: str, heading: str) -> SectionSpan | None:
    """The span of the first section titled *heading*, or ``None``."""
    wanted = _section_key(heading)
    return next(
        (span for text, span in section_spans(content) if _section_key(text) == wanted),
        None,
    )


def _spans(lines: list[str]) -> list[tuple[str, int, int]]:
    headings = _headings(lines)
    result = []
    for position, (index, level, heading) in enumerate(headings):
        name = field_name(heading) if level == 2 else None
        if name:
            end = next(
                (i for i, depth, _ in headings[position + 1 :] if depth <= level),
                len(lines),
            )
            end = next(
                (
                    i
                    for i in range(index + 1, end)
                    if re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", lines[i])
                ),
                end,
            )
            result.append((name, index, end))
    return result


def validate_field(name: str, value: str) -> str:
    limit = FIELD_LIMITS[name]
    clean = value.strip()
    length = len(clean)
    fix = f"write one non-empty line of {limit} characters or fewer"
    if (
        not clean
        or ("\n" in value or "\r" in value or len(value.splitlines()) > 1)
        or length > limit
    ):
        raise StrategyDocFieldError(
            f"{field_heading(name)} is {length} characters (limit {limit}); {fix}."
        )
    return clean


def normalize_fields(content: str) -> str:
    """Validate both fields before normalizing any heading or field value."""
    lines = content.splitlines()
    spans = _spans(lines)
    replacements = []
    for name, limit in FIELD_LIMITS.items():
        matches = [(start, end) for field, start, end in spans if field == name]
        if len(matches) != 1:
            length = sum(
                len("\n".join(lines[start + 1 : end]).strip()) for start, end in matches
            )
            raise StrategyDocFieldError(
                f"{field_heading(name)} is {'missing' if not matches else 'duplicated'} "
                f"({length} characters; limit {limit}); add exactly one "
                f"{field_heading(name)} followed by one non-empty line of "
                f"{limit} characters or fewer."
            )
        start, end = matches[0]
        value = validate_field(name, "\n".join(lines[start + 1 : end]).strip())
        replacements.append((start, end, [field_heading(name), "", value, ""]))
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = replacement
    return "\n".join(lines).rstrip() + "\n"


def insert_fields(content: str, **values: str) -> tuple[str, list[str]]:
    """Explicit fields win over body copies; insert after the first H1."""
    clean = {name: validate_field(name, value) for name, value in values.items()}
    lines = content.splitlines()
    replaced = []
    for name, start, end in reversed(_spans(lines)):
        if name in clean:
            replaced.append(name)
            del lines[start:end]
    title = next((i for i, depth, _ in _headings(lines) if depth == 1), None)
    position = title + 1 if title is not None else 0
    inserted = []
    for name in FIELD_LIMITS:
        if name in clean:
            inserted.extend(["", field_heading(name), "", clean[name]])
    following = next((line for line in lines[position:] if line.strip()), "")
    boundary = ["", "---"] if following and not _HEADING.match(following) else []
    lines[position:position] = [
        *(inserted if position else inserted[1:]),
        *boundary,
        "",
    ]
    return "\n".join(lines).rstrip() + "\n", sorted(set(replaced))


def read_field(content: str, name: str) -> str | None:
    lines = content.splitlines()
    span = next(
        ((start, end) for field, start, end in _spans(lines) if field == name), None
    )
    if span is None:
        return None
    start, end = span
    value = " ".join(line.strip() for line in lines[start + 1 : end] if line.strip())
    return value or None


def body_without_fields(content: str) -> str:
    """Return the document narrative without its authored card metadata."""
    lines = content.splitlines()
    for _, start, end in reversed(_spans(lines)):
        del lines[start:end]
        if start < len(lines) and lines[start].strip() == "---":
            del lines[start]
    return "\n".join(lines).strip() + "\n"
