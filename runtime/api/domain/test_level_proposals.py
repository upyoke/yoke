"""Level proposals: extrapolation from the catalog, change application, checks."""

from __future__ import annotations

from dataclasses import replace

import pytest

from yoke_contracts.level_proposals import (
    apply_level_changes,
    generate_level_changes,
    published_capability_conflicts,
    refuse_capability_conflicts,
    unplaced_models,
)
from yoke_contracts.levels import LevelsError, default_levels, levels_payload
from yoke_contracts.model_reference_data import MODEL_RECORDS
from yoke_contracts.model_reference_records import ModelRecord


def _records(**overrides) -> list[ModelRecord]:
    """The bundled catalog with per-model field overrides and extra records."""
    extra = overrides.pop("extra", ())
    records = [
        replace(record, **overrides.get(record.model_id, {}))
        for record in MODEL_RECORDS
    ]
    return records + list(extra)


def _options(levels, name):
    level = next(level for level in levels_payload(levels) if level["name"] == name)
    return [(o["surface"], o["model"], o["reasoning_effort"]) for o in level["options"]]


def _record(model_id: str, **fields) -> ModelRecord:
    return ModelRecord(model_id=model_id, provider="test", **fields)


def test_unchanged_catalog_proposes_nothing() -> None:
    assert generate_level_changes(default_levels(), MODEL_RECORDS) == []


def test_superseded_model_is_replaced_in_place_by_its_successor() -> None:
    records = _records(
        **{"cursor-grok-4.7": {"replacement_model_id": "cursor-grok-4.8"}},
        extra=[_record("cursor-grok-4.8", aliases=("grok-4.8",))],
    )
    levels = default_levels()
    changes = generate_level_changes(levels, records)

    assert [change["kind"] for change in changes] == ["retire", "add"]
    added = changes[1]
    assert added["level"] == "JUNIOR"
    assert added["position"] == 0
    assert added["option"]["model"] == "grok-4.8-high"
    assert added["option"]["fallback"]["model"] == "claude-opus-5-5-medium"
    assert "superseded by cursor-grok-4.8" in added["reason"]
    proposed = apply_level_changes(levels, changes)
    assert _options(proposed, "JUNIOR")[0] == ("cursor-cli", "grok-4.8-high", "high")
    assert {r["model_id"] for r in unplaced_models(proposed, records)}.isdisjoint(
        {"cursor-grok-4.8", "cursor-grok-4.7"}
    )


def test_successor_effort_moves_to_the_nearest_published_one() -> None:
    records = _records(
        **{"claude-fable-5-1": {"replacement_model_id": "claude-fable-6"}},
        extra=[_record("claude-fable-6", reasoning_efforts=("low", "high", "max"))],
    )
    changes = generate_level_changes(default_levels(), records)
    added = next(change for change in changes if change["kind"] == "add")
    assert added["option"] == {
        "surface": "claude-cli",
        "model": "claude-fable-6",
        "reasoning_effort": "high",
        "context_window_tokens": 1_000_000,
    }


def test_unpublished_effort_and_window_are_corrected_in_place() -> None:
    records = _records(
        **{
            "claude-opus-5-5": {
                "reasoning_efforts": ("low", "minimal", "high"),
                "context_window_tokens": (200_000,),
            }
        }
    )
    levels = default_levels()
    conflicts, _ = published_capability_conflicts(levels, records)
    assert {c["field"] for c in conflicts} == {
        "reasoning_effort",
        "context_window_tokens",
    }

    changes = generate_level_changes(levels, records)
    change = next(c for c in changes if c["kind"] == "change")
    assert change["option"]["model"] == "claude-opus-5-5"
    assert change["reasoning_effort"] == "low"
    assert change["context_window_tokens"] is None
    fallback = next(c for c in changes if c["kind"] == "add")
    assert fallback["option"]["fallback"]["model"] == "claude-opus-5-5-low"
    proposed = apply_level_changes(levels, changes)
    assert published_capability_conflicts(proposed, records)[0] == []


def test_options_without_published_values_are_unverified_not_refused() -> None:
    conflicts, unverified = published_capability_conflicts(
        default_levels(), MODEL_RECORDS
    )
    assert conflicts == []
    reasons = {(u["model"], u["reason"]) for u in unverified}
    assert ("claude-haiku-5-5", "model not in catalog") in reasons
    assert (
        "claude-opus-5-5",
        "catalog publishes no efforts or context windows",
    ) in reasons


def test_conflicts_refuse_by_name_with_the_recovery() -> None:
    records = _records(**{"gpt-6-astra": {"reasoning_efforts": ("high",)}})
    conflicts, _ = published_capability_conflicts(default_levels(), records)
    with pytest.raises(LevelsError) as raised:
        refuse_capability_conflicts(conflicts)
    assert raised.value.code == "level_option_reasoning_effort_unpublished"
    assert raised.value.field == "PRINCIPAL.reasoning_effort"
    assert "yoke models level-proposal" in str(raised.value)


def test_authored_add_move_retire_and_change_apply_in_order() -> None:
    haiku = {
        "surface": "claude-cli",
        "model": "claude-haiku-5-5",
        "reasoning_effort": "max",
    }
    sol = {"surface": "codex-cli", "model": "gpt-6.1-sol", "reasoning_effort": "medium"}
    proposed = apply_level_changes(
        default_levels(),
        [
            {"kind": "move", "option": sol, "to_level": "JUNIOR"},
            {"kind": "change", "option": haiku, "reasoning_effort": "high"},
            {"kind": "retire", "option": {**sol, "surface": "codex-cli"}},
            {
                "kind": "add",
                "level": "SENIOR",
                "position": 0,
                "option": {**sol, "model": "gpt-6-sol", "context_window_tokens": None},
            },
        ],
    )
    assert _options(proposed, "INTERN")[0] == ("claude-cli", "claude-haiku-5-5", "high")
    assert ("codex-cli", "gpt-6.1-sol", "medium") not in _options(proposed, "JUNIOR")
    assert _options(proposed, "SENIOR")[0] == ("codex-cli", "gpt-6-sol", "medium")


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"kind": "promote"}, "level_change_kind_invalid"),
        (
            {
                "kind": "retire",
                "option": {
                    "surface": "claude-cli",
                    "model": "nope",
                    "reasoning_effort": "high",
                },
            },
            "level_change_option_missing",
        ),
        (
            {"kind": "add", "level": "STAFF", "option": {}},
            "level_change_level_missing",
        ),
        (
            {
                "kind": "add",
                "level": "SENIOR",
                "position": "first",
                "option": {
                    "surface": "codex-cli",
                    "model": "gpt-6-sol",
                    "reasoning_effort": "high",
                },
            },
            "level_change_position_invalid",
        ),
        (
            {
                "kind": "change",
                "option": {
                    "surface": "claude-cli",
                    "model": "claude-haiku-5-5",
                    "reasoning_effort": "max",
                },
                "reasoning_effort": "turbo",
            },
            "claude_reasoning_effort_unsupported",
        ),
    ],
)
def test_invalid_changes_refuse_by_name(change, code) -> None:
    with pytest.raises(LevelsError) as raised:
        apply_level_changes(default_levels(), [change])
    assert raised.value.code == code


def test_retiring_a_levels_last_option_is_refused() -> None:
    intern = levels_payload(default_levels())[0]["options"]
    with pytest.raises(LevelsError) as raised:
        apply_level_changes(
            default_levels(),
            [{"kind": "retire", "option": option} for option in intern],
        )
    assert raised.value.code == "level_options_missing"
