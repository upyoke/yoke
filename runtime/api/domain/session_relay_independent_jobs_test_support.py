# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from datetime import timedelta

import pytest

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.session_relay import claim_relay_job, report_relay_job

from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases

from yoke_core.domain.session_relay_types import SessionRelayError

from runtime.api.domain.session_relay_test_support import (
    MACHINE_ID,
    NOW,
    RELAY_ID,
    _add_wake_recipient,
    _connection as relay_connection,
    _heartbeat,
)

from runtime.api.domain.session_launch_test_support import assigned_launch, add_relay


def _connection():
    conn = relay_connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    return conn


def _wake(conn, session, message):
    _add_wake_recipient(conn, message_id=message, session_id=session)


def _fetch(conn, key):
    conn.execute(
        "INSERT INTO session_evidence_fetches "
        "(fetch_id,target_session_id,project_id,machine_id,tail_lines,state,requested_at,requested_by_actor_id) "
        "VALUES (?, 'worker-a',10,?,200,'pending',?,1)",
        (key, MACHINE_ID, NOW),
    )
    conn.commit()


def _claim(conn, seconds=0):
    return claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: parse_instant(NOW) + timedelta(seconds=seconds),
    ).jobs
