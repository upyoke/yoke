"""Width-budgeted Claims-column wrapping shared by both session tables."""

from __future__ import annotations

from yoke_contracts.board.sections_sessions_layout import (
    _CLAIMS_WRAP_WIDTH,
    _chunk_claims,
)
from yoke_contracts.board.utils import display_width


def test_chunk_claims_single_row_under_budget():
    assert _chunk_claims(["YOK-1", "YOK-2"]) == ["1. YOK-1 · 2. YOK-2"]


def test_chunk_claims_wraps_past_width_budget():
    targets = [f"YOK-{n}" for n in (1900, 1901, 1902, 1903, 1904, 1905)]
    rows = _chunk_claims(targets)
    assert len(rows) > 1
    assert all(display_width(row) <= _CLAIMS_WRAP_WIDTH for row in rows)
    # Numbering stays global across wrapped rows.
    assert rows[0].startswith("1. ")
    joined = " · ".join(rows)
    assert "6. YOK-1905" in joined


def test_chunk_claims_oversized_single_entry_gets_own_row():
    targets = ["X" * (_CLAIMS_WRAP_WIDTH + 20), "YOK-1"]
    rows = _chunk_claims(targets)
    assert len(rows) == 2
    assert rows[1] == "2. YOK-1"
