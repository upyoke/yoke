"""Tests for the Claims-column layout helpers.

Covers :func:`_dedup_work_targets` (collapse repeat claims on the same
target to the most recent) and :func:`_chunk_claims` (width-budgeted row
wrapping) — the shared layout step behind both the Active and Recent
Harness Sessions tables.
"""

from __future__ import annotations

from yoke_contracts.board.sections_sessions_layout import (
    _CLAIMS_WRAP_WIDTH,
    _chunk_claims,
    _dedup_work_targets,
)
from yoke_contracts.board.utils import display_width


def test_dedup_keeps_most_recent_claim_per_item():
    # _claims_for_session orders newest-first, so the first occurrence of a
    # repeated target is the most recent and the only one kept.
    targets = [
        ("YOK-1902", 1902, "released"),
        ("YOK-1902", 1902, "completed"),
        ("YOK-1902", 1902, "session_ended"),
    ]
    assert _dedup_work_targets(targets) == [("YOK-1902", 1902, "released")]


def test_dedup_keeps_each_distinct_item_once_in_order():
    targets = [
        ("YOK-1902", 1902, "released"),
        ("YOK-1900", 1900, "released"),
        ("YOK-1902", 1902, "completed"),
        ("YOK-1901", 1901, None),
    ]
    assert _dedup_work_targets(targets) == [
        ("YOK-1902", 1902, "released"),
        ("YOK-1900", 1900, "released"),
        ("YOK-1901", 1901, None),
    ]


def test_dedup_keeps_distinct_none_item_targets_separate():
    # Process-key / epic-task targets carry item_id=None; keying on the
    # rendered string keeps distinct ones separate.
    targets = [
        ("🔩 deploy-lock", None, None),
        ("YOK-1902 T004", None, None),
        ("🔩 deploy-lock", None, None),
    ]
    assert _dedup_work_targets(targets) == [
        ("🔩 deploy-lock", None, None),
        ("YOK-1902 T004", None, None),
    ]


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
