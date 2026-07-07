"""Markdown table primitives shared by the atlas doc renderers."""

from __future__ import annotations

from typing import Any, Iterable, List, Sequence


def _escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> List[str]:
    out: List[str] = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        out.append("| " + " | ".join(_escape_cell(cell) for cell in row) + " |")
    return out


__all__ = ["_escape_cell", "_md_table"]
