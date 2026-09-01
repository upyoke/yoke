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
    requested_facts_of,
    served_model_or_none,
)

CLAUDE = "claude-code"
CODEX = "codex"
CURSOR = "cursor"


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


def test_a_tier_selector_on_the_wire_is_never_read_as_served() -> None:
    """A client older than this split ships its ask under the plain key."""
    facts = facts_from_mapping(
        {"model": "claude-opus-5[1m]", "requested_model": "claude-opus-5[1m]"}
    )

    assert facts.model is None
    # The same string is a perfectly good request.
    assert facts.requested_model == "claude-opus-5[1m]"


def test_a_placeholder_on_the_wire_is_never_read_as_served() -> None:
    for placeholder in ("unknown", "default", "auto", "<synthetic>", "  "):
        assert facts_from_mapping({"model": placeholder}).model is None


def test_served_model_or_none_keeps_a_real_provider_id() -> None:
    assert served_model_or_none(" claude-opus-5 ") == "claude-opus-5"
    assert served_model_or_none(None) is None


def test_a_mapping_with_no_model_keys_attests_nothing() -> None:
    facts = facts_from_mapping({"session_id": "s1"})

    assert not facts.attested()
    assert facts.requested_model is None


def test_a_cursor_variant_name_states_its_model_and_its_effort() -> None:
    facts = requested_facts_of("cursor-grok-4.6-xhigh", harness_id=CURSOR)

    assert facts.requested_model == "cursor-grok-4.6-xhigh"
    assert facts.requested_reasoning_effort == "xhigh"
    assert facts.requested_context_window_tokens is None


def test_a_claude_tier_selector_states_its_requested_window() -> None:
    facts = requested_facts_of("claude-opus-5[1m]", harness_id=CLAUDE)

    assert facts.requested_model == "claude-opus-5[1m]"
    assert facts.requested_context_window_tokens == CLAUDE_CONTEXT_TIER_TOKENS


def test_only_a_name_encoding_harness_reads_an_effort_out_of_the_name() -> None:
    """A Codex family name ending in an effort word is still a model name."""
    assert requested_facts_of("gpt-5.1-codex-max", harness_id=CODEX) == (
        SessionModelFacts(requested_model="gpt-5.1-codex-max")
    )
    assert (
        requested_facts_of(
            "cursor-model-max", harness_id=CURSOR
        ).requested_reasoning_effort
        == "max"
    )


def test_an_unknown_harness_still_states_the_model_it_asked_for() -> None:
    facts = requested_facts_of("gpt-5.6-sol", harness_id="")

    assert facts == SessionModelFacts(requested_model="gpt-5.6-sol")


def test_a_placeholder_selector_states_no_ask_at_all() -> None:
    assert requested_facts_of("default", harness_id=CURSOR) == SessionModelFacts()
    assert requested_facts_of(None, harness_id=CLAUDE) == SessionModelFacts()
