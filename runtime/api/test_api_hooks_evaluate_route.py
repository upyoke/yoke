"""Route test for ``POST /v1/hooks/evaluate`` (auth-gated)."""

from __future__ import annotations

import json
import os
import sys
import time
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def _request_body(**overrides) -> dict:
    body = {
        "hook_schema": 1,
        "event_name": "PreToolUse",
        "project_id": 1,
        "stdin": json.dumps({
            "tool_name": "Read",
            "tool_input": {"file_path": "/client/repo/file.py"},
            "cwd": "/client/repo",
            "session_id": "remote-hook-session",
            "project_id": 1,
        }),
        "executor": "claude",
        "agent_type": None,
        "deadline_ms": 2500,
    }
    body.update(overrides)
    return body


def test_hooks_evaluate_benign_event_allows(client) -> None:
    response = client.post("/v1/hooks/evaluate", json=_request_body())

    assert response.status_code == 200
    payload = response.json()
    assert payload["hook_schema"] == 1
    assert payload["exit_code"] == 0
    assert payload["stdout"] == ""
    assert payload["degraded"] == []
    assert payload["outcome"] == "completed"
    assert isinstance(payload["wait_ms"], int) and payload["wait_ms"] >= 0


def test_hooks_evaluate_honors_deadline_and_marks_degraded(
    client, monkeypatch,
) -> None:
    from runtime.harness.hook_runner import runner as runner_module
    from runtime.harness.hook_runner.types import HookDecision, Next, Outcome

    def slow_evaluate(context) -> HookDecision:  # pragma: no cover — times out
        time.sleep(2.0)
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)

    slow = types.ModuleType("remote_hook_route.fake_slow")
    slow.evaluate = slow_evaluate
    monkeypatch.setitem(sys.modules, "remote_hook_route.fake_slow", slow)
    monkeypatch.setattr(
        runner_module,
        "chain_for",
        lambda *a, **k: ["remote_hook_route.fake_slow", "remote_hook_route.fake_slow"],
    )

    started = time.monotonic()
    response = client.post(
        "/v1/hooks/evaluate", json=_request_body(deadline_ms=300),
    )
    elapsed_ms = (time.monotonic() - started) * 1000

    assert response.status_code == 200
    payload = response.json()
    assert payload["exit_code"] == 0
    assert "deadline_exhausted" in payload["degraded"]
    # The propagated 300ms budget governs, not the 2s the policy wanted.
    assert elapsed_ms < 1500


def test_hooks_evaluate_unsupported_schema_is_typed_400(client) -> None:
    response = client.post(
        "/v1/hooks/evaluate", json=_request_body(hook_schema=99),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_HOOK_SCHEMA"


def test_hooks_evaluate_requires_auth(client) -> None:
    response = client.post(
        "/v1/hooks/evaluate",
        json=_request_body(),
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401


def test_hooks_evaluate_registers_relayed_session_in_process(client, hooks_db) -> None:
    """Relayed tool-call hooks register unknown sessions server-side."""
    from yoke_core.domain import db_helpers

    session_id = "relayed-register-session"
    body = _request_body(
        executor="codex",
        stdin=json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "cwd": "/client/repo",
            "session_id": session_id,
            "project_id": 1,
        }),
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
    """Wire entrypoint/model metadata lands on relayed session rows."""
    from yoke_core.domain import db_helpers

    session_id = "wire-identity-register-session"
    # 1. Tool-call relay registers without model (no wire model on hot path).
    response = client.post("/v1/hooks/evaluate", json=_request_body(
        executor="claude",
        stdin=json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "cwd": "/client/repo",
            "session_id": session_id,
            "project_id": 1,
        }),
    ))
    assert response.status_code == 200

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT model, executor_display_name FROM harness_sessions "
            "WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert row is not None
        assert row["model"] == "unknown"

        # 2. UserPromptSubmit relay with wire model + entrypoint upgrades it.
        response2 = client.post("/v1/hooks/evaluate", json=_request_body(
            event_name="UserPromptSubmit",
            executor="claude",
            entrypoint="claude-desktop",
            model="claude-fable-5[1m]",
            stdin=json.dumps({
                "session_id": session_id,
                "transcript_path": "/client/t.jsonl",
                "prompt": "hello",
                "project_id": 1,
            }),
        ))
        assert response2.status_code == 200
        row = conn.execute(
            "SELECT model FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert row["model"] == "claude-fable-5[1m]", (
            "registration-class relay must upgrade the placeholder model"
        )

        # 3. A fresh session whose FIRST relay carries the wire identity
        #    registers with full metadata in one shot.
        fresh = "wire-identity-fresh-session"
        response3 = client.post("/v1/hooks/evaluate", json=_request_body(
            event_name="SessionStart",
            executor="claude",
            entrypoint="claude-desktop",
            model="claude-fable-5[1m]",
            stdin=json.dumps({
                "session_id": fresh,
                "transcript_path": "/client/t2.jsonl",
                "project_id": 1,
            }),
        ))
        assert response3.status_code == 200
        row = conn.execute(
            "SELECT model, executor_display_name FROM harness_sessions "
            "WHERE session_id = %s",
            (fresh,),
        ).fetchone()
        assert row is not None
        assert row["model"] == "claude-fable-5[1m]"
        assert "desktop" in (row["executor_display_name"] or ""), (
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
        stdin=json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "cwd": "/client/repo",
            "session_id": session_id,
            "project_id": 1,
        }),
    )
    assert client.post("/v1/hooks/evaluate", json=register).status_code == 200

    stop = _request_body(
        event_name="Stop",
        executor="claude",
        stdin=json.dumps({"cwd": "/client/repo", "session_id": session_id, "project_id": 1}),
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
        stdin=json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "cwd": "/client/repo",
            "session_id": stale_id,
            "project_id": 1,
        }),
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
        stdin=json.dumps({"cwd": "/client/repo", "session_id": "fresh-relay-session", "project_id": 1}),
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
