# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import timedelta

import pytest

from runtime.api.domain.session_message_support_test_support import (
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)

from yoke_contracts.session_control.extra_usage import (
    EXTRA_AVAILABLE,
    EXTRA_DISABLED,
    extra_usage,
)

from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    CURSOR_MODELS_SCOPE,
    CURSOR_OTHER_MODELS_SCOPE,
    plan_limit_window,
)

from yoke_core.domain.session_manual_wake import request_session_wake

from yoke_core.domain.session_message_service import send_message

from yoke_core.domain.session_message_types import SessionMessageError

from yoke_core.domain.session_message_wake import wake_eligible_recipients

from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt

from yoke_core.domain.session_turn_posture import stamp_turn_posture

from yoke_core.domain.session_wake_meter import (
    BLOCKED_METER_RESUME,
    METER_EXHAUSTED_CODE,
    RECOVERY,
    SKIP_METER_EXHAUSTED,
    meter_wall,
    overlay_resume_state,
    refuse_exhausted_wake,
)

RESET = "2026-10-07T00:00:00.000000Z"

WAKE_AT = NOW + timedelta(minutes=11)

FRESH_FOR_WAKE = "2026-08-22T16:10:00.000000Z"

DISABLED = extra_usage(EXTRA_DISABLED, meter="extra", reason="user_disabled")

CREDITS = extra_usage(
    EXTRA_AVAILABLE, meter="rateLimits.credits", balance=61206.81, units="Codex credits"
)

_ABSENT = object()


def _rolling(meter: str, remaining: float) -> list[dict]:
    return [
        plan_limit_window(
            window_kind="rolling_5h",
            scope=ALL_MODELS_SCOPE,
            meter=meter,
            remaining_percent=remaining,
            resets_at=RESET,
        )
    ]


def _pin(
    conn,
    session_id: str,
    *,
    surface: str,
    model: str,
    machine_id: str,
    project_id: int,
    windows: list[dict],
    extra: object = DISABLED,
    observed_at: str = NOW_TEXT,
) -> None:
    conn.execute(
        "UPDATE harness_sessions SET executor_surface=?, model=? WHERE session_id=?",
        (surface, model, session_id),
    )
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state,surface_plan_limits) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,'active',?)",
        (
            f"machine:{machine_id}",
            10,
            machine_id,
            "relay-host",
            "0.1.1",
            json.dumps({surface: "1.0.0"}),
            json.dumps([project_id]),
            NOW_TEXT,
            NOW_TEXT,
            "2026-08-23T00:00:00.000000Z",
            json.dumps({surface: _reading(surface, windows, extra, observed_at)}),
        ),
    )
    conn.commit()


def _reading(surface: str, windows: list[dict], extra: object, observed_at: str):
    reading = {
        "surface": surface,
        "plan_tier": "Ultra",
        "observed_at": observed_at,
        "windows": windows,
    }
    if extra is not _ABSENT:
        reading["extra_usage"] = extra
    return reading


def _queue_stopped_codex(conn, remaining: float, extra: object = DISABLED) -> str:
    _pin(
        conn,
        NATIVE_WAKE_SESSION_ID,
        surface="codex-cli",
        model="gpt-5",
        machine_id="m4",
        project_id=1,
        windows=_rolling("primary", remaining),
        extra=extra,
        observed_at=FRESH_FOR_WAKE,
    )
    stamp_turn_posture(
        conn,
        session_id=NATIVE_WAKE_SESSION_ID,
        posture="waiting",
        observed_at=NOW - timedelta(seconds=1),
    )
    conn.execute(
        "UPDATE harness_sessions SET native_thread_id=?,ended_at=? WHERE session_id=?",
        ("codex-thread-s4", NOW_TEXT, NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Continue.",
        now=NOW,
    )["message_id"]
