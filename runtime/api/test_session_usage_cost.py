"""Turning recorded tokens into a labelled API-equivalent estimate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from yoke_contracts.session_usage_cost import (
    COST_COMPLETE,
    COST_PARTIAL,
    COST_UNAVAILABLE,
    session_cost,
)
from yoke_contracts.session_usage_display import (
    UNREAD_DISPLAY,
    compact_tokens,
    compact_usd,
    cost_display,
    tokens_display,
    usage_cell,
    usage_title,
)
from yoke_contracts.session_usage_facts import (
    USAGE_COMPLETE,
    USAGE_PARTIAL,
    ModelUsage,
    SessionUsage,
)


@dataclass(frozen=True)
class _Price:
    """The reference's price record, in the shape its reader returns."""

    input_per_million_usd: Optional[float] = 5.0
    output_per_million_usd: Optional[float] = 25.0
    cache_read_per_million_usd: Optional[float] = 0.5
    cache_write_per_million_usd: Optional[float] = 6.25
    cache_write_long_per_million_usd: Optional[float] = 10.0
    conditions: str = "standard tier"
    source_url: str = "https://example.invalid/pricing"
    effective_at: str = "2026-08-15"
    checked_at: str = "2026-09-01"


def _usage(status: str = USAGE_COMPLETE, **buckets: int) -> SessionUsage:
    return SessionUsage(
        status=status,
        source="transcript assistant message.usage",
        models=(ModelUsage(model="claude-opus-5", **buckets),),
    )


def _priced(_model: str) -> _Price:
    return _Price()


def test_each_bucket_is_billed_at_its_own_published_rate() -> None:
    usage = _usage(
        input=1_000_000,
        cached_input=1_000_000,
        cache_write=1_000_000,
        cache_write_long=1_000_000,
        output=1_000_000,
    )

    cost = session_cost(usage, _priced)

    assert cost.status == COST_COMPLETE
    assert cost.usd == 5.0 + 0.5 + 6.25 + 10.0 + 25.0


def test_reasoning_tokens_are_never_billed_on_top_of_output() -> None:
    """Reasoning is already inside the output count that was charged."""
    with_reasoning = _usage(output=1_000_000, reasoning=900_000)
    without = _usage(output=1_000_000)

    assert (
        session_cost(with_reasoning, _priced).usd == session_cost(without, _priced).usd
    )


def test_the_price_basis_and_both_dates_travel_with_the_estimate() -> None:
    """When a rate took effect and when it was last verified differ."""
    cost = session_cost(_usage(input=1_000_000), _priced)

    assert "https://example.invalid/pricing" in cost.price_basis
    assert "standard tier" in cost.price_basis
    assert cost.effective_date == "2026-08-15"
    assert cost.checked_date == "2026-09-01"


def test_a_model_the_reference_does_not_know_is_named_not_zeroed() -> None:
    cost = session_cost(_usage(input=1_000), lambda _model: None)

    assert cost.status == COST_UNAVAILABLE
    assert "claude-opus-5" in cost.reason
    assert cost.usd == 0.0


def test_one_unpriced_bucket_leaves_the_rest_priced_and_says_which() -> None:
    def _partial(_model: str) -> _Price:
        return _Price(cache_read_per_million_usd=None)

    cost = session_cost(_usage(input=1_000_000, cached_input=1_000_000), _partial)

    assert cost.status == COST_PARTIAL
    assert cost.usd == 5.0
    assert "cached_input" in cost.reason


def test_a_reference_without_a_long_lifetime_rate_says_it_substituted() -> None:
    """The two cache-write rates differ, so a substitution is not silent."""

    def _one_write_rate(_model: str) -> _Price:
        return _Price(cache_write_long_per_million_usd=None)

    cost = session_cost(_usage(cache_write_long=1_000_000), _one_write_rate)

    assert cost.status == COST_PARTIAL
    assert cost.usd == 6.25
    assert "ordinary cache-write rate" in cost.reason


def test_a_partial_reading_yields_a_partial_estimate() -> None:
    usage = SessionUsage(
        status=USAGE_PARTIAL,
        reason="earlier history unreadable",
        models=(ModelUsage(model="claude-opus-5", input=1_000_000),),
    )

    cost = session_cost(usage, _priced)

    assert cost.status == COST_PARTIAL
    assert cost.usd == 5.0


def test_a_session_that_switched_models_is_priced_per_model() -> None:
    usage = SessionUsage(
        status=USAGE_COMPLETE,
        models=(
            ModelUsage(model="cheap", input=1_000_000),
            ModelUsage(model="dear", input=1_000_000),
        ),
    )
    rates = {"cheap": _Price(input_per_million_usd=1.0), "dear": _Price()}

    cost = session_cost(usage, rates.get)

    assert cost.usd == 6.0


def test_a_session_with_no_reading_is_unpriced_rather_than_free() -> None:
    cost = session_cost(None, _priced)

    assert cost.status == COST_UNAVAILABLE
    assert not cost.priced()


def test_compact_renderings_stay_readable_at_every_scale() -> None:
    assert compact_tokens(0) == "0"
    assert compact_tokens(999) == "999"
    assert compact_tokens(1_500) == "1.5k"
    assert compact_tokens(23_000) == "23k"
    assert compact_tokens(1_280_000) == "1.3m"
    assert compact_tokens(12_800_000) == "13m"
    assert compact_usd(0.0) == "$0"
    assert compact_usd(0.42) == "$0.42"
    assert compact_usd(3.5) == "$3.5"
    assert compact_usd(1234.0) == "$1,234"


def test_a_partial_figure_is_marked_and_an_unread_one_is_blank() -> None:
    complete = _usage(input=1_000)
    partial = SessionUsage(
        status=USAGE_PARTIAL, models=(ModelUsage(model="m", input=1_000),)
    )

    assert tokens_display(complete) == "1k"
    assert tokens_display(partial) == "1k~"
    assert tokens_display(None) == UNREAD_DISPLAY
    assert cost_display(session_cost(complete, _priced)) == "$0.01"
    assert cost_display(None) == UNREAD_DISPLAY


def test_the_cell_pairs_both_figures_and_collapses_when_neither_is_known() -> None:
    usage = _usage(input=1_000_000)

    assert usage_cell(usage, session_cost(usage, _priced)) == "1m · $5"
    assert usage_cell(None, None) == UNREAD_DISPLAY


def test_the_note_states_the_estimate_is_not_plan_consumption() -> None:
    usage = _usage(input=1_000_000)

    note = usage_title(usage, session_cost(usage, _priced))

    assert "not plan consumption" in note
    assert "effective 2026-08-15" in note
    assert "checked 2026-09-01" in note


def test_the_note_explains_an_absent_estimate_rather_than_going_quiet() -> None:
    usage = _usage(input=1_000)

    note = usage_title(usage, session_cost(usage, lambda _model: None))

    assert "no cost estimate" in note
