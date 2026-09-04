"""One codex worker whose turn the model provider ended, for both suites.

The fixture is shared because deciding and acting are asserted separately
and must be asserted against the same world: a support module that drifts
from either suite would let the sweep pass on a machine the state reader
never sees. The numbers are the observed incident's — the 404 five
workers died on, and the client version that was installed under them
while they were down.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from runtime.api.domain.session_launch_test_support import (
    add_relay,
    relay_connection,
)
from yoke_core.domain.session_native_turn_end import (
    EVENT_SESSION_TURN_END_OBSERVED,
)
from yoke_core.domain.session_vendor_error_states import (
    EVENT_SESSION_VENDOR_ERROR_RESUMED,
    vendor_error_states,
)


MACHINE_ID = "machine-1"
SESSION_ID = "worker"
PROJECT_ID = 10
INSTALLED_VERSION = "0.152.1"
SESSION_VERSION = "0.151.0-alpha.7.2"
TURN_ENDED_AT = datetime(2026, 9, 3, 15, 3, 29, tzinfo=timezone.utc)
# The failure five workers actually died on, classified only as "other".
LIVE_ERROR = (
    "unexpected status 404 Not Found: Unknown error, url: "
    "https://chatgpt.com/backend-api/codex/responses"
)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def worker_connection():
    """A codex worker on this machine whose turn ended on the vendor."""
    conn = relay_connection()
    conn.execute(
        "CREATE TABLE events ("
        "event_id TEXT PRIMARY KEY,event_name TEXT,event_kind TEXT,"
        "event_type TEXT,source_type TEXT,session_id TEXT,severity TEXT,"
        "event_outcome TEXT,org_id TEXT,environment TEXT,service TEXT,"
        "project_id INTEGER,actor_id INTEGER,item_id TEXT,task_num INTEGER,"
        "agent TEXT,tool_name TEXT,duration_ms INTEGER,exit_code INTEGER,"
        "trace_id TEXT,anomaly_flags TEXT,tool_use_id TEXT,turn_id TEXT,"
        "hook_event_name TEXT,client_timing_id TEXT, envelope TEXT,created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE session_tool_calls ("
        "id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,tool_use_id TEXT,"
        "tool_name TEXT,started_at TEXT,completed_at TEXT,outcome TEXT,"
        "command_summary TEXT)"
    )
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor,executor_surface,executor_version,"
        "machine_id,turn_posture,last_tool_call_at) "
        "VALUES (?,?,'codex','codex-cli',?,?,'waiting',NULL)",
        (SESSION_ID, PROJECT_ID, SESSION_VERSION, MACHINE_ID),
    )
    add_relay(
        conn,
        surface="codex-cli",
        version=INSTALLED_VERSION,
        connected_until="2026-09-04T00:00:00Z",
    )
    conn.commit()
    return conn


def observe_turn_end(
    conn,
    *,
    at: datetime = TURN_ENDED_AT,
    error_message: str = LIVE_ERROR,
    vendor_code: str = "other",
    event_id: str = "observed-1",
) -> None:
    """Record the turn-end observation the relay's record read produced."""
    conn.execute(
        "INSERT INTO events (event_id,event_name,session_id,envelope,created_at) "
        "VALUES (?,?,?,?,?)",
        (
            event_id,
            EVENT_SESSION_TURN_END_OBSERVED,
            SESSION_ID,
            json.dumps(
                {
                    "context": {
                        "observed_at": stamp(at),
                        "codex_error_info": vendor_code,
                        "error_message": error_message,
                    }
                }
            ),
            stamp(at),
        ),
    )
    conn.commit()


def record_resume(conn, *, at: datetime, event_id: str) -> None:
    conn.execute(
        "INSERT INTO events (event_id,event_name,session_id,envelope,created_at) "
        "VALUES (?,?,?,'{}',?)",
        (event_id, EVENT_SESSION_VENDOR_ERROR_RESUMED, SESSION_ID, stamp(at)),
    )
    conn.commit()


def states(conn, *, now: datetime):
    return vendor_error_states(
        conn,
        machine_id=MACHINE_ID,
        authorized_projects=(PROJECT_ID,),
        now=now,
    )


def one_state(conn, *, now: datetime) -> dict:
    found = states(conn, now=now)
    assert len(found) == 1, found
    return found[0]
