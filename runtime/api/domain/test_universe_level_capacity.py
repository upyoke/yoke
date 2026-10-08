"""Each level's launch standing: the pools per option and what blocks it.

The readings are the approved Levels design's: Claude weekly 177% headroom
with 72% left (Fable 100% left), Codex weekly 79% / 35%, Cursor Models 998% /
9%, and Cursor Other Models exhausted. Where the next launch goes is the
launcher's answer, covered by ``test_universe_level_next_launch``.
"""

from __future__ import annotations

from yoke_contracts.levels import default_levels
from yoke_core.domain.universe_level_capacity import (
    Meter,
    evaluate_level_capacity,
    pool_label,
)

MACHINE = "machine-1"
OFFERED = [(MACHINE, "claude-cli"), (MACHINE, "codex-cli"), (MACHINE, "cursor-cli")]


def _meter(surface, kind, scope, left, headroom):
    return Meter(MACHINE, surface, kind, scope, "ok", left, headroom)


def _meters(*, fable_left=100.0, codex_left=35.0):
    codex_headroom = 79.4 if codex_left else 0.0
    return [
        _meter("claude-cli", "rolling_7d", "all", 72.0, 177.2),
        _meter(
            "claude-cli", "rolling_7d", "Fable", fable_left, None if fable_left else 0.0
        ),
        _meter("codex-cli", "rolling_7d", "all", codex_left, codex_headroom),
        _meter("cursor-cli", "monthly", "Cursor Models", 9.0, 998.0),
        _meter("cursor-cli", "monthly", "Other Models", 0.0, 0.0),
    ]


def _evaluate(meters, offered=OFFERED):
    return {
        level["name"]: level
        for level in evaluate_level_capacity(
            default_levels(),
            meters=meters,
            offered=offered,
            display=lambda model: {"claude-haiku-4-5": "Claude Haiku 4.5"}.get(
                model, model
            ),
        )
    }


def test_pool_labels_name_the_vendor_window_and_scope_only_when_it_disambiguates():
    assert pool_label("claude-cli", "rolling_7d", "all", scoped=True) == (
        "Claude weekly · all models"
    )
    assert pool_label("claude-cli", "rolling_7d", "Fable", scoped=True) == (
        "Claude weekly · Fable"
    )
    assert pool_label("codex-cli", "rolling_7d", "all", scoped=False) == "Codex weekly"
    assert pool_label("cursor-cli", "monthly", "Cursor Models", scoped=True) == (
        "Cursor Models"
    )
    assert pool_label("cursor-cli", "monthly", "Other Models", scoped=True) == (
        "Cursor Other Models"
    )


def test_options_read_only_the_pools_their_model_draws_on():
    levels = _evaluate(_meters())
    intern = levels["INTERN"]
    assert intern["launchable_surfaces"] == ["claude-cli", "codex-cli"]
    assert "next_launch" not in intern
    assert intern["options"][0]["display_name"] == "Claude Haiku 4.5"
    junior = levels["JUNIOR"]
    cursor = junior["options"][0]
    assert [pool["label"] for pool in cursor["pools"]] == ["Cursor Models"]
    assert [pool["label"] for pool in cursor["fallback"]["pools"]] == [
        "Cursor Other Models"
    ]
    assert cursor["now"]["state"] == "can_launch"
    assert cursor["now"]["via"] is None
    assert cursor["now"]["binding_pool"] == {
        "label": "Cursor Models",
        "left": 9,
        "headroom": 998,
    }
    codex = junior["options"][1]["now"]["binding_pool"]
    assert (codex["label"], codex["headroom"], codex["left"]) == (
        "Codex weekly",
        79,
        35,
    )
    principal = levels["PRINCIPAL"]["options"][0]
    assert [pool["label"] for pool in principal["pools"]] == [
        "Claude weekly · all models",
        "Claude weekly · Fable",
    ]


def test_a_level_with_no_launchable_option_names_each_blocking_pool():
    levels = _evaluate(_meters(fable_left=0.0, codex_left=0.0))
    principal = levels["PRINCIPAL"]
    assert principal["launchable_surfaces"] == []
    assert [option["now"] for option in principal["options"]] == [
        {
            "state": "blocked",
            "blockers": [{"kind": "pool", "label": "Claude weekly · Fable", "left": 0}],
        },
        {
            "state": "blocked",
            "blockers": [{"kind": "pool", "label": "Codex weekly", "left": 0}],
        },
    ]
    assert levels["SENIOR"]["launchable_surfaces"] == ["claude-cli"]


def test_cursor_option_falls_back_only_when_its_own_pool_is_exhausted():
    meters = [m for m in _meters() if m.scope != "Cursor Models"]
    meters.append(_meter("cursor-cli", "monthly", "Cursor Models", 0.0, 0.0))
    meters = [m for m in meters if m.scope != "Other Models"]
    meters.append(_meter("cursor-cli", "monthly", "Other Models", 40.0, 120.0))
    cursor = _evaluate(meters)["JUNIOR"]["options"][0]
    assert cursor["now"]["state"] == "can_launch"
    assert cursor["now"]["via"] == cursor["fallback"]["model"]
    assert cursor["now"]["binding_pool"]["label"] == "Cursor Other Models"


def test_a_surface_no_usable_machine_offers_blocks_by_name():
    offered = [(MACHINE, "claude-cli")]
    codex = _evaluate(_meters(), offered=offered)["SENIOR"]["options"][1]
    assert codex["now"] == {
        "state": "blocked",
        "blockers": [{"kind": "no_machine", "surface": "codex-cli"}],
    }


def test_unreadable_meters_never_block():
    senior = _evaluate([])["SENIOR"]
    assert [o["now"]["state"] for o in senior["options"]] == ["can_launch"] * 2
    assert [o["now"]["binding_pool"] for o in senior["options"]] == [None, None]
