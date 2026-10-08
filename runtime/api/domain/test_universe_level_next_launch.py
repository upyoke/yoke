"""The Levels read's next launch is the launcher's own placement, previewed."""

from __future__ import annotations

import pytest

from yoke_core.domain import session_launch_preview_payload as preview_module
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_placement import (
    LEVEL_NO_CAPACITY,
    RULE_HEADROOM,
    RULE_SPREAD,
)
from yoke_core.domain.session_launch_level_selection import preview_level_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.universe_level_next_launch import next_launches
from yoke_core.domain.universe_levels import effective_levels

from runtime.api.domain.session_launch_level_test_support import (
    CLAUDE_OPUS,
    CODEX_SOL,
    LEVEL,
    add_surface,
    level_connection,
    pin_live_workers,
    weekly,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization

PROJECT = (10, "launch-project")


@pytest.fixture(autouse=True)
def _fixture_clock(monkeypatch):
    monkeypatch.setattr(preview_module, "utc_now", lambda: NOW)


def _universe(*, claude: float, codex: float):
    conn = level_connection(CODEX_SOL, CLAUDE_OPUS)
    add_surface(conn, "m-codex", "codex-cli", [weekly(codex)])
    add_surface(conn, "m-claude", "claude-cli", [weekly(claude)])
    return conn


def _next(conn, *, authorize=lambda _project_id: authorization()):
    levels, _ = effective_levels(conn, None)
    return next_launches(
        conn,
        levels,
        [PROJECT],
        authorize=authorize,
        display=lambda model: model.upper(),
    )[LEVEL]


def _launcher_choice(conn):
    """Where a level launch create would place the same ask."""
    _, preview = preview_level_launch(
        conn,
        auth=authorization(),
        request=LaunchRequest(
            project_id=PROJECT[0],
            executor_surface="",
            instructions="",
            idempotency_key="",
            level=LEVEL,
        ),
        now=NOW,
        eligibility=derive_launch_eligibility,
    )
    return preview.level_placement["chosen"], preview.placement_reason


@pytest.mark.parametrize(
    ("workers", "rule", "surface"),
    [
        ({}, RULE_SPREAD, "codex-cli"),
        ({"codex-cli": 1}, RULE_SPREAD, "claude-cli"),
        ({"codex-cli": 1, "claude-cli": 1}, RULE_HEADROOM, "codex-cli"),
    ],
)
def test_next_launch_is_the_launchers_placement(monkeypatch, workers, rule, surface):
    pin_live_workers(monkeypatch, workers)
    conn = _universe(claude=60.0, codex=70.0)
    (entry,) = _next(conn)
    chosen, reason = _launcher_choice(conn)
    assert entry["launchable"] is True
    assert (entry["surface"], entry["rule"]) == (surface, rule)
    assert (entry["surface"], entry["model"], entry["option_index"]) == (
        chosen["surface"],
        chosen["model"],
        chosen["option_index"],
    )
    assert entry["machine_id"] == chosen["machine_id"]
    assert entry["reason"] == reason
    assert entry["display_name"] == chosen["model"].upper()
    assert entry["project"] == PROJECT[1]


def test_a_level_with_no_capacity_reports_the_launchers_refusal(monkeypatch):
    pin_live_workers(monkeypatch, {})
    (entry,) = _next(_universe(claude=0.0, codex=0.0))
    assert entry["launchable"] is False
    assert entry["code"] == LEVEL_NO_CAPACITY
    assert entry["reason"].startswith(f"No {LEVEL} option has capacity")
    assert "surface" not in entry


def test_a_caller_who_cannot_launch_there_is_refused_by_name(monkeypatch):
    pin_live_workers(monkeypatch, {})
    conn = _universe(claude=60.0, codex=70.0)
    (entry,) = _next(conn, authorize=lambda _id: authorization(operator=False))
    assert (entry["launchable"], entry["code"]) == (False, "permission_denied")

    def unverified(_project_id):
        raise SessionLaunchError("actor_required", "verified numeric actor is required")

    (entry,) = _next(conn, authorize=unverified)
    assert entry == {
        "project": PROJECT[1],
        "launchable": False,
        "code": "actor_required",
        "reason": "verified numeric actor is required",
    }
