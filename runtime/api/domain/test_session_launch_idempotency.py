"""Launch replay distinguishes finished workers from live and pending launches."""

from dataclasses import replace

import pytest

from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    relay_connection,
)
from runtime.api.domain.test_session_launch_itemless import (
    _itemless_payload,
    _request,
    _wire_create,
)


def _launch():
    conn = relay_connection()
    add_relay(conn)
    request = LaunchRequest(
        project_id=10,
        executor_surface="codex-cli",
        instructions="Do the bounded task.",
        idempotency_key="same-launch",
    )
    first = create_launch(conn, auth=authorization(), request=request, now=NOW)
    return conn, request, first.launch


@pytest.mark.parametrize("end_column", ["ended_at", "terminated_at"])
@pytest.mark.parametrize("binding", ["registered_session_id", "native_session_id"])
def test_finished_session_replay_refuses_without_creating_worker(
    end_column,
    binding,
) -> None:
    conn, request, launch = _launch()
    conn.execute(
        f"INSERT INTO harness_sessions (session_id, project_id, {end_column}) "
        "VALUES ('worker', 10, ?)",
        (NOW,),
    )
    conn.execute(
        f"UPDATE session_launches SET state = 'succeeded', {binding} = 'worker' "
        "WHERE launch_id = ?",
        (launch.launch_id,),
    )
    conn.commit()

    with pytest.raises(SessionLaunchError) as raised:
        create_launch(conn, auth=authorization(), request=request, now=NOW)

    assert raised.value.code == "launch_replay_finished"
    message = str(raised.value)
    assert f"replay of finished launch {launch.launch_id}" in message
    assert "no new worker started" in message
    assert "new --idempotency-key" in message
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 1
    assert (
        conn.execute(
            "SELECT state FROM session_launches WHERE launch_id = ?",
            (launch.launch_id,),
        ).fetchone()[0]
        == "succeeded"
    )

    relaunched = create_launch(
        conn,
        auth=authorization(),
        request=replace(request, idempotency_key="new-launch"),
        now=NOW,
    )
    assert relaunched.launch.launch_id != launch.launch_id
    assert not relaunched.deduplicated


@pytest.mark.parametrize("state", ["assigned", "awaiting_registration", "succeeded"])
def test_pending_or_live_session_replays_existing_launch(state) -> None:
    conn, request, launch = _launch()
    if state == "succeeded":
        conn.execute(
            "INSERT INTO harness_sessions (session_id, project_id) VALUES ('worker', 10)"
        )
        conn.execute(
            "UPDATE session_launches SET state = 'succeeded', "
            "registered_session_id = 'worker' WHERE launch_id = ?",
            (launch.launch_id,),
        )
        conn.commit()
    elif state == "awaiting_registration":
        conn.execute(
            "UPDATE session_launches SET state = ?, native_session_id = 'native-worker' "
            "WHERE launch_id = ?",
            (state, launch.launch_id),
        )
        conn.commit()

    replay = create_launch(conn, auth=authorization(), request=request, now=NOW)

    assert replay.launch.launch_id == launch.launch_id
    assert replay.deduplicated
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 1


def test_finished_session_still_refuses_key_reused_for_changed_request() -> None:
    conn, request, launch = _launch()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, ended_at) "
        "VALUES ('gone', 10, ?)",
        (NOW,),
    )
    conn.execute(
        "UPDATE session_launches SET registered_session_id = 'gone' WHERE launch_id = ?",
        (launch.launch_id,),
    )
    conn.commit()

    with pytest.raises(SessionLaunchError) as raised:
        create_launch(
            conn,
            auth=authorization(),
            request=replace(request, instructions="Other work"),
            now=NOW,
        )

    assert raised.value.code == "idempotency_conflict"


def test_registered_create_returns_named_finished_replay_refusal(monkeypatch) -> None:
    conn = relay_connection()
    add_relay(conn)
    _wire_create(monkeypatch, conn)
    request = _request(_itemless_payload(key="finished-worker"))
    first = handlers.handle_launch_create(request)
    assert first.primary_success, first.error
    launch_id = first.result_payload["launch"]["launch_id"]
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, terminated_at) "
        "VALUES ('worker', 10, ?)",
        (NOW,),
    )
    conn.execute(
        "UPDATE session_launches SET state = 'succeeded', "
        "registered_session_id = 'worker' WHERE launch_id = ?",
        (launch_id,),
    )
    conn.commit()

    replay = handlers.handle_launch_create(request)

    assert not replay.primary_success
    assert replay.error.code == "launch_replay_finished"
    assert launch_id in replay.error.message
    assert "no new worker started" in replay.error.message
    assert "new --idempotency-key" in replay.error.message
