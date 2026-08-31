"""The shared vocabulary for a session's requested and served model facts."""

from __future__ import annotations

from yoke_contracts.session_model_facts import (
    CLAUDE_CONTEXT_TIER_TOKENS,
    MODEL_FACT_FIELDS,
    REQUESTED_LABEL,
    SessionModelFacts,
    effort_suffix_of,
    fact_flag,
    facts_arguments,
    facts_from_mapping,
    model_display,
    normalize_context_window_tokens,
    normalize_reasoning_effort,
    requested_context_window_of,
)


def test_a_recognized_effort_level_is_kept_and_folded() -> None:
    assert normalize_reasoning_effort("XHigh") == "xhigh"


def test_an_effort_no_harness_names_is_dropped_rather_than_stored() -> None:
    assert normalize_reasoning_effort("turbo") is None


def test_a_context_window_must_be_a_positive_count() -> None:
    assert normalize_context_window_tokens("258400") == 258400
    assert normalize_context_window_tokens(0) is None
    assert normalize_context_window_tokens(True) is None
    assert normalize_context_window_tokens("lots") is None


def test_a_flat_variant_name_reports_its_own_effort() -> None:
    assert effort_suffix_of("cursor-grok-4.6-xhigh") == "xhigh"


def test_the_longest_effort_suffix_wins_over_a_shorter_tail() -> None:
    assert effort_suffix_of("cursor-model-extra-high") == "extra-high"


def test_a_name_ending_in_nothing_recognized_reports_no_effort() -> None:
    assert effort_suffix_of("claude-opus-5") is None


def test_the_claude_tier_selector_is_a_context_window_request() -> None:
    assert requested_context_window_of("claude-opus-5[1m]") == (
        CLAUDE_CONTEXT_TIER_TOKENS
    )
    assert requested_context_window_of("claude-opus-5") is None


def test_a_served_model_displays_as_itself() -> None:
    facts = SessionModelFacts(model="claude-opus-5", requested_model="opus[1m]")

    assert model_display(facts) == "claude-opus-5"


def test_an_unattested_session_shows_its_request_labelled_as_one() -> None:
    facts = SessionModelFacts(requested_model="claude-opus-5[1m]")

    assert model_display(facts) == f"claude-opus-5[1m]{REQUESTED_LABEL}"


def test_a_session_with_neither_fact_reads_as_unknown() -> None:
    assert model_display(SessionModelFacts()) == "unknown"


def test_only_stated_facts_ship_as_flags() -> None:
    """An empty string on the wire is indistinguishable from unattested."""
    arguments = facts_arguments(
        SessionModelFacts(model="claude-opus-5", requested_context_window_tokens=1000)
    )

    assert arguments == [
        "--model",
        "claude-opus-5",
        "--requested-context-window-tokens",
        "1000",
    ]


def test_every_fact_has_a_flag_named_for_its_column() -> None:
    for field in MODEL_FACT_FIELDS:
        assert fact_flag(field) == "--" + field.replace("_", "-")


def test_facts_read_back_out_of_a_wire_mapping() -> None:
    facts = facts_from_mapping(
        {
            "model": " claude-opus-5 ",
            "reasoning_effort": "high",
            "context_window_tokens": "258400",
            "requested_model": "claude-opus-5[1m]",
        }
    )

    assert facts.model == "claude-opus-5"
    assert facts.reasoning_effort == "high"
    assert facts.context_window_tokens == 258400
    assert facts.requested_model == "claude-opus-5[1m]"
    assert facts.requested_reasoning_effort is None


def test_a_mapping_with_no_model_keys_attests_nothing() -> None:
    facts = facts_from_mapping({"session_id": "s1"})

    assert not facts.attested()
    assert facts.requested_model is None
