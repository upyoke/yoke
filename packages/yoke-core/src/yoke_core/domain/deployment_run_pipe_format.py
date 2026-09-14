"""Pipe-delimited formatting shared by deployment-run CLI readers."""

from __future__ import annotations


def pipe_row(row) -> str:
    return "|".join(str(value) for value in row)


def pipe_rows(rows) -> str:
    return "\n".join(pipe_row(row) for row in rows)


__all__ = ["pipe_row", "pipe_rows"]
