"""Cross-surface dedup regressions for chain_skip_memory item-id normalization.

The recorder accepts both ``YOK-N`` and bare-numeric input; the scheduler's
candidate list always carries ``c.item_id = "YOK-N"``. Before normalization the
boundary compared raw strings, so a ``'<int>'`` skip-memory entry never
filtered a ``'YOK-<int>'`` candidate. Coverage here pins the contract: every
candidate-filter site canonicalises both sides via ``normalize_claim_item_id``
so all three skip-id formats ``{<int>, '<int>', 'YOK-<int>'}`` filter the
``YOK-N`` candidate out, and existing rows persisted in non-canonical form
still filter correctly without a DB rewrite.
"""

from __future__ import annotations

from typing import Iterable

import pytest

from yoke_core.domain.scheduler_types import (
    ClaimState,
    NextStep,
    ScheduledStep,
    SchedulerResult,
    SMLState,
)
from yoke_core.domain.session_offer_invariant_events import (
    _summarise_skip_memory,
)
from yoke_core.api.service_client_sessions_frontier import (
    build_frontier_state_from_schedule,
)


_ITEM_NUM = 1785
_YOKE_ITEM_REF = f"YOK-{_ITEM_NUM}"


def _make_step(item_id: str, rank: int) -> ScheduledStep:
    return ScheduledStep(
        item_id=item_id,
        item_type="issue",
        status="refined-idea",
        title=f"{item_id} title",
        priority="medium",
        next_step=NextStep.ADVANCE,
        rank=rank,
        claim_state=ClaimState.UNCLAIMED,
    )


def _schedule_with_two_candidates() -> SchedulerResult:
    steps = [
        _make_step(_YOKE_ITEM_REF, rank=0),
        _make_step("YOK-1786", rank=1),
    ]
    return SchedulerResult(
        project_scope=["yoke"],
        sml_state=SMLState(coherent=True),
        ranked_steps=steps,
        selected_step=steps[0],
    )


@pytest.mark.parametrize(
    "skip_memory_item_ids",
    [
        {_YOKE_ITEM_REF},  # YOK-prefixed
        {str(_ITEM_NUM)},  # bare-numeric string
        {_ITEM_NUM},  # bare-int
        {_YOKE_ITEM_REF, str(_ITEM_NUM)},  # mixed string forms
        {str(_ITEM_NUM), _ITEM_NUM, _YOKE_ITEM_REF},  # all accepted forms
    ],
)
def test_frontier_filter_canonicalizes_both_sides(skip_memory_item_ids):
    """build_frontier_state_from_schedule filters all three skip-id formats."""
    schedule = _schedule_with_two_candidates()

    baseline = build_frontier_state_from_schedule(schedule)
    assert baseline.selected_item == _YOKE_ITEM_REF

    filtered = build_frontier_state_from_schedule(
        schedule, skip_memory_item_ids=skip_memory_item_ids,
    )
    assert _YOKE_ITEM_REF not in filtered.runnable_items
    assert filtered.runnable_items == ["YOK-1786"]
    assert filtered.selected_item == "YOK-1786"


def test_frontier_filter_no_skip_memory_runs_all_candidates():
    """Baseline: no skip-memory means every assignable step survives."""
    schedule = _schedule_with_two_candidates()
    filtered = build_frontier_state_from_schedule(schedule)
    assert filtered.runnable_items == [_YOKE_ITEM_REF, "YOK-1786"]


def test_historical_envelope_row_with_mixed_formats_filters():
    """Historical chain_skip_memory rows with mixed formats still dedup
    correctly. The compatibility contract is the read-side normalization
    at the actual compare site; no DB rewrite is required.
    """
    schedule = _schedule_with_two_candidates()

    # simulates an offer_envelope.chain_skip_memory list assembled
    # from a recorder mix that predates the canonicalization slice.
    historical_entries = [
        {"item_id": str(_ITEM_NUM), "chain_step": 1},  # bare-numeric
        {"item_id": _YOKE_ITEM_REF, "chain_step": 2},  # YOK-prefixed
    ]
    skip_memory_item_ids = {
        str(e.get("item_id")) for e in historical_entries if e.get("item_id")
    }
    filtered = build_frontier_state_from_schedule(
        schedule, skip_memory_item_ids=skip_memory_item_ids,
    )
    assert _YOKE_ITEM_REF not in filtered.runnable_items


@pytest.mark.parametrize(
    "raw_item_id",
    [_YOKE_ITEM_REF, str(_ITEM_NUM), _ITEM_NUM],
)
def test_summarise_skip_memory_canonicalizes_item_id(raw_item_id):
    """The SessionOfferInvariantFailed summary renders canonical
    bare-numeric item ids regardless of input shape, so post-mortem
    queries don't have to dual-decode every entry.
    """
    skip_memory: Iterable[dict] = [
        {"item_id": raw_item_id, "reason": "recoverable_substrate", "chain_step": 1},
    ]
    summary = _summarise_skip_memory(skip_memory)
    assert summary == [
        {
            "item_id": str(_ITEM_NUM),
            "reason": "recoverable_substrate",
            "chain_step": 1,
        }
    ]


def test_summarise_skip_memory_passes_through_missing_item_id():
    """Non-item entries (no item_id) shouldn't crash the normalizer."""
    skip_memory = [{"reason": "operator-skip", "chain_step": 1}]
    summary = _summarise_skip_memory(skip_memory)
    assert summary == [{"item_id": None, "reason": "operator-skip", "chain_step": 1}]


def test_invariant_helpers_are_item_id_comparison_free():
    """The offer helpers in
    ``runtime/api/service_client_sessions_offer_helpers.py`` consume the
    skip memory only for ``chain_step`` book-keeping (the
    ``no_work_wait`` shape) and for opaque pass-through into
    ``build_no_work_wait_context``. They never compare ``entry.item_id``
    against a scheduler candidate. Pin that contract here so a future
    refactor that adds a candidate-filter branch fails this test until it
    also adds the matching normalization.
    """
    import inspect

    from yoke_core.api import service_client_sessions_offer_helpers as helpers

    source = inspect.getsource(helpers)
    # If a future change adds a candidate-filter shape, normalize at the
    # site and update this assertion to allow the canonical normalizer
    # call. The intent is to flag accidental drift, not freeze the file.
    assert ".item_id) not in" not in source
    assert "candidate.item_id" not in source
