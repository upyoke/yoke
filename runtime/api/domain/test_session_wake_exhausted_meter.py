"""Refuse a wake that would spend a published meter already at zero."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from runtime.api.domain.test_session_message_support import (
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
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


RESET = "2026-10-07T00:00:00Z"
OTHER_METER = "planUsage.apiPercentUsed"
CURSOR_METER = "planUsage.autoPercentUsed"


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
            "2026-08-23T00:00:00Z",
            json.dumps(
                {
                    surface: {
                        "surface": surface,
                        "plan_tier": "Ultra",
                        "observed_at": NOW_TEXT,
                        "windows": windows,
                    }
                }
            ),
        ),
    )
    conn.commit()


def _queue_stopped_codex(conn, remaining: float) -> str:
    _pin(
        conn,
        NATIVE_WAKE_SESSION_ID,
        surface="codex-cli",
        model="gpt-5",
        machine_id="m4",
        project_id=1,
        windows=_rolling("primary", remaining),
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


def test_operator_wake_refuses_an_empty_meter_and_does_not_queue() -> None:
    conn = message_connection()
    _pin(
        conn,
        "s2",
        surface="claude-cli",
        model="claude-opus-4-6",
        machine_id="m2",
        project_id=1,
        windows=_rolling("five_hour", 0.0),
    )

    with pytest.raises(SessionMessageError) as refused:
        request_session_wake(
            conn,
            actor_id=10,
            caller_session_id="s1",
            session_id="s2",
            public_ref=None,
            prompt=None,
            now=NOW,
        )

    text = str(refused.value)
    assert refused.value.code == METER_EXHAUSTED_CODE
    assert "five_hour" in text
    assert "0%" in text
    assert RESET in text
    assert RECOVERY in text
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0


def test_unknown_meter_does_not_refuse_a_wake() -> None:
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET model=? WHERE session_id='s2'",
        ("claude-opus-4-6",),
    )
    conn.commit()

    assert refuse_exhausted_wake(conn, "s2", NOW) is None
    result = request_session_wake(
        conn,
        actor_id=10,
        caller_session_id="s1",
        session_id="s2",
        public_ref=None,
        prompt=None,
        now=NOW,
    )
    assert result["result_code"] == "queued"
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 1


def test_opus_reads_the_other_models_pool_not_cursor_models() -> None:
    conn = message_connection()
    _pin(
        conn,
        "s2",
        surface="cursor-cli",
        model="claude-opus-4-6",
        machine_id="m2",
        project_id=1,
        windows=[
            plan_limit_window(
                window_kind="monthly",
                scope=CURSOR_MODELS_SCOPE,
                meter=CURSOR_METER,
                remaining_percent=0.0,
                resets_at=RESET,
            ),
            plan_limit_window(
                window_kind="monthly",
                scope=CURSOR_OTHER_MODELS_SCOPE,
                meter=OTHER_METER,
                remaining_percent=50.0,
                resets_at=RESET,
            ),
        ],
    )
    assert meter_wall(conn, "s2", NOW) is None

    conn.execute(
        "UPDATE harness_sessions SET model=? WHERE session_id='s2'",
        ("composer-1",),
    )
    wall = meter_wall(conn, "s2", NOW)
    assert wall is not None
    assert wall.meter == CURSOR_METER
    assert wall.remaining_percent == 0.0


def test_automatic_reentry_does_not_offer_an_exhausted_session() -> None:
    conn = message_connection()
    message_id = _queue_stopped_codex(conn, 0.0)

    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

    attempt = conn.execute(
        "SELECT result_code, completed_at, lease_id, evidence "
        "FROM session_message_attempts WHERE message_id=?",
        (message_id,),
    ).fetchone()
    evidence = json.loads(attempt["evidence"])
    assert attempt["result_code"] == SKIP_METER_EXHAUSTED
    assert attempt["completed_at"]
    assert attempt["lease_id"] is None
    assert evidence["skip_reason"] == "model_meter_exhausted"
    assert "primary" in evidence["probe_detail"]
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients "
            "WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        == 0
    )


def test_claim_does_not_open_a_native_when_the_meter_drains() -> None:
    conn = message_connection()
    _queue_stopped_codex(conn, 50.0)
    candidate = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))[0]
    conn.execute(
        "UPDATE session_relays SET surface_plan_limits=? WHERE relay_id=?",
        (
            json.dumps(
                {
                    "codex-cli": {
                        "surface": "codex-cli",
                        "plan_tier": "Ultra",
                        "observed_at": NOW_TEXT,
                        "windows": _rolling("primary", 0.0),
                    }
                }
            ),
            "machine:m4",
        ),
    )
    conn.commit()
    assert (
        claim_wake_attempt(conn, candidate=candidate, now="2026-08-22T16:11:00Z")
        is None
    )
    conn.commit()
    attempt = conn.execute(
        "SELECT lease_id FROM session_message_attempts WHERE result_code=?",
        (SKIP_METER_EXHAUSTED,),
    ).fetchone()
    assert attempt["lease_id"] is None


def test_resumed_died_against_an_empty_meter_is_blocked() -> None:
    conn = message_connection()
    _pin(
        conn,
        "s2",
        surface="claude-cli",
        model="claude-opus-4-6",
        machine_id="m2",
        project_id=1,
        windows=_rolling("five_hour", 0.0),
    )
    assert overlay_resume_state(conn, "s2", "resumed-died", NOW) == BLOCKED_METER_RESUME
    assert overlay_resume_state(conn, "s2", "wake-delivered", NOW) == "wake-delivered"


def test_resumed_died_with_headroom_stays_resumed_died() -> None:
    conn = message_connection()
    _pin(
        conn,
        "s2",
        surface="claude-cli",
        model="claude-opus-4-6",
        machine_id="m2",
        project_id=1,
        windows=_rolling("five_hour", 1.0),
    )
    assert overlay_resume_state(conn, "s2", "resumed-died", NOW) == "resumed-died"
