"""A level launch is placed by the quota pools each option's model draws on."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_placement import (
    LEVEL_UNKNOWN,
    RULE_HEADROOM,
    RULE_SPREAD,
    place_level,
)
from yoke_core.domain.session_launch_types import SessionLaunchError

from runtime.api.domain.session_launch_level_test_support import (
    CLAUDE_OPUS,
    CODEX_SOL,
    CURSOR_GROK,
    FIVE_HOUR_RESET,
    LEVEL,
    MONTH_RESET,
    add_surface,
    level_connection,
    pin_live_workers,
    unreadable,
    weekly,
    window,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization


@pytest.fixture(autouse=True)
def _no_live_workers(monkeypatch):
    pin_live_workers(monkeypatch, {})


def _place(conn, level: str = LEVEL):
    return place_level(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        level=level,
        machine_id=None,
        now=NOW,
        eligibility=derive_launch_eligibility,
    )


def _cursor_pools(cursor_models: float, other_models: float) -> list[dict]:
    return [
        window("monthly", cursor_models, scope="Cursor Models", resets_at=MONTH_RESET),
        window("monthly", other_models, scope="Other Models", resets_at=MONTH_RESET),
    ]


def test_claude_reads_the_5h_weekly_and_its_own_family_window_only() -> None:
    conn = level_connection(CLAUDE_OPUS)
    add_surface(
        conn,
        "m-claude",
        "claude-cli",
        [
            window("rolling_5h", 80.0, resets_at=FIVE_HOUR_RESET),
            weekly(90.0),
            weekly(30.0, scope="Opus"),
            # Another family's window at zero must neither block nor rank Opus.
            weekly(0.0, scope="Sonnet"),
        ],
    )

    placement = _place(conn)

    chosen = placement.chosen
    assert chosen is not None
    assert (chosen.surface, chosen.model) == ("claude-cli", "claude-opus-5-5")
    windows = [pool.window for pool in chosen.pools]
    assert len(windows) == 3
    assert not any("Sonnet" in name for name in windows)
    assert chosen.headroom_window == "weekly · Opus"
    assert chosen.headroom_percent == pytest.approx(60.0)
    assert chosen.blocked is None


def test_an_empty_family_window_blocks_the_claude_option() -> None:
    conn = level_connection(CLAUDE_OPUS)
    add_surface(
        conn, "m-claude", "claude-cli", [weekly(90.0), weekly(0.0, scope="Opus")]
    )

    placement = _place(conn)

    assert placement.chosen is None
    assert placement.rule is None
    assert "No SENIOR option has capacity" in placement.reason
    assert "claude-cli claude-opus-5-5 high on m-claude" in placement.reason
    assert "weekly · Opus pool exhausted" in placement.reason


def test_cursor_falls_back_to_other_models_when_cursor_models_is_empty() -> None:
    conn = level_connection(CURSOR_GROK)
    add_surface(conn, "m-cursor", "cursor-cli", _cursor_pools(0.0, 50.0))

    placement = _place(conn)

    primary, fallback = placement.candidates
    assert primary.model == "grok-4.7-high"
    assert "Cursor Models pool exhausted" in str(primary.blocked)
    assert [pool.window for pool in primary.pools] == ["monthly · Cursor Models"]
    assert placement.chosen == fallback
    assert fallback.fallback is True
    assert fallback.model == "claude-opus-5-5-medium"
    assert fallback.reasoning_effort == "medium"
    assert [pool.window for pool in fallback.pools] == ["monthly · Other Models"]
    assert "(fallback)" in fallback.label


def test_other_models_never_blocks_the_grok_option() -> None:
    conn = level_connection(CURSOR_GROK)
    add_surface(conn, "m-cursor", "cursor-cli", _cursor_pools(40.0, 0.0))

    placement = _place(conn)

    # The primary is open, so its fallback is not even weighed.
    assert len(placement.candidates) == 1
    assert placement.chosen is not None
    assert placement.chosen.model == "grok-4.7-high"
    assert placement.chosen.fallback is False


def test_cursor_refuses_when_the_fallback_pool_is_empty_too() -> None:
    conn = level_connection(CURSOR_GROK)
    add_surface(conn, "m-cursor", "cursor-cli", _cursor_pools(0.0, 0.0))

    placement = _place(conn)

    assert placement.chosen is None
    assert "Cursor Models pool exhausted" in placement.reason
    assert "Other Models pool exhausted" in placement.reason


def test_codex_reads_the_weekly_account_window() -> None:
    conn = level_connection(CODEX_SOL)
    add_surface(conn, "m-codex", "codex-cli", [weekly(0.0)])

    placement = _place(conn)

    assert placement.chosen is None
    assert "weekly · all models pool exhausted" in placement.reason


def test_an_idle_surface_above_full_headroom_is_spread_to_first(monkeypatch) -> None:
    conn = level_connection(CLAUDE_OPUS, CODEX_SOL)
    add_surface(conn, "m1", "claude-cli", [weekly(60.0)])
    add_surface(conn, "m2", "codex-cli", [weekly(95.0)])
    pin_live_workers(monkeypatch, {"codex-cli": 1})

    placement = _place(conn)

    assert placement.rule == RULE_SPREAD
    assert placement.chosen.surface == "claude-cli"
    assert placement.chosen.headroom_percent == pytest.approx(120.0)
    assert "spread rule" in placement.reason


def test_a_surface_with_a_live_worker_gets_no_spread_priority(monkeypatch) -> None:
    conn = level_connection(CLAUDE_OPUS, CODEX_SOL)
    add_surface(conn, "m1", "claude-cli", [weekly(75.0)])
    add_surface(conn, "m2", "codex-cli", [weekly(45.0)])

    pin_live_workers(monkeypatch, {"claude-cli": 2})

    placement = _place(conn)

    # Claude is busy at 150% and Codex idle at only 90%: nothing spreads, so
    # the most headroom wins.
    assert placement.rule == RULE_HEADROOM
    assert placement.chosen.surface == "claude-cli"
    assert placement.chosen.live_workers == 2
    assert placement.reason.startswith("most headroom")


def test_most_headroom_wins_when_no_surface_qualifies_to_spread() -> None:
    conn = level_connection(CLAUDE_OPUS, CODEX_SOL)
    add_surface(conn, "m1", "claude-cli", [weekly(20.0)])
    add_surface(conn, "m2", "codex-cli", [weekly(40.0)])

    placement = _place(conn)

    assert placement.rule == RULE_HEADROOM
    assert placement.chosen.surface == "codex-cli"
    assert placement.chosen.headroom_percent == pytest.approx(80.0)
    assert [c.chosen for c in placement.candidates] == [False, True]


def test_an_unreadable_meter_does_not_block_but_ranks_last() -> None:
    conn = level_connection(CLAUDE_OPUS, CODEX_SOL)
    add_surface(conn, "m1", "claude-cli", [unreadable()])
    add_surface(conn, "m2", "codex-cli", [weekly(10.0)])

    placement = _place(conn)

    claude = placement.candidates[0]
    assert claude.blocked is None
    assert claude.headroom_percent is None
    assert placement.chosen.surface == "codex-cli"


def test_an_option_with_only_an_unreadable_meter_still_launches() -> None:
    conn = level_connection(CLAUDE_OPUS)
    add_surface(conn, "m1", "claude-cli", [unreadable()])

    placement = _place(conn)

    assert placement.chosen is not None
    assert placement.reason.startswith("only option with capacity")


def test_option_order_breaks_a_headroom_tie() -> None:
    conn = level_connection(CODEX_SOL, CLAUDE_OPUS)
    add_surface(conn, "m1", "claude-cli", [weekly(30.0)])
    add_surface(conn, "m2", "codex-cli", [weekly(30.0)])

    placement = _place(conn)

    assert placement.chosen.option_index == 0
    assert placement.chosen.surface == "codex-cli"


def test_an_option_no_machine_offers_is_blocked_with_the_reason() -> None:
    conn = level_connection(CLAUDE_OPUS, CODEX_SOL)
    add_surface(conn, "m2", "codex-cli", [weekly(30.0)])

    placement = _place(conn)

    claude = placement.candidates[0]
    assert claude.machine_id is None
    assert str(claude.blocked).startswith("no usable machine offers claude-cli")
    assert placement.chosen.surface == "codex-cli"


def test_a_level_name_is_matched_case_insensitively() -> None:
    conn = level_connection(CODEX_SOL)
    add_surface(conn, "m2", "codex-cli", [weekly(30.0)])

    placement = _place(conn, level="senior")

    assert placement.level == LEVEL
    assert placement.levels_source == "universe"
    assert (
        placement.to_dict()["chosen"]["label"] == "codex-cli gpt-6.1-sol medium on m2"
    )


def test_an_unknown_level_is_refused_naming_the_defined_levels() -> None:
    conn = level_connection(CODEX_SOL)

    with pytest.raises(SessionLaunchError) as raised:
        _place(conn, level="WIZARD")

    assert raised.value.code == LEVEL_UNKNOWN
    assert "WIZARD" in str(raised.value)
    assert LEVEL in str(raised.value)


@pytest.mark.parametrize(
    "reset",
    [
        "2026-08-26T00:00:00.123456Z",
        "2026-08-26T05:45:00.123456+05:45",
        "2026-08-25T20:00:00.123456-04:00",
    ],
)
def test_placement_keeps_native_pool_reset_until_json_projection(reset) -> None:
    conn = level_connection(CODEX_SOL)
    add_surface(
        conn,
        "m-codex",
        "codex-cli",
        [
            window("rolling_7d", 30.0, resets_at=reset),
        ],
    )
    placement = _place(conn)
    chosen = placement.chosen
    assert chosen is not None
    assert chosen.pools[0].resets_at == datetime(
        2026, 8, 26, 0, 0, 0, 123456, tzinfo=timezone.utc
    )
    payload = json.loads(json.dumps(placement.to_dict()))
    assert payload["chosen"]["pools"][0]["resets_at"] == "2026-08-26T00:00:00.123456Z"
    assert payload["chosen"]["label"] == chosen.label
    assert payload["candidates"][0]["pools"] == payload["chosen"]["pools"]


def test_pool_projection_preserves_null_reset_and_opaque_window() -> None:
    from yoke_core.domain.session_launch_level_pools import PoolCheck

    pool = PoolCheck("opaque .123+offset", None, None, None, "unknown", False)
    assert json.loads(json.dumps(pool.to_dict())) == {
        "window": "opaque .123+offset",
        "remaining_percent": None,
        "headroom_percent": None,
        "resets_at": None,
        "status": "unknown",
        "exhausted": False,
    }


@pytest.mark.parametrize(
    "reset", ["", "2026-08-26", "2026-08-26T00:00:00", "2026-08-26T00:00:00-00:00"]
)
def test_pool_constructor_refuses_unverifiable_reset(reset) -> None:
    from yoke_contracts.timestamps import InvalidInstant
    from yoke_core.domain.session_launch_level_pools import PoolCheck

    with pytest.raises(InvalidInstant):
        PoolCheck("weekly", 30.0, 60.0, reset, "ok", False)
