"""Cursor parent-turn token fields fold into existing session usage totals."""

from __future__ import annotations

from yoke_contracts.session_usage_facts import (
    USAGE_COMPLETE,
    USAGE_UNAVAILABLE,
    usage_from_document,
    usage_document,
)
from yoke_contracts.session_usage_sources import (
    CURSOR_INCOMPLETE_TOKEN_FIELDS_REASON,
    CURSOR_NO_TURN_IDENTITY_REASON,
    UNNAMED_MODEL,
    CURSOR_USAGE_SOURCE,
)
from yoke_harness.usage_attestation import attest_session_usage
from runtime.harness.session_usage_test_support import (  # noqa: F401
    cursor_result_payload,
    cursor_stop_payload,
    machine_home,
)


def test_cursor_stop_subtracts_inclusive_cache_fields() -> None:
    usage = attest_session_usage("cursor", cursor_stop_payload())

    assert usage.status == USAGE_COMPLETE
    assert usage.source == CURSOR_USAGE_SOURCE
    entry = usage.models[0]
    assert entry.model == "composer-2"
    assert entry.input == 50
    assert entry.cached_input == 40
    assert entry.cache_write == 10
    assert entry.output == 20
    assert entry.reasoning == 0


def test_cursor_inclusive_remainder_clamps_at_zero() -> None:
    usage = attest_session_usage(
        "cursor",
        cursor_stop_payload(
            input_tokens=10, cache_read_tokens=40, cache_write_tokens=10
        ),
    )

    assert usage.models[0].input == 0
    assert usage.models[0].cached_input == 40
    assert usage.models[0].cache_write == 10


def test_cursor_same_generation_is_not_counted_twice() -> None:
    first = attest_session_usage("cursor", cursor_stop_payload())
    again = attest_session_usage(
        "cursor",
        cursor_stop_payload(event="afterAgentResponse"),
    )

    assert first.models[0].output == 20
    assert again.models[0].output == 20
    assert again.billable_tokens() == first.billable_tokens()


def test_cursor_later_generation_accumulates() -> None:
    attest_session_usage("cursor", cursor_stop_payload(generation_id="gen-1"))
    usage = attest_session_usage(
        "cursor",
        cursor_stop_payload(generation_id="gen-2", output_tokens=5),
    )

    assert usage.models[0].output == 25


def test_cursor_delayed_older_generation_is_not_readded() -> None:
    attest_session_usage("cursor", cursor_stop_payload(generation_id="gen-1"))
    attest_session_usage(
        "cursor",
        cursor_stop_payload(generation_id="gen-2", output_tokens=5),
    )
    usage = attest_session_usage(
        "cursor",
        cursor_stop_payload(generation_id="gen-1", output_tokens=99),
    )

    assert usage.models[0].output == 25


def test_cursor_incomplete_fields_are_not_folded_as_zero() -> None:
    payload = cursor_stop_payload()
    del payload["cache_write_tokens"]

    usage = attest_session_usage("cursor", payload)

    assert usage.status == USAGE_UNAVAILABLE
    assert usage.reason == CURSOR_INCOMPLETE_TOKEN_FIELDS_REASON
    assert usage.models == ()


def test_cursor_tokens_without_turn_id_are_not_folded() -> None:
    payload = cursor_stop_payload()
    del payload["generation_id"]

    usage = attest_session_usage("cursor", payload)

    assert usage.status == USAGE_UNAVAILABLE
    assert usage.reason == CURSOR_NO_TURN_IDENTITY_REASON


def test_cursor_unnamed_model_is_recorded_as_unknown() -> None:
    payload = cursor_stop_payload()
    del payload["model"]

    usage = attest_session_usage("cursor", payload)

    assert usage.models[0].model == UNNAMED_MODEL
    stored = usage_from_document(usage_document(usage))
    assert stored is not None
    assert stored.models[0].model == UNNAMED_MODEL


def test_cursor_print_mode_usage_is_exclusive_of_cache() -> None:
    usage = attest_session_usage("cursor", cursor_result_payload())

    entry = usage.models[0]
    assert entry.input == 6536
    assert entry.cached_input == 7424
    assert entry.cache_write == 0
    assert entry.output == 34
    assert entry.model == UNNAMED_MODEL


def test_cursor_event_without_tokens_keeps_watermarked_totals() -> None:
    attest_session_usage("cursor", cursor_stop_payload())
    usage = attest_session_usage(
        "cursor",
        {
            "hook_event_name": "preToolUse",
            "session_id": "cursor-1",
            "tool_name": "Shell",
        },
    )

    assert usage.status == USAGE_COMPLETE
    assert usage.models[0].output == 20


def test_cursor_unnamed_model_cost_names_the_gap_not_a_free_session() -> None:
    from yoke_contracts.session_usage_cost import COST_UNAVAILABLE
    from yoke_contracts.session_usage_pricing import estimated_session_cost

    usage = attest_session_usage("cursor", cursor_result_payload())
    cost = estimated_session_cost(usage)

    assert usage.status == USAGE_COMPLETE
    assert cost.status == COST_UNAVAILABLE
    assert cost.reason
    assert cost.usd == 0.0


def test_cursor_subagent_payload_is_not_folded() -> None:
    attest_session_usage("cursor", cursor_stop_payload())
    payload = cursor_stop_payload(generation_id="sub-1", output_tokens=80)
    payload["is_subagent_session"] = True

    usage = attest_session_usage("cursor", payload)

    assert usage.models[0].output == 20
