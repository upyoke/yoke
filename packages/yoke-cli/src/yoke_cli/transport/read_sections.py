"""One Markdown section of a registered human read, and its heading outline.

A long document read must never dead-end: an oversized reply whose text has
headings teaches the exact ``--section`` command for each one, and that
command prints only the named section. Section identity and extent come from
the shared scanner in ``yoke_contracts.project_contract.strategy_doc_fields``.
"""

from __future__ import annotations

from itertools import accumulate

from yoke_contracts.project_contract.strategy_doc_fields import (
    find_section,
    section_spans,
)

# An outline is a menu, not a second answer: it stays well inside one reply.
OUTLINE_BUDGET_BYTES = 8_000


def select_section(text: str, heading: str) -> str | None:
    """The section titled *heading*, with its heading line, or ``None``."""
    span = find_section(text, heading)
    if span is None:
        return None
    lines = text.splitlines()[span.heading_index : span.body_end]
    return "\n".join(lines).rstrip() + "\n"


def section_outline(text: str, command_for) -> str | None:
    """Each heading with its size and exact read command, or ``None``.

    *command_for* maps a heading to the command that reads it, or ``None``
    when this read cannot select a section. Deeper levels drop first when
    the whole outline would not fit, but the two shallowest levels always
    show, so a document under one title still lists the sections inside it.
    """
    spans = section_spans(text)
    if not spans or command_for(spans[0][0]) is None:
        return None
    lines = text.splitlines()
    offsets = [0, *accumulate(len(line.encode("utf-8")) + 1 for line in lines)]
    seen: set[str] = set()
    rows: list[tuple[int, str]] = []
    for heading, span in spans:
        if heading.casefold() not in seen:
            seen.add(heading.casefold())
            size = offsets[span.body_end] - offsets[span.heading_index]
            rows.append((span.level, f"- {heading} ({size} bytes): {command_for(heading)}"))
    levels = sorted({level for level, _ in rows})
    top = levels[0]
    entries: list[str] = []
    for depth in reversed(levels[1:] or levels):
        entries = [
            "  " * (level - top) + entry for level, entry in rows if level <= depth
        ]
        if len("\n".join(entries).encode("utf-8")) <= OUTLINE_BUDGET_BYTES:
            break
    shown = _head_and_tail(entries)
    deeper = (
        "\nRead a listed section to see the headings under it."
        if len(entries) < len(rows)
        else ""
    )
    return "Read one section:\n" + "\n".join(shown) + deeper


def _head_and_tail(entries: list[str]) -> list[str]:
    """Entries within budget; when some must go, keep both ends.

    Documents lead with their overview and logs end with their newest
    entry, so the middle is what an outline drops.
    """
    if len("\n".join(entries).encode("utf-8")) <= OUTLINE_BUDGET_BYTES:
        return entries
    half = OUTLINE_BUDGET_BYTES // 2
    head: list[str] = []
    tail: list[str] = []
    used = 0
    for entry in entries:
        used += len(entry.encode("utf-8")) + 1
        if used > half:
            break
        head.append(entry)
    used = 0
    for entry in reversed(entries[len(head) :]):
        used += len(entry.encode("utf-8")) + 1
        if used > half:
            break
        tail.insert(0, entry)
    hidden = len(entries) - len(head) - len(tail)
    return [*head, f"- ({hidden} more headings not shown)", *tail]


__all__ = ["OUTLINE_BUDGET_BYTES", "section_outline", "select_section"]
