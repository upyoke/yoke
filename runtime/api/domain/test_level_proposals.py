"""Catalog-driven model/minimum-effort proposals stay explicit and validated."""

from dataclasses import replace
import pytest
from yoke_contracts.level_proposals import (
    apply_level_changes,
    generate_level_changes,
    published_capability_conflicts,
    refuse_capability_conflicts,
    unplaceable_models,
    unplaced_models,
)
from yoke_contracts.levels import default_levels, levels_payload, LevelsError
from runtime.api.fixtures.model_catalog import RECORDS


def test_unchanged_current_catalog_proposes_no_changes():
    assert generate_level_changes(default_levels(), RECORDS) == []


def test_new_successor_replaces_all_threshold_rows_in_place():
    current = next(
        record for record in RECORDS if record.model_id == "claude-fable-5-1"
    )
    successor = replace(
        current, model_id="claude-fable-6", aliases=(), replacement_model_id=None
    )
    records = [
        replace(record, replacement_model_id=successor.model_id)
        if record is current
        else record
        for record in RECORDS
    ] + [successor]
    proposed = apply_level_changes(
        default_levels(), generate_level_changes(default_levels(), records)
    )
    assert [entry.model for level in proposed for entry in level.options].count(
        "claude-fable-6"
    ) == 3
    assert "claude-fable-5-1" not in [
        entry.model for level in proposed for entry in level.options
    ]


def test_unpublished_threshold_is_named():
    records = [
        replace(record, reasoning_efforts=("low", "high", "max"))
        if record.model_id == "claude-opus-5-5"
        else record
        for record in RECORDS
    ]
    conflicts, _ = published_capability_conflicts(default_levels(), records)
    assert conflicts[0]["field"] == "min_effort"
    with pytest.raises(LevelsError, match="level_min_effort_unpublished"):
        refuse_capability_conflicts(conflicts)


def test_unknown_model_facts_remain_unverified():
    conflicts, unverified = published_capability_conflicts(default_levels(), ())
    assert conflicts == []
    assert len(unverified) == 18


def test_add_move_retire_change_use_model_threshold_selectors():
    levels = default_levels()
    selector = {"model": "gpt-6-luna", "min_effort": "low"}
    changed = apply_level_changes(
        levels, [{"kind": "change", "option": selector, "min_effort": "medium"}]
    )
    assert (
        next(
            entry for entry in changed[0].options if entry.model == "gpt-6-luna"
        ).min_effort
        == "medium"
    )
    moved = apply_level_changes(
        changed,
        [
            {
                "kind": "move",
                "option": {"model": "gpt-6-luna", "min_effort": "medium"},
                "to_level": "JUNIOR",
            }
        ],
    )
    assert moved[1].options[-1].model == "gpt-6-luna"
    retired = apply_level_changes(
        moved,
        [{"kind": "retire", "option": {"model": "gpt-6-luna", "min_effort": "medium"}}],
    )
    added = apply_level_changes(
        retired, [{"kind": "add", "level": "INTERN", "option": selector, "position": 1}]
    )
    assert levels_payload(added) == levels_payload(levels)


def test_invalid_changes_cannot_leave_contradictory_thresholds():
    with pytest.raises(LevelsError, match="level_min_effort_order_invalid"):
        apply_level_changes(
            default_levels(),
            [
                {
                    "kind": "change",
                    "option": {"model": "grok-4.7", "min_effort": "high"},
                    "min_effort": "low",
                }
            ],
        )


def test_unplaced_models_report_unplaced_facts_without_guessing_rows():
    names = {
        record["model_id"] for record in unplaced_models(default_levels(), RECORDS)
    }
    assert "composer-2.5" not in names
    assert "cursor-grok-4.7" not in names


def test_models_publishing_no_efforts_are_listed_as_unplaceable():
    unplaceable = unplaceable_models(default_levels(), RECORDS)
    assert {record["model_id"] for record in unplaceable} == {"composer-2.5"}
    assert {"model_id", "provider", "display_name"} <= set(unplaceable[0])
