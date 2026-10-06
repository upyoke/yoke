"""api hooks session registration regression coverage."""

# ruff: noqa: F401
from __future__ import annotations

import json
import os
import sys
import time
import types
import pytest
from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)

from runtime.api.test_api_hooks_evaluate_route import (
    _request_body,
    client as client,
    hooks_db as hooks_db,
    pytestmark,
)


def test_hooks_evaluate_registers_relayed_session_in_process(client, hooks_db) -> None:
    """Relayed tool-call hooks register unknown sessions server-side."""
    from yoke_core.domain import db_helpers

    session_id = "relayed-register-session"
    body = _request_body(
        executor="codex",
        stdin=json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "true"},
                "cwd": "/client/repo",
                "session_id": session_id,
                "project_id": 1,
            }
        ),
    )

    response = client.post("/v1/hooks/evaluate", json=body)
    assert response.status_code == 200

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT session_id, executor, workspace FROM harness_sessions "
            "WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert row is not None, "relayed session must be registered server-side"
        assert row["executor"] == "codex", "request executor must be honored"
        assert row["workspace"] == "/client/repo"

        response2 = client.post("/v1/hooks/evaluate", json=body)
        assert response2.status_code == 200
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert int(count["n"]) == 1, "repeat relays must stay idempotent"
    finally:
        conn.close()


def test_hooks_evaluate_wire_identity_registers_full_metadata(client, hooks_db) -> None:
    """Wire entrypoint/model metadata lands on relayed session rows.

    A tier selector such as ``[1m]`` can only ever be a request — no
    provider response returns one — so it rides the wire as
    ``requested_model`` and lands in the requested column, leaving the
    served column unattested.
    """
    from yoke_core.domain import db_helpers

    session_id = "wire-identity-register-session"
    # 1. Tool-call relay registers with nothing attested and nothing asked
    #    (the hot path carries no wire model facts).
    response = client.post(
        "/v1/hooks/evaluate",
        json=_request_body(
            executor="claude",
            stdin=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "true"},
                    "cwd": "/client/repo",
                    "session_id": session_id,
                    "project_id": 1,
                }
            ),
        ),
    )
    assert response.status_code == 200

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT model, executor_surface FROM harness_sessions "
            "WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert row is not None
        assert row["model"] is None

        # 2. UserPromptSubmit relay with wire facts + entrypoint fills them.
        response2 = client.post(
            "/v1/hooks/evaluate",
            json=_request_body(
                event_name="UserPromptSubmit",
                executor="claude",
                entrypoint="claude-desktop",
                requested_model="claude-fable-5[1m]",
                stdin=json.dumps(
                    {
                        "session_id": session_id,
                        "transcript_path": "/client/t.jsonl",
                        "prompt": "hello",
                        "project_id": 1,
                    }
                ),
            ),
        )
        assert response2.status_code == 200
        row = conn.execute(
            "SELECT requested_model FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert row["requested_model"] == "claude-fable-5[1m]", (
            "registration-class relay must fill the stated request"
        )

        # 3. A fresh session whose FIRST relay carries the wire identity
        #    registers with full metadata in one shot.
        fresh = "wire-identity-fresh-session"
        response3 = client.post(
            "/v1/hooks/evaluate",
            json=_request_body(
                event_name="SessionStart",
                executor="claude",
                entrypoint="claude-desktop",
                requested_model="claude-fable-5[1m]",
                stdin=json.dumps(
                    {
                        "session_id": fresh,
                        "transcript_path": "/client/t2.jsonl",
                        "project_id": 1,
                    }
                ),
            ),
        )
        assert response3.status_code == 200
        row = conn.execute(
            "SELECT requested_model, executor_surface FROM harness_sessions "
            "WHERE session_id = %s",
            (fresh,),
        ).fetchone()
        assert row is not None
        assert row["requested_model"] == "claude-fable-5[1m]"
        assert "desktop" in (row["executor_surface"] or ""), (
            "wire entrypoint must drive the display name"
        )
    finally:
        conn.close()


