"""Which lines of a fleet report are new since the watcher's last one.

A report repeats every row still listed, and each row carries ages that
move every pass (``stage item-qa for 1h32m``, ``quiet 42m``,
``pending=10m``). Read whole, every pass looks new. A row is compared with
its elapsed-time and instant fields blanked; a changed row keeps the less
indented lines above it (its section heading, its run) so it still reads
in place. The raw capture keeps the whole report.

A report the watcher must cut short ends in :data:`PARTIAL_REPORT_NOTE`
instead of the closing marker; ``watch_tail`` closes its buffer on either.
"""

from __future__ import annotations

import re

PARTIAL_REPORT_NOTE = (
    "# watch_fleet report_partial: the probe ended before the closing marker\n"
)
#: Instants the report stamps, and ages it renders (``42s``, ``42m``, ``1h32m``).
_ELAPSED_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?"
    r"|\b\d+h\d{2}m\b|\b\d+[smhd]\b"
)


def row_identity(line: str) -> str:
    """One report line with its elapsed-time and instant fields blanked."""
    return _ELAPSED_RE.sub("<t>", line.rstrip("\n"))


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def changed_lines(body: list[str], seen: set[str]) -> list[str]:
    """Lines of ``body`` new since ``seen``, each with the lines it sits under."""
    kept: set[int] = set()
    above: list[tuple[int, int]] = []
    for index, line in enumerate(body):
        if not line.strip():
            continue
        depth = _indent(line)
        while above and above[-1][0] >= depth:
            above.pop()
        changed = row_identity(line) not in seen
        if changed:
            kept.update(parent for _, parent in above)
            kept.add(index)
        above.append((depth, index))
    partial: set[int] = set()
    above = []
    for index, line in enumerate(body):
        if not line.strip():
            continue
        depth = _indent(line)
        while above and above[-1][0] >= depth:
            above.pop()
        if index not in kept:
            partial.update(parent for _, parent in above if parent in kept)
        above.append((depth, index))
    return [
        _partial_heading(line) if index in partial else line
        for index, line in enumerate(body) if index in kept
    ]


def _partial_heading(line: str) -> str:
    """Mark a heading whose report shows only some of its rows.

    The suffix goes inside the line, before its newline: a suffix after the
    newline would start the next line, and on the report's last heading it
    would corrupt the closing marker a reader waits for.
    """
    text = line.rstrip("\n")
    ending = line[len(text):]
    suffix = " (changes only)"
    if " — " in text:
        heading, rest = text.split(" — ", 1)
        return f"{heading}{suffix} — {rest}{ending}"
    if text.endswith(":"):
        return f"{text[:-1]}{suffix}:{ending}"
    return f"{text}{suffix}{ending}"


__all__ = ["PARTIAL_REPORT_NOTE", "changed_lines", "row_identity"]
