"""Backlog file-line-limit gate shim.

File-line enforcement is product-local: git pre-commit, ``yoke check
file-line``, and checkout-backed verification commands. Prod core normally has
no project checkout, so lifecycle transitions must not pretend to enforce this
filesystem rule centrally.
"""

from __future__ import annotations

from typing import Optional


_FILE_LINE_GATE_TARGETS = frozenset()


def _run_file_line_gate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict]:
    """Lifecycle no-op retained for the authoritative-gate composition point."""
    return None


__all__ = ["_FILE_LINE_GATE_TARGETS", "_run_file_line_gate"]
