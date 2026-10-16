"""Capacity expands model thresholds across observed native listings and quotas."""

from yoke_contracts.levels import parse_levels
from yoke_core.domain.universe_level_capacity import (
    Meter,
    evaluate_level_capacity,
    pool_label,
)
from runtime.api.fixtures.model_catalog import RECORDS

MACHINE = "machine-1"
LEVELS = parse_levels(
    [
        {
            "name": "SENIOR",
            "glyph": "🦉",
            "options": [
                {"model": "claude-opus-5-5", "min_effort": "medium"},
                {"model": "grok-4.7", "min_effort": "high"},
            ],
        }
    ]
)
NATIVE = {
    MACHINE: {
        "claude-cli": {
            "status": "ok",
            "models": [{"model": "claude-opus-5-5", "reasoning_efforts": ["medium"]}],
        },
        "cursor-cli": {
            "status": "ok",
            "models": [
                {"model": "claude-opus-5-5-medium", "reasoning_efforts": ["medium"]},
                {"model": "grok-4.7-high-fast", "reasoning_efforts": ["high"]},
            ],
        },
    }
}


def meter(surface, scope, left):
    return Meter(
        MACHINE,
        surface,
        "monthly" if surface == "cursor-cli" else "rolling_7d",
        scope,
        "ok",
        left,
        left * 2,
        # Paid extra usage switched off: an empty pool really blocks.
        extra_blocks=True,
        extra="extra usage disabled (user_disabled)",
    )


def evaluate(meters=(), offered=None, native=NATIVE):
    return evaluate_level_capacity(
        LEVELS,
        meters=meters,
        offered=offered
        if offered is not None
        else [(MACHINE, "claude-cli"), (MACHINE, "cursor-cli")],
        display=lambda model: {"claude-opus-5-5": "Claude Opus 5.5"}.get(model, model),
        native_models=native,
        records=RECORDS,
    )[0]


def test_rows_expand_to_all_observed_surfaces_and_only_current_fields():
    result = evaluate()
    assert result["launchable_surfaces"] == ["claude-cli", "cursor-cli"]
    opus = result["options"][0]
    assert opus["display_name"] == "Claude Opus 5.5"
    assert opus["now"]["surfaces"] == ["claude-cli", "cursor-cli"]
    assert set(opus) == {"model", "min_effort", "display_name", "now"}
    assert "next_launches" not in result


def test_exhausted_cursor_pool_does_not_block_another_surface_or_pool():
    result = evaluate(
        [
            meter("cursor-cli", "Other Models", 0),
            meter("cursor-cli", "Cursor Models", 40),
        ]
    )
    assert result["options"][0]["now"]["surfaces"] == ["claude-cli"]
    assert result["options"][1]["now"]["surfaces"] == ["cursor-cli"]


def test_claude_separate_cap_blocks_an_otherwise_open_model():
    result = evaluate(
        [meter("claude-cli", "all", 80), meter("claude-cli", "Opus", 0)],
        offered=[(MACHINE, "claude-cli")],
    )
    now = result["options"][0]["now"]
    assert now["state"] == "blocked"
    assert any(
        blocker["label"] == "Claude weekly · Opus" for blocker in now["blockers"]
    )


def test_unobserved_native_models_are_blocked_with_recovery():
    result = evaluate(native={}, offered=[(MACHINE, "cursor-cli")])
    assert result["launchable_surfaces"] == []
    assert (
        "native_models_unknown" in result["options"][0]["now"]["blockers"][0]["label"]
    )


def test_claude_catalog_capacity_does_not_require_a_native_listing():
    result = evaluate(native={})
    assert result["launchable_surfaces"] == ["claude-cli"]
    assert result["options"][0]["now"]["surfaces"] == ["claude-cli"]
    assert result["options"][1]["now"]["state"] == "blocked"


def test_no_machine_and_unknown_meters_remain_distinct():
    assert (
        evaluate(offered=[])["options"][0]["now"]["blockers"][0]["kind"] == "no_machine"
    )
    assert evaluate()["options"][0]["now"]["state"] == "can_launch"


def test_vendor_pool_labels_preserve_separate_caps():
    assert (
        pool_label("claude-cli", "rolling_7d", "Fable", scoped=True)
        == "Claude weekly · Fable"
    )
    assert (
        pool_label("cursor-cli", "monthly", "Cursor Models", scoped=True)
        == "Cursor Models"
    )
    assert (
        pool_label("cursor-cli", "monthly", "Other Models", scoped=True)
        == "Cursor Other Models"
    )
