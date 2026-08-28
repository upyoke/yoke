"""Claims-column layout helpers for the BOARD.md sessions tables.

Sibling of :mod:`yoke_contracts.board.sections_sessions`. Owns the pure
target-list layout step shared by the Active and Recent Harness Sessions
tables: width-budgeted row wrapping. Keeps the parent module focused on the
table assembly and the keycap decoration in
:mod:`sections_sessions_holdings`.
"""

from __future__ import annotations

from yoke_contracts.board.utils import display_width


# Max display width of a single Claims-cell row before wrapping to a new
# continuation row. Sized to keep the column narrow on the board; a single
# entry wider than this still occupies its own row rather than being split.
_CLAIMS_WRAP_WIDTH = 43


def _index_prefix(n: int) -> str:
    """Render a positive integer as a plain index prefix (universal; no VS16 keycaps)."""
    return f"{n}."


def _chunk_claims(targets: list[str], max_width: int = _CLAIMS_WRAP_WIDTH) -> list[str]:
    """Group numbered claims into rows, wrapping past a display-width budget.

    Each entry renders as ``N. <target>`` joined by ` · `. A new row starts
    when appending the next entry would push the row's display width past
    ``max_width``; numbering is global (1., 2., 3., …) across wrapped rows.
    """
    rows: list[str] = []
    current: list[str] = []
    current_width = 0
    sep_width = display_width(" · ")
    for i, t in enumerate(targets):
        entry = f"{_index_prefix(i + 1)} {t}"
        entry_width = display_width(entry)
        projected = (
            entry_width if not current else current_width + sep_width + entry_width
        )
        if current and projected > max_width:
            rows.append(" · ".join(current))
            current = [entry]
            current_width = entry_width
        else:
            current.append(entry)
            current_width = projected
    if current:
        rows.append(" · ".join(current))
    return rows


__all__ = [
    "_CLAIMS_WRAP_WIDTH",
    "_chunk_claims",
    "_index_prefix",
]
