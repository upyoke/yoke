# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import sqlite3

from concurrent.futures import ThreadPoolExecutor

from datetime import timedelta

from yoke_core.domain.session_message_service import send_message

from yoke_core.domain.session_message_wake import wake_eligible_recipients

from yoke_core.domain.session_relay_jobs import claim_wake_job

from yoke_core.domain.session_relay_types import RelayHeartbeat

from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt

from yoke_core.domain.session_turn_posture import stamp_turn_posture

from runtime.api.domain.session_message_support_test_support import (
    ALPHA_WORKSPACE,
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


def _waiting(conn: sqlite3.Connection) -> None:
    stamp_turn_posture(
        conn,
        session_id=NATIVE_WAKE_SESSION_ID,
        posture="waiting",
        observed_at=NOW - timedelta(seconds=1),
    )
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
