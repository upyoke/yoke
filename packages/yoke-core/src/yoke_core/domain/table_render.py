"""Table rendering utilities for Yoke engines.

Provides pipe-delimited and Markdown table formatting, replacing shell
``printf``/``column`` patterns with Python equivalents.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

Row = Any


def _get(row: Row, key: str) -> str:
    """Extract a string value from a Row or dict, defaulting to empty."""
    try:
        val = row[key]
    except (KeyError, IndexError):
        val = None
    return "" if val is None else str(val)


def pipe_delimited(rows: Sequence[Row], columns: List[str]) -> str:
    """Render *rows* as pipe-delimited text (no header, no padding).

    Each output line has the form ``col1|col2|col3``.
    """
    lines: list[str] = []
    for row in rows:
        parts = [_get(row, c) for c in columns]
        lines.append("|".join(parts))
    return "\n".join(lines)


def markdown_table(
    rows: Sequence[Row],
    columns: List[str],
    headers: Optional[List[str]] = None,
) -> str:
    """Render *rows* as a Markdown table with aligned columns.

    Parameters
    ----------
    rows:
        Sequence of row-like objects or dicts.
    columns:
        Column keys to extract from each row.
    headers:
        Display headers.  Defaults to *columns* when ``None``.
    """
    hdrs = headers if headers is not None else columns

    if len(hdrs) != len(columns):
        raise ValueError(
            f"headers length ({len(hdrs)}) must match columns length ({len(columns)})"
        )

    # Compute column widths (minimum 3 for separator dashes)
    widths = [max(3, len(h)) for h in hdrs]
    str_rows: list[list[str]] = []
    for row in rows:
        cells = [_get(row, c) for c in columns]
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], len(cell))
        str_rows.append(cells)

    # Build header line
    header_line = "| " + " | ".join(h.ljust(w) for h, w in zip(hdrs, widths)) + " |"
    sep_line = "| " + " | ".join("-" * w for w in widths) + " |"

    lines = [header_line, sep_line]
    for cells in str_rows:
        data_line = "| " + " | ".join(
            c.ljust(w) for c, w in zip(cells, widths)
        ) + " |"
        lines.append(data_line)

    return "\n".join(lines)
