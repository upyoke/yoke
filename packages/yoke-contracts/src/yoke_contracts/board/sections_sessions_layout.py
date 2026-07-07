"""Claims-column layout helpers for the BOARD.md sessions tables.

Sibling of :mod:`yoke_contracts.board.sections_sessions`. Owns the pure
target-list layout step shared by the Active and Recent Harness Sessions
tables: dedup of repeat claims and width-budgeted row wrapping. Keeps the
parent module focused on the table assembly and the keycap decoration in
:mod:`sections_sessions_extra_claims`.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from yoke_contracts.board.utils import display_width


# Max display width of a single Claims-cell row before wrapping to a new
# continuation row. Sized to keep the column narrow on the board; a single
# entry wider than this still occupies its own row rather than being split.
_CLAIMS_WRAP_WIDTH = 43


def _index_prefix(n: int) -> str:
    """Render a positive integer as a plain index prefix (universal; no VS16 keycaps)."""
    return f"{n}."


def _dedup_work_targets(
    targets: List[Tuple[str, Optional[int], Optional[str]]],
) -> List[Tuple[str, Optional[int], Optional[str]]]:
    """Collapse repeat claims on the same target to the most recent one.

    A session may claim the same item several times (e.g. re-acquired across a
    lifecycle loop). ``_claims_for_session`` returns rows newest-first, so the
    first occurrence of each rendered target is the most recent — keep it and
    drop the rest. Distinct items are each kept once, preserving the
    most-recent-first order. Keying on the rendered target string (not the raw
    item_id) keeps process-key and epic-task targets — whose item_id is None —
    distinct from one another.
    """
    seen: set[str] = set()
    deduped: List[Tuple[str, Optional[int], Optional[str]]] = []
    for entry in targets:
        key = entry[0]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


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
            entry_width if not current
            else current_width + sep_width + entry_width
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
    "_dedup_work_targets",
    "_index_prefix",
]
