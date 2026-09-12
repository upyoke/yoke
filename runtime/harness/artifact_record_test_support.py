"""Artifact fixtures the record-reading suites share.

Both suites need the same two shapes: a JSONL artifact written whole, and
a record padded to a chosen size so a test can state its bound in bytes
rather than in rows.
"""

from __future__ import annotations

import json
from pathlib import Path


def write_rows(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def padded_row(index: int, size: int, filler: str = "a") -> dict:
    return {"index": index, "filler": filler * size}


__all__ = ["padded_row", "write_rows"]
