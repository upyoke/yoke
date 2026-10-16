"""SQLite fixtures for level placement: levels, relays per surface, meters."""

from __future__ import annotations

from typing import Any
import json
from yoke_core.domain.model_reference_store import (
    create_model_reference_table,
    seed_initial_catalog,
)
from yoke_contracts.session_control.native_models import models_reading, native_model
from runtime.api.domain.session_launch_test_support import NOW

from yoke_contracts.session_control.extra_usage import EXTRA_DISABLED, extra_usage
from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    plan_limit_window,
    unknown_window,
)
from yoke_core.domain import session_launch_level_placement as placement_module
from yoke_core.domain.session_launch_machine_models import machine_native_models
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

CLAUDE_OPUS = {"model": "claude-opus-5-5", "min_effort": "high"}
CODEX_SOL = {"model": "gpt-6.1-sol", "min_effort": "medium"}
CURSOR_GROK = {"model": "grok-4.7", "min_effort": "high"}
CURSOR_OPUS = {"model": "claude-opus-5-5", "min_effort": "medium"}
NATIVE_MODELS = {
    "claude-cli": [
        native_model("claude-opus-5-5", reasoning_efforts=["low", "medium", "high"])
    ],
    "codex-cli": [
        native_model("gpt-6.1-sol", reasoning_efforts=["low", "medium", "high"])
    ],
    "cursor-cli": [
        native_model("grok-4.7-high", reasoning_efforts=["high"]),
        native_model("claude-opus-5-5-medium", reasoning_efforts=["medium"]),
    ],
}


def level_connection(*options: dict[str, Any]):
    """A launch universe whose one stored level, SENIOR, has ``options``."""
    conn = launch_connection()
    create_model_reference_table(conn)
    seed_initial_catalog(conn)
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


#: Paid extra usage switched off: an empty included pool really stops work.
EXTRA_OFF = extra_usage(EXTRA_DISABLED, meter="fixture", reason="user_disabled")


def plan_reading(
    windows: list[dict[str, Any]], extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One surface's stored reading: its windows and, when given, extra usage."""
    reading: dict[str, Any] = {"plan_tier": "max", "windows": windows}
    if extra is not None:
        reading.update(observed_at=NOW, extra_usage=extra)
    return reading


def add_surface(
    conn,
    machine_id: str,
    surface: str,
    windows: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """One relay on ``machine_id`` offering ``surface`` with these meters.

    ``extra`` is the surface's paid extra-usage fact, observed at the fixture
    clock so it is fresh; without it the fact is absent and reads unknown.
    """
    readings = machine_native_models(conn, machine_id=machine_id)
    add_relay(
        conn,
        relay_id=f"relay-{machine_id}-{surface}",
        machine_id=machine_id,
        surface=surface,
        version=SURFACE_VERSIONS[surface],
        plan_limits=({surface: plan_reading(windows, extra)} if windows else None),
        access=SHARED_ACCESS,
    )
    reading = models_reading(
        surface, NATIVE_MODELS[surface], source="native fixture", observed_at=NOW
    )
    readings[surface] = reading
    conn.execute(
        "UPDATE session_relays SET surface_native_models = ? WHERE machine_id = ?",
        (json.dumps(readings), machine_id),
    )
    conn.commit()


def pin_live_workers(monkeypatch, workers: dict[tuple[str, str, str], int]) -> None:
    """Fix the live workers per ``(machine, surface, model)`` placement reads.

    The real count reads session rows through a Postgres-only probe filter;
    these tests decide placement, so they state the counts directly.
    """
    monkeypatch.setattr(placement_module, "live_workers", lambda _conn: dict(workers))


__all__ = [
    "CLAUDE_OPUS",
    "CODEX_SOL",
    "CURSOR_GROK",
    "CURSOR_OPUS",
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
