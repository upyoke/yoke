"""Typed item-id dedup regressions for chain skip memory."""

from __future__ import annotations

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
_OTHER_ITEM_NUM = 1786


def _title(item_id: int) -> str:
    """The step title, which carries the item identity as data."""
    return f"{item_id} title"


def _make_step(item_id: int, rank: int) -> ScheduledStep:
    return ScheduledStep(
        item_id=item_id,
        workflow_id="issue",
        workflow_version_id=1,
        workflow_version=1,
        status="refined-idea",
        title=_title(item_id),
        priority="medium",
        next_step=NextStep.ADVANCE,
        rank=rank,
        claim_state=ClaimState.UNCLAIMED,
    )


def _schedule_with_two_candidates() -> SchedulerResult:
    steps = [
        _make_step(_ITEM_NUM, rank=0),
        _make_step(_OTHER_ITEM_NUM, rank=1),
    ]
    return SchedulerResult(
        project_scope=["yoke"],
        sml_state=SMLState(coherent=True),
        ranked_steps=steps,
        selected_step=steps[0],
    )


def test_frontier_filter_uses_typed_internal_skip_ids():
    """The frontier filter removes the typed internal item id."""
    schedule = _schedule_with_two_candidates()

    baseline = build_frontier_state_from_schedule(schedule)
    # These fields are presentation-facing references. A conn-less build has
    # no identity read to make one from, so it says so and shows no number:
    # the storage key is not a reference and reads as one to whoever sees it.
    assert "no control-plane read" in baseline.selected_item
    assert str(_ITEM_NUM) not in baseline.selected_item

    filtered = build_frontier_state_from_schedule(
        schedule, skip_memory_item_ids={_ITEM_NUM},
    )
    assert len(filtered.runnable_items) == 1
    assert filtered.selected_item == filtered.runnable_items[0]
    # Which step survived is read from the typed schedule data the context
    # carries, because two unresolvable refs render the same phrase.
    assert filtered.scheduler_context["title"] == _title(_OTHER_ITEM_NUM)


def test_frontier_filter_no_skip_memory_runs_all_candidates():
    """Baseline: no skip-memory means every assignable step survives."""
    schedule = _schedule_with_two_candidates()
    filtered = build_frontier_state_from_schedule(schedule)
    assert len(filtered.runnable_items) == 2
    assert filtered.scheduler_context["title"] == _title(_ITEM_NUM)
    for rendered in filtered.runnable_items:
        assert str(_ITEM_NUM) not in rendered
        assert str(_OTHER_ITEM_NUM) not in rendered


def test_summarise_skip_memory_preserves_typed_item_id():
    """Invariant telemetry keeps the internal item id numeric."""
    skip_memory = [
        {"item_id": _ITEM_NUM, "reason": "recoverable_substrate", "chain_step": 1},
    ]
    summary = _summarise_skip_memory(skip_memory)
    assert summary == [
        {
            "item_id": _ITEM_NUM,
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
