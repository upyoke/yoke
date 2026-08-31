"""The two write rules that keep a request out of the served columns."""

from __future__ import annotations

from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.domain.session_model_columns import (
    MODEL_COLUMNS,
    changed_columns,
    facts_values,
    merged_facts,
    stored_facts,
)


def _row(**values) -> dict:
    return {column: values.get(column) for column in MODEL_COLUMNS}


def test_an_attestation_replaces_a_stored_served_value() -> None:
    """A session that switched model mid-run is serving the later one."""
    stored = _row(model="claude-sonnet-5", requested_model="claude-opus-5[1m]")

    merged = merged_facts(stored, SessionModelFacts(model="claude-opus-5"))

    assert merged.model == "claude-opus-5"


def test_having_nothing_to_attest_never_clears_a_proven_served_value() -> None:
    stored = _row(model="claude-opus-5", reasoning_effort="high")

    merged = merged_facts(stored, SessionModelFacts(requested_model="opus"))

    assert merged.model == "claude-opus-5"
    assert merged.reasoning_effort == "high"


def test_the_request_is_stamped_once_and_not_rewritten() -> None:
    """The ask was fixed at launch; a later reading fills a gap only."""
    stored = _row(requested_model="claude-opus-5[1m]")

    merged = merged_facts(stored, SessionModelFacts(requested_model="haiku"))

    assert merged.requested_model == "claude-opus-5[1m]"


def test_a_missing_request_is_filled_by_a_later_reading() -> None:
    merged = merged_facts(_row(), SessionModelFacts(requested_model="opus"))

    assert merged.requested_model == "opus"


def test_a_settled_row_reports_no_changed_columns() -> None:
    """Nothing new to say means no write, which is what stops re-registering."""
    stored = _row(model="claude-opus-5", requested_model="claude-opus-5[1m]")

    columns, values = changed_columns(
        stored,
        SessionModelFacts(model="claude-opus-5", requested_model="claude-opus-5[1m]"),
    )

    assert columns == []
    assert values == []


def test_changed_columns_names_only_what_actually_moves() -> None:
    stored = _row(requested_model="claude-opus-5[1m]")

    columns, values = changed_columns(
        stored,
        SessionModelFacts(model="claude-opus-5", reasoning_effort="high"),
    )

    assert dict(zip(columns, values)) == {
        "model": "claude-opus-5",
        "reasoning_effort": "high",
    }


def test_a_less_specific_name_does_not_replace_a_measurement() -> None:
    """A composed variant contains the family id it belongs to.

    A name the stored one already contains is the same model reported less
    precisely — an older client's payload self-report, not a later reading.
    """
    stored = _row(model="cursor-grok-4.6-xhigh")

    merged = merged_facts(stored, SessionModelFacts(model="grok-4.6"))

    assert merged.model == "cursor-grok-4.6-xhigh"


def test_an_unrelated_later_name_still_wins() -> None:
    """Two real names are both measurements; a mid-run switch heals."""
    stored = _row(model="cursor-grok-4.6-xhigh")

    merged = merged_facts(stored, SessionModelFacts(model="claude-opus-5"))

    assert merged.model == "claude-opus-5"


def test_stored_facts_reads_an_empty_string_as_unset() -> None:
    assert stored_facts(_row(model="")).model is None


def test_facts_values_follows_the_declared_column_order() -> None:
    facts = SessionModelFacts(model="m", requested_model="r")

    assert facts_values(facts) == [
        facts.model,
        facts.reasoning_effort,
        facts.context_window_tokens,
        facts.requested_model,
        facts.requested_reasoning_effort,
        facts.requested_context_window_tokens,
    ]
