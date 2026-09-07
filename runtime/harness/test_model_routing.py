"""Steering's launch model routing rule: pools, exhaustion, and preference."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.model_billing_pools import (
    MODEL_UNNAMED,
    NO_POOL_WINDOW,
    POOL_HAS_HEADROOM,
    POOL_UNREADABLE,
    pool_exhaustion,
    pool_for_model,
    window_covers_model,
)
from yoke_contracts.session_control.model_routing import (
    EFFORT_SUBSTITUTES,
    EXCLUDED,
    MODEL_RANKS,
    ROUTING_TIERS,
    TIER1,
    TIER2,
    WORK_KINDS,
    fallback_justified,
    model_excluded,
    normalize_session_model_routing,
    preferred_model_for_tier,
    replacement_for,
    resolved_effort,
    routed_selection,
    routing_preference,
    supported_reasoning_efforts,
)

CURSOR = "cursor-cli"
CLAUDE = "claude-cli"
CODEX = "codex-cli"
GROK = "cursor-grok-4.6-high"
OPUS = "claude-opus-5"

# Both included pools readable, with the pool Grok does NOT bill to running low.
SPLIT_POOLS = (
    {"scope": "Cursor Models", "status": "ok", "remaining_percent": 62.0},
    {"scope": "Other Models", "status": "ok", "remaining_percent": 3.0},
)
GROK_POOL_EMPTY = (
    {"scope": "Cursor Models", "status": "ok", "remaining_percent": 0.0},
    {"scope": "Other Models", "status": "ok", "remaining_percent": 90.0},
)
GROK_POOL_UNREADABLE = (
    {"scope": "Cursor Models", "status": "unknown", "remaining_percent": None},
    {"scope": "Other Models", "status": "ok", "remaining_percent": 0.0},
)
ROUTING_CONFIG = {
    "session_model_routing": {
        CURSOR: {
            "tier1": GROK,
            "tier2": "cursor-grok-4.6",
            "excluded": ["cursor-auto"],
            "fallbacks": [OPUS],
        },
        CLAUDE: {"tier1": OPUS, "tier2": "claude-sonnet-5", "worker_tier": TIER2},
        CODEX: {"tier1": "gpt-6-astra", "tier2": "gpt-5.6-sol", "worker_tier": TIER2},
    }
}


def test_tier_vocabulary_matches_the_ranks_the_reference_may_propose():
    assert ROUTING_TIERS == (TIER1, TIER2)
    assert MODEL_RANKS == (TIER1, TIER2, EXCLUDED)


@pytest.mark.parametrize(
    "model,expected",
    [
        (GROK, "Cursor Models"),
        ("cursor-grok-4.6", "Cursor Models"),
        ("composer-1", "Cursor Models"),
        (OPUS, "Other Models"),
        ("gpt-6-astra", "Other Models"),
    ],
)
def test_cursor_bills_by_model_family_prefix(model, expected):
    assert pool_for_model(CURSOR, model) == expected


def test_surfaces_without_split_pools_report_no_derivable_pool():
    assert pool_for_model("claude-cli", OPUS) is None
    assert pool_for_model(CURSOR, "") is None


def test_a_pooled_window_only_covers_its_own_pool():
    assert window_covers_model(CURSOR, GROK, "Cursor Models") is True
    assert window_covers_model(CURSOR, GROK, "Other Models") is False
    assert window_covers_model(CURSOR, OPUS, "Other Models") is True


def test_an_account_wide_window_covers_every_named_model():
    assert window_covers_model("claude-cli", OPUS, "all") is True
    assert window_covers_model("claude-cli", None, "all") is False


def test_a_family_scoped_window_covers_the_model_carrying_that_family():
    assert window_covers_model(
        "codex-cli", "gpt-5.3-codex-spark", "GPT-5.3-Codex-Spark"
    )
    assert not window_covers_model("codex-cli", "gpt-6-astra", "GPT-5.3-Codex-Spark")


def test_exhaustion_reads_the_requested_model_pool_not_the_lowest_meter():
    """A Grok launch must not be answered with the Other Models pool."""
    reading = pool_exhaustion(CURSOR, GROK, SPLIT_POOLS)
    assert reading.pool == "Cursor Models"
    assert reading.remaining_percent == 62.0
    assert reading.exhausted is False
    assert reading.reason == POOL_HAS_HEADROOM


def test_the_other_pool_is_still_read_for_a_model_that_bills_to_it():
    reading = pool_exhaustion(CURSOR, OPUS, SPLIT_POOLS)
    assert reading.pool == "Other Models"
    assert reading.remaining_percent == 3.0
    assert reading.exhausted is False


def test_only_an_affirmative_pool_matched_zero_is_exhaustion():
    reading = pool_exhaustion(CURSOR, GROK, GROK_POOL_EMPTY)
    assert reading.pool == "Cursor Models"
    assert reading.exhausted is True
    assert reading.reason is None


def test_an_unreadable_pool_is_never_exhaustion_even_beside_an_empty_one():
    reading = pool_exhaustion(CURSOR, GROK, GROK_POOL_UNREADABLE)
    assert reading.exhausted is False
    assert reading.reason == POOL_UNREADABLE


def test_a_pool_no_meter_covers_is_unknown_rather_than_empty():
    reading = pool_exhaustion(
        CURSOR,
        GROK,
        ({"scope": "Other Models", "status": "ok", "remaining_percent": 0.0},),
    )
    assert reading.exhausted is False
    assert reading.reason == NO_POOL_WINDOW


def test_no_model_named_leaves_nothing_to_match():
    reading = pool_exhaustion(CURSOR, None, SPLIT_POOLS)
    assert reading.pool is None
    assert reading.reason == MODEL_UNNAMED


def test_a_model_scoped_meter_outranks_the_account_wide_one_beside_it():
    windows = (
        {"scope": "all", "status": "ok", "remaining_percent": 80.0},
        {"scope": "Fable", "status": "ok", "remaining_percent": 0.0},
    )
    reading = pool_exhaustion("claude-cli", "claude-fable-5", windows)
    assert reading.pool == "Fable"
    assert reading.exhausted is True


def test_preference_names_a_model_per_tier_and_reads_blank_when_unset():
    assert preferred_model_for_tier(ROUTING_CONFIG, CURSOR, TIER1) == GROK
    assert preferred_model_for_tier(ROUTING_CONFIG, CURSOR, TIER2) == "cursor-grok-4.6"
    assert preferred_model_for_tier(ROUTING_CONFIG, "claude-other", TIER1) is None
    assert preferred_model_for_tier({}, CURSOR, TIER1) is None
    assert preferred_model_for_tier(ROUTING_CONFIG, CURSOR, "tier3") is None


def test_an_unconfigured_surface_answers_with_a_complete_blank():
    assert routing_preference(None, CURSOR) == {
        "tier1": None,
        "tier2": None,
        "worker_tier": None,
        "excluded": (),
        "fallbacks": (),
    }


def test_exclusion_is_case_insensitive_and_ignores_the_unnamed():
    assert model_excluded(ROUTING_CONFIG, CURSOR, "Cursor-Auto") is True
    assert model_excluded(ROUTING_CONFIG, CURSOR, GROK) is False
    assert model_excluded(ROUTING_CONFIG, CURSOR, None) is False


def test_normalizing_drops_surfaces_that_configure_nothing():
    payload = {
        "session_model_routing": {
            CURSOR: {"tier1": GROK},
            CODEX: {"worker_tier": TIER2},
            "claude-other": {},
        }
    }
    assert normalize_session_model_routing(payload) == {
        CURSOR: {"tier1": GROK},
        CODEX: {"worker_tier": TIER2},
    }
    assert normalize_session_model_routing({}) == {}


def test_headroom_in_the_preferred_pool_refuses_the_fallback():
    allowed, reason = fallback_justified(
        ROUTING_CONFIG, CURSOR, GROK, OPUS, SPLIT_POOLS
    )
    assert allowed is False
    assert POOL_HAS_HEADROOM in reason


def test_confirmed_exhaustion_justifies_the_configured_fallback():
    allowed, reason = fallback_justified(
        ROUTING_CONFIG, CURSOR, GROK, OPUS, GROK_POOL_EMPTY
    )
    assert allowed is True
    assert "Cursor Models" in reason and OPUS in reason


def test_an_unconfigured_fallback_is_never_reached_however_empty_the_pool():
    allowed, reason = fallback_justified(
        ROUTING_CONFIG, CURSOR, GROK, "gpt-6-astra", GROK_POOL_EMPTY
    )
    assert allowed is False
    assert "not a configured fallback" in reason


def test_an_excluded_model_is_refused_as_a_fallback():
    payload = {
        "session_model_routing": {
            CURSOR: {"fallbacks": ["cursor-auto"], "excluded": ["cursor-auto"]}
        }
    }
    allowed, reason = fallback_justified(
        payload, CURSOR, GROK, "cursor-auto", GROK_POOL_EMPTY
    )
    assert allowed is False
    assert "excluded by operator preference" in reason


def test_an_unreadable_meter_is_not_permission_to_start_spending():
    allowed, reason = fallback_justified(
        ROUTING_CONFIG, CURSOR, GROK, OPUS, GROK_POOL_UNREADABLE
    )
    assert allowed is False
    assert POOL_UNREADABLE in reason


def test_replacement_comes_from_vendor_metadata_not_a_version_number():
    assert replacement_for({"model": "gpt-5.5", "replaced_by": "gpt-6-astra"})
    assert replacement_for({"model": "gpt-5.5", "replaced_by": None}) is None
    assert replacement_for({"model": "gpt-5.5"}) is None
    assert replacement_for(None) is None


def test_reasoning_efforts_come_from_the_model_not_the_surface():
    entry = {"model": GROK, "reasoning_efforts": ["low", "high", " "]}
    assert supported_reasoning_efforts(entry) == ("low", "high")
    assert supported_reasoning_efforts({"model": GROK}) == ()
    assert supported_reasoning_efforts({"reasoning_efforts": "high"}) == ()


def test_the_three_work_kinds_are_the_whole_routing_table():
    assert WORK_KINDS == {
        "simple": (TIER2, "medium"),
        "normal": (TIER1, "high"),
        "difficult": (TIER1, "xhigh"),
    }
    assert "max" not in {effort for _tier, effort in WORK_KINDS.values()}


def test_routine_work_takes_the_cheaper_tier_at_a_middling_level():
    model, effort = routed_selection(ROUTING_CONFIG, CURSOR, "simple")
    assert (model, effort) == ("cursor-grok-4.6", "medium")


def test_cursor_ordinary_development_keeps_its_tier1_model():
    model, effort = routed_selection(ROUTING_CONFIG, CURSOR, "normal")
    assert (model, effort) == (GROK, "high")


def test_difficult_work_asks_for_the_higher_level_on_the_same_tier():
    model, effort = routed_selection(ROUTING_CONFIG, CURSOR, "difficult")
    assert (model, effort) == (GROK, "xhigh")


@pytest.mark.parametrize(
    "surface,work_kind,model,effort",
    [
        (CLAUDE, "normal", "claude-sonnet-5", "high"),
        (CLAUDE, "difficult", "claude-sonnet-5", "xhigh"),
        (CODEX, "normal", "gpt-5.6-sol", "high"),
        (CODEX, "difficult", "gpt-5.6-sol", "xhigh"),
    ],
)
def test_configured_workers_stay_on_tier2(surface, work_kind, model, effort):
    assert routed_selection(ROUTING_CONFIG, surface, work_kind) == (model, effort)


def test_steering_uses_tier1_despite_the_worker_reservation():
    assert routed_selection(ROUTING_CONFIG, CODEX, "normal", steering=True) == (
        "gpt-6-astra",
        "high",
    )


def test_an_unnamed_work_kind_decides_nothing():
    assert routed_selection(ROUTING_CONFIG, CURSOR, "urgent") == (None, None)


def test_an_unconfigured_surface_leaves_its_existing_default_alone():
    model, effort = routed_selection({}, "claude-cli", "normal")
    assert model is None
    assert effort == "high"


def test_an_excluded_tier_model_is_not_routed_to():
    payload = {"session_model_routing": {CURSOR: {"tier1": GROK, "excluded": [GROK]}}}
    model, _effort = routed_selection(payload, CURSOR, "normal")
    assert model is None


def test_an_unpublished_level_steps_down_to_the_one_named_for_it():
    entry = {"model": GROK, "reasoning_efforts": ["low", "medium", "high"]}
    assert routed_selection(ROUTING_CONFIG, CURSOR, "difficult", entry) == (
        GROK,
        "high",
    )
    assert EFFORT_SUBSTITUTES["xhigh"] == "high"


def test_a_published_level_is_taken_as_asked():
    entry = {"model": GROK, "reasoning_efforts": ["high", "xhigh"]}
    assert resolved_effort("xhigh", entry) == "xhigh"


def test_no_published_levels_leaves_the_asked_for_level_standing():
    assert resolved_effort("xhigh", None) == "xhigh"
    assert resolved_effort("xhigh", {"model": GROK}) == "xhigh"


def test_a_level_with_no_named_substitute_is_never_silently_lowered():
    entry = {"model": GROK, "reasoning_efforts": ["low"]}
    assert resolved_effort("medium", entry) == "medium"
