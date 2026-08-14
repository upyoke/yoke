# ruff: noqa: F811
"""A running Yoke command keeps its work claim out of stale cleanup."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.sessions_api_stale_test_helpers import (
    _ago_minutes,
    conn,  # noqa: F401 (backend-aware pytest fixture)
)
from runtime.api.test_sessions import _insert_claimable_items, _register
from yoke_core.domain import session_liveness_pump
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.domain.sessions import (
    claim_work,
    clean_stale_harness_sessions,
    heartbeat,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _claimable_items(conn):
    _insert_claimable_items(conn, 810, 811)


def _age_session(conn, session_id: str) -> None:
    old = _ago_minutes(30)
    conn.execute(
        "UPDATE harness_sessions SET offered_at=%s, last_heartbeat=%s "
        "WHERE session_id=%s",
        (old, old, session_id),
    )
    conn.execute(
        "UPDATE work_claims SET claimed_at=%s, last_heartbeat=%s "
        "WHERE session_id=%s AND released_at IS NULL",
        (old, old, session_id),
    )
    conn.commit()


def test_running_command_survives_while_dead_session_is_reclaimed(conn):
    _register(conn, session_id="running-command")
    _register(conn, session_id="dead-command")
    claim_work(conn, session_id="running-command", item_id="YOK-810")
    claim_work(conn, session_id="dead-command", item_id="YOK-811")
    _age_session(conn, "running-command")
    _age_session(conn, "dead-command")
    clock = Clock()
    pump = SessionLivenessPump(
        session_id="running-command",
        interval_seconds=1.0,
        clock=clock,
    )
    clock.now = 1.0

    def refresh(session_id: str) -> bool:
        heartbeat(conn, session_id)
        return True

    with patch.object(
        session_liveness_pump,
        "refresh_session_heartbeat",
        side_effect=refresh,
    ):
        assert pump.tick()

    result = clean_stale_harness_sessions(
        conn,
        stale_threshold_minutes=1,
        progress_threshold_minutes=90,
    )

    assert result["total_reclaimed"] == 1
    assert result["never_engaged"][0]["session_id"] == "dead-command"
    live = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s",
        ("running-command",),
    ).fetchone()
    assert live["ended_at"] is None
    live_claim = conn.execute(
        "SELECT released_at FROM work_claims WHERE item_id=%s",
        (810,),
    ).fetchone()
    assert live_claim["released_at"] is None
