"""Only a persisted Yoke launch may authorize a native session resume."""

from importlib import import_module
import sqlite3

import pytest

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.session_control.capabilities import (
    SESSION_SURFACE_CAPABILITIES,
    native_wake_supported,
)
from yoke_core.domain.session_launch_origin import session_launch_origin
from yoke_core.domain.session_relay_launch_context import session_was_relay_launched
from yoke_core.domain.session_message_routing import messageability
from yoke_core.domain.session_message_wake_skip import _wake_skip_result
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.release_wait_wake import session_wake
from runtime.api.domain.session_message_support_test_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    record_process_gone,
)
from runtime.api.domain.session_desktop_operator_wake_test_support import (
    STARVED,
    _send_to,
    _operator_notices,
)


@pytest.mark.parametrize("surface", SESSION_SURFACE_CAPABILITIES)
@pytest.mark.parametrize("origin", ["operator", "yoke"])
def test_every_surface_requires_yoke_origin(surface, origin):
    capability = SESSION_SURFACE_CAPABILITIES[surface]
    row = {
        "executor_surface": surface,
        "executor_version": capability.minimum_version,
        "launch_origin": origin,
    }
    routing = messageability(row, liveness="ended", force_stopped_route=True)
    expected_native = origin == "yoke" and capability.wake_authority == "native"
    assert native_wake_supported(surface, origin) is expected_native
    assert routing["wake_authority"] == ("native" if expected_native else "operator")
    if not expected_native:
        assert routing["wake_interface"] == "none"
        assert _wake_skip_result(row, "message_stopped", {}) == (
            "skipped_operation",
            None,
            "operator",
        )
        assert session_wake(row)["kind"] == "operator"
    elif surface.endswith("-cli"):
        assert routing["wake_interface"] != "none"
        assert session_wake(row)["kind"] == "native"


@pytest.mark.parametrize("surface", ["claude-cli", "codex-cli", "cursor-cli"])
def test_operator_cli_with_observed_dead_process_keeps_hook_delivery(surface):
    conn = message_connection()
    capability = SESSION_SURFACE_CAPABILITIES[surface]
    conn.execute(
        "UPDATE harness_sessions SET launch_origin='operator',executor_surface=?,"
        "executor_version=?,executor=?,last_heartbeat=?,last_tool_call_at=? "
        "WHERE session_id='s4'",
        (
            surface,
            capability.minimum_version,
            canonical_harness_id(surface),
            NOW_TEXT,
            NOW_TEXT,
        ),
    )
    message_id = _send_to(conn, "s4")
    record_process_gone(conn, when=NOW)
    eligible = wake_eligible_recipients(
        conn,
        now=STARVED,
    )
    assert not eligible
    receipt = conn.execute(
        "SELECT state,wake_attempt_count FROM session_message_recipients "
        "WHERE message_id=? AND session_id='s4'",
        (message_id,),
    ).fetchone()
    assert tuple(receipt) == ("pending", 0)
    assert _operator_notices(conn)


def test_missing_origin_never_grants_native_authority():
    routing = messageability(
        {"executor_surface": "codex-cli", "executor_version": "0.161.0"},
        liveness="ended",
    )
    assert routing["wake_interface"] == "none"
    assert routing["wake_authority"] == "operator"


def test_backfill_matches_registered_and_native_identities_and_survives_retention():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE harness_sessions(session_id TEXT PRIMARY KEY, native_thread_id TEXT);
        CREATE TABLE session_launches(registered_session_id TEXT, native_session_id TEXT);
        INSERT INTO harness_sessions VALUES
            ('registered',NULL),('native',NULL),('folded','thread'),('manual',NULL);
        INSERT INTO session_launches VALUES
            ('registered',NULL),(NULL,'native'),(NULL,'thread');
    """)
    migration = import_module("yoke_core.domain.migrations.0104_session_launch_origin")
    migration.apply(conn)
    migration.invariants(conn)
    assert dict(
        conn.execute("SELECT session_id,launch_origin FROM harness_sessions")
    ) == {
        "registered": "yoke",
        "native": "yoke",
        "folded": "yoke",
        "manual": "operator",
    }
    migration.apply(conn)
    conn.execute("DELETE FROM session_launches")
    assert session_launch_origin(conn, "folded") == "yoke"
    assert session_was_relay_launched(conn, "registered")
    assert not session_was_relay_launched(conn, "manual")
    conn.execute("INSERT INTO harness_sessions(session_id) VALUES ('unbound')")
    assert session_launch_origin(conn, "unbound") == "operator"
    assert session_launch_origin(conn, "unknown") == "operator"
