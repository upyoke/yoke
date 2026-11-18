"""Level rows map only onto each surface's actual observed selectors."""

from yoke_contracts.levels import LevelEntry
from yoke_core.domain.level_native_selections import native_selections
from runtime.api.fixtures.model_catalog import RECORDS


def test_cursor_expands_both_observed_speed_variants():
    reading = {
        "status": "ok",
        "models": [
            {"model": "grok-4.7-high", "reasoning_efforts": ["high"]},
            {"model": "grok-4.7-high-fast", "reasoning_efforts": ["high"]},
            {"model": "grok-4.7-low", "reasoning_efforts": ["low"]},
        ],
    }
    selections, reason = native_selections(
        LevelEntry("grok-4.7", "high"),
        surface="cursor-cli",
        reading=reading,
        records=RECORDS,
    )
    assert reason is None
    assert [selection.model for selection in selections] == [
        "grok-4.7-high",
        "grok-4.7-high-fast",
    ]
    assert all(selection.reasoning_effort == "high" for selection in selections)


def test_codex_uses_model_token_and_effort_flag():
    selections, reason = native_selections(
        LevelEntry("gpt-6.1-sol", "medium"),
        surface="codex-cli",
        reading={
            "status": "ok",
            "models": [
                {"model": "gpt-6.1-sol", "reasoning_efforts": ["low", "medium", "high"]}
            ],
        },
        records=RECORDS,
    )
    assert reason is None
    assert (selections[0].model, selections[0].reasoning_effort) == (
        "gpt-6.1-sol",
        "medium",
    )


def test_claude_uses_declared_catalog_without_native_listing():
    selections, reason = native_selections(
        LevelEntry("claude-opus-5-5", "medium"),
        surface="claude-cli",
        reading={"status": "unsupported", "reason": "no native listing adapter"},
        records=RECORDS,
    )
    assert reason is None
    assert [
        (selection.model, selection.reasoning_effort) for selection in selections
    ] == [("claude-opus-5-5", "medium")]


def test_available_model_at_wrong_effort_is_not_invented():
    selections, reason = native_selections(
        LevelEntry("grok-4.7", "high"),
        surface="cursor-cli",
        reading={
            "status": "ok",
            "models": [{"model": "grok-4.7-medium", "reasoning_efforts": ["medium"]}],
        },
        records=RECORDS,
    )
    assert selections == ()
    assert "native_model_effort_unavailable" in reason


def test_stale_listing_keeps_real_last_observed_choice():
    selections, reason = native_selections(
        LevelEntry("gpt-6.1-sol", "medium"),
        surface="codex-cli",
        reading={
            "status": "stale",
            "models": [{"model": "gpt-6.1-sol", "reasoning_efforts": ["medium"]}],
        },
        records=RECORDS,
    )
    assert reason is None and len(selections) == 1


def test_model_missing_from_the_cli_listing_names_the_cli_update():
    selections, reason = native_selections(
        LevelEntry("gpt-6.2-sol", "medium"),
        surface="codex-cli",
        reading={
            "status": "ok",
            "machine": "workshop-mac",
            "surface_version": "0.161.0",
            "models": [{"model": "gpt-6.1-sol", "reasoning_efforts": ["medium"]}],
        },
        records=RECORDS,
    )
    assert selections == ()
    assert reason == (
        "native_model_not_offered: codex-cli 0.161.0 on workshop-mac does not "
        "list gpt-6.2-sol; run `codex update` there, then "
        "`yoke relay probe-models --surface codex-cli`"
    )
