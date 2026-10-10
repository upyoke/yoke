"""SQLite fixtures for level placement: levels, relays per surface, meters."""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    plan_limit_window,
    unknown_window,
)
from yoke_core.domain import session_launch_level_placement as placement_module
from yoke_core.domain.universe_levels import (
    create_universe_settings_table,
    write_universe_levels,
)

from runtime.api.domain.session_launch_test_support import add_relay, launch_connection


#: Three and a half days after the fixture clock, so a weekly window's
#: headroom is exactly twice its remaining percent.
HALF_WEEK_RESET = "2026-08-26T00:00:00.000000Z"
#: Five hours after the fixture clock: a rolling 5h window's headroom equals
#: its remaining percent.
FIVE_HOUR_RESET = "2026-08-22T17:00:00.000000Z"
MONTH_RESET = "2026-09-10T00:00:00.000000Z"
LEVEL = "SENIOR"
#: Every machine is shared capacity, so placement is decided by the meters.
SHARED_ACCESS = {"use": {"mode": "universe"}}
SURFACE_VERSIONS = {
    "claude-cli": "2.1.259",
    "codex-cli": "0.148.0a15",
    "cursor-cli": "2026.08.25",
}

CLAUDE_OPUS = {
    "surface": "claude-cli",
    "model": "claude-opus-5-5",
    "reasoning_effort": "high",
    "context_window_tokens": None,
}
CODEX_SOL = {
    "surface": "codex-cli",
    "model": "gpt-6.1-sol",
    "reasoning_effort": "medium",
    "context_window_tokens": None,
}
CURSOR_GROK = {
    "surface": "cursor-cli",
    "model": "grok-4.7-high",
    "reasoning_effort": "high",
    "context_window_tokens": None,
    "fallback": {
        "surface": "cursor-cli",
        "model": "claude-opus-5-5-medium",
        "reasoning_effort": "medium",
        "context_window_tokens": None,
    },
}


def level_connection(*options: dict[str, Any]):
    """A launch universe whose one stored level, SENIOR, has ``options``."""
    conn = launch_connection()
    create_universe_settings_table(conn)
    conn.execute(
        "CREATE TABLE project_capabilities "
        "(project_id INTEGER, type TEXT, settings TEXT)"
    )
    write_universe_levels(
        conn,
        [{"name": LEVEL, "glyph": "\U0001f989", "options": list(options)}],
        actor_id=1,
    )
    return conn


def window(
    kind: str,
    remaining: float,
    *,
    scope: str = ALL_MODELS_SCOPE,
    resets_at: str = HALF_WEEK_RESET,
) -> dict[str, Any]:
    return plan_limit_window(
        window_kind=kind,
        scope=scope,
        meter=f"{kind}.{scope}",
        remaining_percent=remaining,
        resets_at=resets_at,
    )


def unreadable() -> dict[str, Any]:
    return unknown_window("the meter did not answer")


def weekly(remaining: float, *, scope: str = ALL_MODELS_SCOPE) -> dict[str, Any]:
    """A weekly window whose headroom is twice ``remaining``."""
    return window("rolling_7d", remaining, scope=scope)


def add_surface(
    conn,
    machine_id: str,
    surface: str,
    windows: list[dict[str, Any]] | None = None,
) -> None:
    """One relay on ``machine_id`` offering ``surface`` with these meters."""
    add_relay(
        conn,
        relay_id=f"relay-{machine_id}-{surface}",
        machine_id=machine_id,
        surface=surface,
        version=SURFACE_VERSIONS[surface],
        plan_limits=(
            {surface: {"plan_tier": "max", "windows": windows}} if windows else None
        ),
        access=SHARED_ACCESS,
    )


def pin_live_workers(monkeypatch, workers: dict[str, int]) -> None:
    """Fix the live-worker count per surface that placement reads.

    The real count reads session rows through a Postgres-only probe filter;
    these tests decide placement, so they state the counts directly.
    """
    monkeypatch.setattr(placement_module, "live_workers", lambda _conn: dict(workers))


__all__ = [
    "CLAUDE_OPUS",
    "CODEX_SOL",
    "CURSOR_GROK",
    "FIVE_HOUR_RESET",
    "HALF_WEEK_RESET",
    "LEVEL",
    "MONTH_RESET",
    "add_surface",
    "level_connection",
    "pin_live_workers",
    "unreadable",
    "weekly",
    "window",
]
