"""A reactivation records the process that drove it, in stored rows.

Attribution has to survive the absence of a wake attempt. The stamp used to
ride on an open ``session_message_attempts`` evidence row and return early
when there was none — exactly the case with nothing else to fall back on, and
exactly the case a live investigation could not answer for one of four revived
sessions. The reactivation now stamps its own ``HarnessSessionStarted``
context, so the question "which process reactivated session X, and what hook
event drove it" is answerable from stored rows for EVERY reactivation.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.test_constants import TEST_MODEL_ID
from runtime.api.test_sessions import (
    _connect_with_backend_setup,
    _create_schema,
)
from yoke_contracts.hook_driver_process import DRIVER_PAYLOAD_KEY
from yoke_core.domain import db_backend, events_crud
from yoke_core.domain.sessions_lifecycle_registry import register_session
from yoke_core.domain.sessions_reactivation_driver import (
    build_reactivation_driver_stamp,
)
from yoke_core.hooks import telemetry


SESSION_ID = "sess-reactivation-driver"

# The dispatch tail's resolved driving process: a relayed client's own pids,
# not the evaluating server's, plus the hook event that actually ran.
DRIVER = {"pid": 90210, "ppid": 431, "hook_event": "PreToolUse", "origin": "client"}


def _apply_schema() -> None:
    """Session schema plus a REAL events universe on one disposable database.

    Hand-rolled events DDL is how this suite first went green while proving
    nothing: ``emit_event`` is best-effort, so a missing ``severity_config``
    or registry table degrades into silence rather than an error, and the
    assertions below would read an empty table. ``events_crud.cmd_init`` builds
    the schema the emitter actually targets, so a missing row here means the
    stamp is missing, not the fixture.
    """
    conn = db_backend.connect()
    try:
        _create_schema(conn)
        conn.commit()
    finally:
        conn.close()
    events_crud.cmd_init()


@pytest.fixture
def conn(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_schema):
        c = _connect_with_backend_setup(tmp_path)
        try:
            yield c
        finally:
            c.close()


def _register(conn, **kwargs):
    return register_session(
        conn,
        session_id=SESSION_ID,
        executor="claude-code",
        provider="anthropic",
        model=TEST_MODEL_ID,
        workspace="/tmp/work",
        project_id=1,
        entrypoint="claude-cli",
        **kwargs,
    )


def _end_session(conn) -> None:
    conn.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        ("2026-08-28T12:00:00Z", SESSION_ID),
    )
    conn.commit()


def _started_contexts(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT envelope FROM events WHERE session_id = %s "
        "AND event_name = %s ORDER BY id",
        (SESSION_ID, "HarnessSessionStarted"),
    ).fetchall()
    return [json.loads(row["envelope"])["context"] for row in rows]


def test_reactivation_with_no_wake_attempt_still_names_its_driver(conn) -> None:
    """The case the wake-attempt-only stamp dropped on the floor."""
    _register(conn)
    _end_session(conn)

    _register(conn, driver=DRIVER)

    # No wake attempt was ever opened for this session — the reactivation is
    # the only thing that could have recorded the driver, and it did.
    context = _started_contexts(conn)[-1]
    assert context["driver_pid"] == 90210
    assert context["driver_ppid"] == 431
    assert context["driver_hook_event"] == "PreToolUse"
    assert context["driver_surface"] == "claude-cli"


def test_fresh_registration_carries_no_driver_stamp(conn) -> None:
    """A first registration's driver IS its registered surface; no stamp."""
    _register(conn, driver=DRIVER)

    context = _started_contexts(conn)[-1]
    assert "driver_pid" not in context
    assert "driver_hook_event" not in context


def test_reactivation_without_driver_facts_still_stamps_the_surface(conn) -> None:
    """A registration path carrying no hook dispatch degrades, never fails."""
    _register(conn)
    _end_session(conn)

    _register(conn)

    context = _started_contexts(conn)[-1]
    assert context["driver_surface"] == "claude-cli"
    assert "driver_pid" not in context


def test_wake_attempt_evidence_and_event_context_agree(conn) -> None:
    """Both records are built from one dict — they cannot drift apart."""
    stamp = build_reactivation_driver_stamp(
        driver_surface="claude-cli",
        driver_version="2.1.251",
        driver=DRIVER,
    )
    assert stamp == {
        "driver_surface": "claude-cli",
        "driver_version": "2.1.251",
        "driver_pid": 90210,
        "driver_ppid": 431,
        "driver_hook_event": "PreToolUse",
        "driver_pid_origin": "client",
    }


def test_driver_facts_are_validated_not_trusted() -> None:
    """Wire-carried values are data: a bad pid is dropped, not stored."""
    stamp = build_reactivation_driver_stamp(
        driver_surface="claude-cli",
        driver_version=None,
        driver={"pid": "not-a-pid", "ppid": -1, "hook_event": "   "},
    )
    assert stamp == {"driver_surface": "claude-cli"}


def test_dispatch_tail_revival_records_driver_and_telemetry(conn) -> None:
    """End to end: one hook dispatch revives an ended session and says who did.

    This is the whole chain in one call — the tail's ensure-register on the
    flush's own shared connection, the reactivation it drives, the driver
    stamp, and the ``HookDispatchTelemetry`` row that names the same process.
    Both records have to survive the connection closing, so this also proves
    the batched flush commits.
    """
    _register(conn)
    _end_session(conn)

    payload = {
        "cwd": "/tmp/work",
        "entrypoint": "claude-cli",
        "model": TEST_MODEL_ID,
        "project_id": 1,
        DRIVER_PAYLOAD_KEY: DRIVER,
    }
    telemetry.flush_hook_telemetry(
        [
            (
                "dispatch",
                {
                    "hook_event": "PreToolUse",
                    "executor": "claude",
                    "chain_length": 3,
                    "decision_outcome": "allow",
                    "session_id": SESSION_ID,
                    "item_id": None,
                    "tool_name": "Bash",
                    "duration_ms": 11,
                    "extra": {"driver_pid": DRIVER["pid"]},
                },
            )
        ],
        ensure_session=(
            SESSION_ID,
            json.dumps(payload),
            "",  # transcript_path
            False,  # record_anchor — the process tree is not under test
            "claude-code",  # executor_hint
            True,  # register_in_process
            False,  # force_reregister
            None,  # actor_id
            1,  # project_id
        ),
    )

    revived = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
        (SESSION_ID,),
    ).fetchone()
    assert revived["ended_at"] is None, "the dispatch tail did not revive the row"

    context = _started_contexts(conn)[-1]
    assert context["driver_pid"] == DRIVER["pid"]
    assert context["driver_hook_event"] == "PreToolUse"

    telemetry_row = conn.execute(
        "SELECT envelope FROM events WHERE session_id = %s AND event_name = %s",
        (SESSION_ID, "HookDispatchTelemetry"),
    ).fetchone()
    assert telemetry_row is not None, "the dispatch row was rolled back at close"
    assert json.loads(telemetry_row["envelope"])["context"]["driver_pid"] == DRIVER["pid"]
