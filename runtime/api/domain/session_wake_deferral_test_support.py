# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import sqlite3

from concurrent.futures import ThreadPoolExecutor

import pytest

import json

from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT

from yoke_harness.session_relay_native_turn_custody import (
    RESUME_CUSTODY_SOURCE,
    RunningNative,
)

from yoke_core.domain.session_relay import claim_relay_job, report_relay_job

from yoke_core.domain.session_relay_types import SessionRelayError

from yoke_core.domain.session_wake_deferral import restore_deferred_wake_budget

from runtime.api.domain.session_relay_test_support import (
    RELAY_ID,
    _add_wake_recipient,
    _clock,
    _connection,
    _heartbeat,
)

CLAIMED_AT = "2026-08-22T11:30:00Z"

RUNNING_NATIVE = RunningNative(
    session_id="target",
    pid=4001,
    process_start_time="Mon Aug 24 08:00:00 2026",
    source=RESUME_CUSTODY_SOURCE,
)


def _claim_wake(conn, *, now: str = CLAIMED_AT):
    claimed = claim_relay_job(
        conn, _heartbeat(), wait_seconds=0, now_provider=_clock(now)
    )
    assert claimed.jobs, "the seeded recipient should be claimable"
    return claimed.jobs[0]


def _recipient(conn) -> tuple[int, str, str]:
    return conn.execute(
        "SELECT wake_attempt_count,wake_after,state FROM session_message_recipients "
        "WHERE message_id='message-1'"
    ).fetchone()
