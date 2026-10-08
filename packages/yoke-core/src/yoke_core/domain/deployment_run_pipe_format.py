"""Pipe-delimited formatting shared by deployment-run CLI readers."""

from __future__ import annotations

from datetime import datetime
from yoke_contracts.timestamps import format_instant


def pipe_row(row) -> str:
    return "|".join(
        ""
        if value is None
        else format_instant(value)
        if isinstance(value, datetime)
        else str(value)
        for value in row
    )


def pipe_rows(rows) -> str:
    return "\n".join(pipe_row(row) for row in rows)


__all__ = ["pipe_row", "pipe_rows"]
