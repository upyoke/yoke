# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import format_instant

from runtime.api.sessions_api_stale_test_helpers import _ago_minutes

from runtime.api.sessions_test_support import _insert_claimable_items, _register

from yoke_core.domain import session_process_liveness_report as liveness_report

from yoke_core.domain import sessions_analytics

from yoke_core.domain.session_native_process_observation import (
    CLAIMS_HELD_STATUS,
    current_native_process_observation,
)

from yoke_core.domain.session_process_liveness_report import (
    PROCESS_VERIFIED_DEAD_REASON,
    apply_verified_process_death_reports,
)

from yoke_core.domain.events_tool_call_outcome import OUTCOME_INTERRUPTED

from yoke_core.domain.sessions import claim_work

from yoke_core.domain.sessions_analytics import (
    EVENT_HARNESS_SESSION_ENDED,
    SessionError,
)

MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

LAUNCH_ID = "9f1f2d4e-0f7a-4a71-9a1a-6a0c0b6f2d10"

EVIDENCE = {
    "records_considered": 1,
    "sources": ["launch_handle"],
    "pids": [4002],
    "process_start_times": {"4002": "1699999999"},
    "launch_id": LAUNCH_ID,
}

MEASURED_USAGE = json.dumps(
    {
        "status": "complete",
        "reason": "",
        "observed_at": "2026-09-08T17:00:00.000000Z",
        "source": "cursor parent-turn stop/afterAgentResponse token fields; "
        "print-mode result usage",
        "models": [
            {
                "model": "cursor-grok-4.6-high",
                "input": 102596,
                "cached_input": 9600,
                "cache_write": 0,
                "cache_write_long": 0,
                "output": 30,
                "reasoning": 0,
            }
        ],
    }
)

ANCHOR_EVIDENCE = {
    "records_considered": 1,
    "sources": ["process_anchor"],
    "pids": [4003],
    "process_start_times": {"4003": "1699999998"},
}


@pytest.fixture
def conn(test_db):
    return test_db


def _ghost(
    conn,
    session_id: str = "sess-ghost",
    *,
    machine_id: str = MACHINE,
    executor_surface: str | None = None,
) -> str:
    kwargs = {"machine_id": machine_id}
    if executor_surface:
        kwargs["executor"] = executor_surface
    _register(conn, session_id=session_id, **kwargs)
    old = _ago_minutes(120)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s, last_heartbeat=%s, "
        "last_tool_call_at=%s WHERE session_id=%s",
        (machine_id, old, old, session_id),
    )
    conn.commit()
    return session_id


def _apply(
    conn,
    session_id: str,
    *,
    projects=(1,),
    machine_id: str = MACHINE,
    evidence=None,
    usage_totals=None,
):
    report = {
        "session_id": session_id,
        "evidence": EVIDENCE if evidence is None else evidence,
    }
    if usage_totals is not None:
        report["usage_totals"] = usage_totals
    return apply_verified_process_death_reports(
        conn,
        machine_id=machine_id,
        authorized_projects=projects,
        reports=[report],
    )


def _session_row(conn, session_id: str):
    return dict(
        conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (session_id,)
        ).fetchone()
    )
