# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.session_launch_test_support import relay_connection

from runtime.api.domain.session_relay_test_support import (
    RELAY_ID,
    _add_wake_recipient,
    _clock,
    _connection as relay_job_connection,
    _heartbeat,
)

from yoke_contracts.session_control.resume import (
    RESUME_NEVER_STARTED_RESULT,
    RESUMED_DIED_RESULT,
    RESUMED_RUNNING_RESULT,
)

from yoke_contracts.session_control.wake_delivery import (
    TURN_WITHOUT_INJECTION_RESULT,
)

from yoke_core.domain.session_wake_reconciliation import (
    EVENT_SESSION_WAKE_OUTCOME_RECORDED,
    reconcile_spawned_wake_attempts,
)

from yoke_core.domain.session_relay import claim_relay_job, report_relay_job


def _add_events_table(conn) -> None:
    conn.execute(
        "CREATE TABLE events ("
        "event_id TEXT PRIMARY KEY,event_name TEXT,event_kind TEXT,event_type TEXT,"
        "source_type TEXT,session_id TEXT,severity TEXT,event_outcome TEXT,"
        "org_id TEXT,environment TEXT,service TEXT,project_id INTEGER,"
        "actor_id INTEGER,item_id TEXT,task_num INTEGER,agent TEXT,tool_name TEXT,"
        "duration_ms INTEGER,exit_code INTEGER,trace_id TEXT,anomaly_flags TEXT,"
        "tool_use_id TEXT,turn_id TEXT,hook_event_name TEXT,client_timing_id TEXT,"
        "envelope TEXT,"
        "created_at TEXT)"
    )
