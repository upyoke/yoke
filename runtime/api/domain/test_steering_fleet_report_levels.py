"""The steering report's level readout and item level overrides."""

from __future__ import annotations

import json

import pytest

from runtime.api.steering_fleet_test_helpers import (
    compose as _compose,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain.session_launch_level_placement import (
    RULE_SPREAD,
    LevelCandidate,
    LevelPlacement,
)
from yoke_core.domain.session_launch_level_pools import PoolCheck
from yoke_core.domain.steering_fleet_report_levels import (
    LEVELS_HEADING,
    LevelReadout,
    level_override_lines,
    level_readout_lines,
    read_level_overrides,
)
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body


def _pool(**overrides) -> PoolCheck:
    values = dict(
        window="Claude 5h",
        remaining_percent=62.0,
        headroom_percent=140.0,
        resets_at="2026-10-08T17:05:00Z",
        status="ok",
        exhausted=False,
    )
    values.update(overrides)
    return PoolCheck(**values)


def _candidate(**overrides) -> LevelCandidate:
    values = dict(
        option_index=0,
        surface="claude-cli",
        model="claude-opus-5-5",
        reasoning_effort="medium",
        context_window_tokens=1_000_000,
        machine_id="machine-a",
        fallback=False,
        pools=(_pool(),),
    )
    values.update(overrides)
    return LevelCandidate(**values)


def _readout() -> LevelReadout:
    chosen = _candidate(chosen=True)
    blocked = _candidate(
        option_index=1,
        surface="codex-cli",
        model="gpt-6.1-sol",
        pools=(_pool(window="Codex weekly", remaining_percent=0.0, exhausted=True),),
        blocked="Codex weekly pool exhausted (resets 2026-10-09T00:00:00Z)",
    )
    senior = LevelPlacement(
        "SENIOR",
        "universe",
        (chosen, blocked),
        chosen,
        RULE_SPREAD,
        "spread rule: no live worker on claude-cli and headroom 140% above 100%",
    )
    principal = LevelPlacement(
        "PRINCIPAL",
        "universe",
        (
            _candidate(
                model="claude-fable-5-1",
                machine_id=None,
                blocked="no usable machine offers claude-cli",
            ),
        ),
        None,
        None,
        "No PRINCIPAL option has capacity",
    )
    return LevelReadout(
        source="universe",
        live_workers=(("claude-cli", 0), ("codex-cli", 3)),
        levels=(("🦉", senior), ("🦅", principal)),
    )


def test_readout_names_each_option_machine_pool_and_next_launch() -> None:
    lines = level_readout_lines(_readout(), machine_names={"machine-a": "mini"})
    text = "\n".join(lines)

    assert lines[0] == (
        f"{LEVELS_HEADING} (universe) — launch with --level; "
        "live workers: claude-cli 0 · codex-cli 3"
    )
    assert "SENIOR 🦉 next → spread rule: no live worker on claude-cli" in text
    assert (
        "→ claude-cli claude-opus-5-5 medium on mini · Claude 5h 62% left, "
        "headroom 140%, resets Oct 8 17:05"
    ) in text
    assert (
        "✗ codex-cli gpt-6.1-sol medium on mini · Codex weekly pool exhausted"
    ) in text
    assert "PRINCIPAL 🦅 no capacity: a launch at this level refuses" in text
    assert "✗ claude-cli claude-fable-5-1 medium · no usable machine" in text


def test_unreadable_pool_and_no_meter_are_named_not_hidden() -> None:
    unreadable = _candidate(
        pools=(_pool(status="unavailable", remaining_percent=None),)
    )
    bare = _candidate(option_index=1, pools=())
    placement = LevelPlacement("JUNIOR", "universe", (unreadable, bare), None, None, "")
    lines = level_readout_lines(
        LevelReadout("universe", (), (("🐥", placement),)), machine_names={}
    )
    assert "· Claude 5h unreadable" in lines[2]
    assert lines[3].endswith("· no published meter")
    assert "live workers: none" in lines[0]


def test_unavailable_readout_says_why_and_how_to_check() -> None:
    lines = level_readout_lines(
        LevelReadout("universe", (), (), unavailable="no actor"), machine_names={}
    )
    assert lines[1] == "  unavailable: no actor"


def test_no_readout_renders_nothing() -> None:
    assert level_readout_lines(None, machine_names={}) == []


def test_readout_projection_carries_glyph_and_placement() -> None:
    payload = _readout().to_dict()
    assert payload["live_workers"] == {"claude-cli": 0, "codex-cli": 3}
    senior = payload["levels"][0]
    assert senior["glyph"] == "🦉"
    assert senior["level"] == "SENIOR"
    assert senior["chosen"]["model"] == "claude-opus-5-5"
    assert senior["candidates"][1]["blocked"].startswith("Codex weekly")


@pytest.fixture
def steering_scope(test_db):
    return seed_steering_scope(test_db)


def test_composed_report_dry_runs_every_level_on_launch_surfaces_only(
    steering_scope,
):
    seed_session(
        steering_scope,
        "desktop-worker",
        executor="claude-code",
        executor_surface="claude-desktop",
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    assert report.levels is not None
    assert not report.levels.unavailable
    names = [placement.level for _glyph, placement in report.levels.levels]
    assert names == ["INTERN", "JUNIOR", "SENIOR", "PRINCIPAL"]
    surfaces = dict(report.levels.live_workers)
    assert "claude-desktop" not in surfaces
    assert surfaces["codex-cli"] == 2
    assert report_dict(report)["levels"]["levels"][0]["level"] == "INTERN"
    assert "launch with --level" in report_body(report)


def test_overrides_list_only_items_that_carry_one(steering_scope):
    steering_scope.execute(
        "UPDATE items SET workflow_posture = %s WHERE id = 1",
        (json.dumps({"level": {"max": "SENIOR", "reason": "well specified"}}),),
    )
    steering_scope.commit()

    overrides = read_level_overrides(steering_scope, {1: "YOK-1", 2: "YOK-2"})

    assert overrides == (("YOK-1", "level max SENIOR (well specified)"),)
    assert level_override_lines(overrides) == [
        "item level overrides",
        "  YOK-1  level max SENIOR (well specified)",
    ]
    assert level_override_lines(()) == []