def test_hooks_evaluate_stop_ends_claimless_relayed_session(client, hooks_db) -> None:
    """Remote lifecycle tail ends claimless relayed sessions server-side."""
    from yoke_core.domain import db_helpers

    session_id = "relayed-stop-end-session"
    register = _request_body(
        executor="claude",
        stdin=json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "true"},
                "cwd": "/client/repo",
                "session_id": session_id,
                "project_id": 1,
            }
        ),
    )
    assert client.post("/v1/hooks/evaluate", json=register).status_code == 200

    stop = _request_body(
        event_name="Stop",
        executor="claude",
        stdin=json.dumps(
            {"cwd": "/client/repo", "session_id": session_id, "project_id": 1}
        ),
    )
    response = client.post("/v1/hooks/evaluate", json=stop)
    assert response.status_code == 200

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert row is not None
        assert row["ended_at"] is not None, (
            "relayed Stop must end a claimless session server-side"
        )
    finally:
        conn.close()


def test_hooks_evaluate_session_start_reaps_stale_actives(client, hooks_db) -> None:
    """The stale-session sweep has no automatic caller on https-default
    machines; relayed SessionStart runs it server-side so abandoned active
    rows (heartbeat + activity stale) get ended."""
    from yoke_core.domain import db_helpers
    from runtime.api.sessions_api_stale_test_helpers import (
        EVENTS_TABLE_FOR_STALE_DETECTION,
        apply_ddl_statements,
    )

    conn = db_helpers.connect()
    try:
        apply_ddl_statements(conn, EVENTS_TABLE_FOR_STALE_DETECTION)
        conn.commit()
    finally:
        conn.close()

    stale_id = "stale-active-session"
    register = _request_body(
        executor="claude",
        stdin=json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "true"},
                "cwd": "/client/repo",
                "session_id": stale_id,
                "project_id": 1,
            }
        ),
    )
    assert client.post("/v1/hooks/evaluate", json=register).status_code == 200

    conn = db_helpers.connect()
    try:
        # Backdate the session AND its registration-era events so both the
        # heartbeat and the activity signal read stale.
        conn.execute(
            "UPDATE harness_sessions SET offered_at = NOW() - INTERVAL '2 hours', "
            "last_heartbeat = NOW() - INTERVAL '2 hours' WHERE session_id = %s",
            (stale_id,),
        )
        conn.execute(
            "UPDATE events SET created_at = "
            "to_char(NOW() - INTERVAL '2 hours', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') "
            "WHERE session_id = %s",
            (stale_id,),
        )
        conn.commit()
    finally:
        conn.close()

    start = _request_body(
        event_name="SessionStart",
        executor="claude",
        stdin=json.dumps(
            {
                "cwd": "/client/repo",
                "session_id": "fresh-relay-session",
                "project_id": 1,
            }
        ),
    )
    assert client.post("/v1/hooks/evaluate", json=start).status_code == 200

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
            (stale_id,),
        ).fetchone()
        assert row is not None
        assert row["ended_at"] is not None, (
            "relayed SessionStart must reap stale active sessions"
        )
    finally:
        conn.close()


def test_hooks_evaluate_cursor_session_start_registers_workspace_root(
    client, hooks_db
) -> None:
    """Cursor's sessionStart carries ``workspace_roots`` and no ``cwd``.

    The relay binds a Cursor launch to its native by workspace, so the
    registered row must carry the workspace Cursor opened.
    """
    from yoke_core.domain import db_helpers

    session_id = "relayed-cursor-workspace-session"
    body = _request_body(
        executor="cursor",
        event_name="SessionStart",
        stdin=json.dumps(
            {
                "hook_event_name": "sessionStart",
                "session_id": session_id,
                "conversation_id": session_id,
                "identity_stamped": True,
                "workspace_roots": ["/client/repo"],
                "project_id": 1,
            }
        ),
    )

    response = client.post("/v1/hooks/evaluate", json=body)
    assert response.status_code == 200
    assert response.json()["outcome"] == "completed", response.json()["stdout"]

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT workspace FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "cursor session must be registered server-side"
    assert row["workspace"] == "/client/repo"
