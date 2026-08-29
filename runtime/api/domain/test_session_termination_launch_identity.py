"""Finding a terminated session's launch through either identity column."""

from __future__ import annotations

import pytest

from runtime.api.test_sessions import _register
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.session_termination import terminate_session


pytest_plugins = ("runtime.api.test_sessions",)

NOW = "2026-08-26T12:00:00Z"
MACHINE_ID = "11111111-1111-4111-8111-111111111111"
LAUNCH_ID = "44444444-4444-4444-8444-444444444444"
WORKER = "worker"


@pytest.fixture(autouse=True)
def _termination_schema(conn, monkeypatch):
    create_session_control_tables(conn)
    conn.execute(
        "INSERT INTO actors (id,kind,created_at) VALUES (41,'human',%s),(42,'human',%s)",
        (NOW, NOW),
    )
    conn.commit()
    monkeypatch.setattr(
        "yoke_core.domain.session_termination.emit_session_terminated",
        lambda session_id, context: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end.emit_release_claims_branch_event",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end._sa._emit_session_event",
        lambda *args, **kwargs: None,
    )


def _register_pair(conn) -> None:
    _register(conn, session_id="operator", actor_id=41, mode="operator")
    _register(conn, session_id=WORKER, actor_id=42, machine_id=MACHINE_ID)


def _insert_launch(conn, *, native_session_id, registered_session_id) -> None:
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,sender_session_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES "
        "('launch-message',41,'operator','go','sha256:body','{}',%s,"
        "'2026-08-27T12:00:00Z')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id,requester_actor_id,project_id,requested_surface,"
        "selected_surface,message_id,state,assigned_machine_id,"
        "native_session_id,registered_session_id,deadline_at,created_at) VALUES "
        "(%s,41,1,'claude-cli','claude-cli','launch-message','outcome_unknown',"
        "%s,%s,%s,'2026-08-27T12:00:00Z',%s)",
        (
            LAUNCH_ID,
            MACHINE_ID,
            native_session_id,
            registered_session_id,
            NOW,
        ),
    )
    conn.commit()


def _reap_launch_id(conn) -> str | None:
    return conn.execute(
        "SELECT launch_id FROM session_termination_reaps "
        "WHERE target_session_id=%s",
        (WORKER,),
    ).fetchone()["launch_id"]


def _terminate(conn) -> None:
    terminate_session(
        conn,
        target_session_id=WORKER,
        actor_id=41,
        caller_session_id="operator",
        reason="worker completed",
    )


def test_the_reap_finds_a_launch_that_only_registered_the_session(conn) -> None:
    _register_pair(conn)
    _insert_launch(conn, native_session_id=None, registered_session_id=WORKER)

    _terminate(conn)

    assert _reap_launch_id(conn) == LAUNCH_ID


def test_the_reap_finds_a_launch_that_only_named_the_native(conn) -> None:
    """Registration can fail while the native the launch started still runs.

    The custody handle the reap needs is filed under the launch id, so
    losing the launch here leaves that process with nothing to kill it.
    """
    _register_pair(conn)
    _insert_launch(conn, native_session_id=WORKER, registered_session_id=None)

    _terminate(conn)

    assert _reap_launch_id(conn) == LAUNCH_ID


def test_a_session_no_launch_created_carries_no_launch_into_its_reap(conn) -> None:
    _register_pair(conn)
    _insert_launch(
        conn,
        native_session_id="a-different-session",
        registered_session_id=None,
    )

    _terminate(conn)

    assert _reap_launch_id(conn) is None
