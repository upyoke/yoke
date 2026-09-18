"""The two answers a routine read can give, and the excerpt width they share.

Several reads serve a small routine answer and a much larger complete one:
a mailbox page, a QA plan, the operator execution instructions bound to a
workflow and project. Their default is ``summary`` — the fields a caller
scanning a list actually reads — and the complete document is served only
when the caller asks for ``full``.

The vocabulary is one closed pair rather than a per-read flag name so a
reader who learns it on one surface already knows it on the next, and so
an adapter's ``--full`` maps to the same request field everywhere.

A summary that carries prose carries one excerpt of it, cut to
``SUMMARY_EXCERPT_CHARACTERS``. Truncation happens where the projection is
built, not where it is printed: a caller reading ``--json`` is the one
whose context the summary exists to protect.
"""

from __future__ import annotations

from typing import Literal

DETAIL_SUMMARY = "summary"
DETAIL_FULL = "full"

#: Request-field vocabulary shared by every read that has both shapes.
ReadDetail = Literal["summary", "full"]

#: Characters of prose a summary row carries before it is cut.
SUMMARY_EXCERPT_CHARACTERS = 72


def excerpt(value: object, limit: int = SUMMARY_EXCERPT_CHARACTERS) -> str:
    """Return the first line of ``value``, cut to ``limit`` with an ellipsis."""
    text = " ".join(str(value or "").strip().splitlines()[:1]).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


__all__ = [
    "DETAIL_FULL",
    "DETAIL_SUMMARY",
    "ReadDetail",
    "SUMMARY_EXCERPT_CHARACTERS",
    "excerpt",
]
