"""A level no-capacity refusal stays short however many machines it weighed."""

from __future__ import annotations

import pytest

from yoke_contracts.levels import Level
from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_candidate import (
    LevelCandidate,
    placement_refusal,
)
from yoke_core.domain.session_launch_level_placement import place_level

from runtime.api.domain.session_launch_level_test_support import (
    CLAUDE_OPUS,
    CODEX_SOL,
    CURSOR_GROK,
    EXTRA_OFF,
    LEVEL,
    add_surface,
    level_connection,
    pin_live_workers,
    weekly,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
)

#: The read limit a refusal must fit under to reach the caller whole.
READ_LIMIT_BYTES = 28_000
OFFLINE_SEEN = "2026-08-14T09:00:00.000000Z"
OFFLINE_UNTIL = "2026-08-14T09:20:00.000000Z"


@pytest.fixture(autouse=True)
def _no_live_workers(monkeypatch):
    pin_live_workers(monkeypatch, {})


def _candidate(index: int, surface: str, blocked: str) -> LevelCandidate:
    return LevelCandidate(
        option_index=index,
        surface=surface,
        model=f"model-{index}",
        reasoning_effort="medium",
        context_window_tokens=None,
        machine_id=None,
        blocked=blocked,
    )


def test_options_sharing_one_reason_share_one_clause() -> None:
    shared = "no usable machine offers cursor-cli (3 machines offline)"
    weighed = [
        _candidate(0, "cursor-cli", shared),
        _candidate(1, "claude-cli", "weekly pool exhausted"),
        _candidate(2, "cursor-cli", shared),
    ]
    level = Level(name=LEVEL, glyph="", options=())

    message = placement_refusal(level, weighed, surface=None)

    assert (
        "cursor-cli model-0 medium, cursor-cli model-2 medium: " + shared
    ) in message
    assert "claude-cli model-1 medium: weekly pool exhausted" in message
    assert message.count(shared) == 1


def test_many_offline_machines_and_one_full_machine_fit_the_read_limit() -> None:
    conn = level_connection(CLAUDE_OPUS, CODEX_SOL, CURSOR_GROK)
    add_surface(conn, "m-claude", "claude-cli", [weekly(0.0)], EXTRA_OFF)
    for index in range(96):
        name = f"offline-box-{index:02d}"
        add_relay(
            conn,
            relay_id=f"relay-{name}",
            machine_id=f"machine-{name}",
            hostname=name,
            surface="cursor-cli" if index % 2 else "codex-cli",
            last_seen_at=OFFLINE_SEEN,
            connected_until=OFFLINE_UNTIL,
            projects=[99],
        )

    placement = place_level(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        level=LEVEL,
        machine_id=None,
        now=parse_instant(NOW),
        eligibility=derive_launch_eligibility,
    )

    reason = placement.reason
    assert placement.chosen is None
    assert len(reason.encode("utf-8")) < READ_LIMIT_BYTES // 10
    assert "claude-cli claude-opus-5-5 high on m-claude" in reason
    assert "96 machines offline (newest last seen 2026-08-14T09:00:00Z)" in reason
    assert "offline-box-" not in reason
    assert reason.count("no usable machine offers cursor-cli") == 1
    assert "cursor-cli grok-4.7 high: no usable machine offers cursor-cli" in reason
