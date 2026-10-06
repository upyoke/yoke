"""Server-side authority guardrail coverage for ``POST /v1/hooks/evaluate``."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.test_api_hooks_evaluate_route import _request_body
from yoke_core.domain.work_claim_targets import make_item_target


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def _seed_recent_claim_denial_state(
    *,
    session_id: str,
    holder_session_id: str,
    item_id: int,
) -> None:
    from yoke_core.domain import db_helpers

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db_helpers.connect()
    try:
        # The guard resolves the command's public ref, so the item exists
        # (its project sequence equals its id in this fixture project).
        insert_item(conn, id=item_id, title="claim-guard item")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_tool_calls (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_use_id TEXT NOT NULL,
                tool_name TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                outcome TEXT,
                command_summary TEXT
            )
            """
        )
        conn.execute(
            """INSERT INTO session_tool_calls
               (id, session_id, tool_use_id, tool_name, started_at,
                completed_at, outcome, command_summary)
               VALUES (%s, %s, %s, 'Bash', %s, %s, 'denied', %s)""",
            (
                901,
                session_id,
                "claim-denied",
                now,
                now,
                (
                    "python3 -m yoke_core.api.service_client "
                    f"claim-work --item YOK-{item_id}"
                ),
            ),
        )
        conn.execute(
            """INSERT INTO work_claims
               (id, session_id, target_kind, scope, claim_type,
                claimed_at, last_heartbeat, released_at, release_reason)
               VALUES (%s, %s, 'item', %s, 'exclusive',
                       '2026-06-16T17:59:00Z', '2026-06-16T18:00:00Z',
                       NULL, NULL)""",
            (902, holder_session_id, make_item_target(item_id).scope_json()),
        )
        conn.commit()
    finally:
        conn.close()


def test_hooks_evaluate_runs_claim_ownership_guard_server_side(client) -> None:
    session_id = "server-claim-guard-client"
    holder = "server-claim-guard-holder"
    item_id = 42
    _seed_recent_claim_denial_state(
        session_id=session_id,
        holder_session_id=holder,
        item_id=item_id,
    )

    body = _request_body(
        event_name="PreToolUse",
        executor="claude",
        stdin=json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python3 -m yoke_core.cli.db_router "
                        f"items update YOK-{item_id} status implementing"
                    )
                },
                "cwd": "/client/repo",
                "session_id": session_id,
                "tool_use_id": "mutation-after-denial",
                "project_id": 1,
            }
        ),
    )

    response = client.post("/v1/hooks/evaluate", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["exit_code"] == 2
    assert payload["outcome"] == "denied"
    assert "claim-boundary bypass after live claim denial" in payload["stdout"]
    assert holder in payload["stdout"]
    assert (
        "yoke_core.domain.lint_claim_ownership_mutations" not in (payload["degraded"])
    )
    assert "yoke_core.domain.lint_workspace_cwd_match" not in payload["degraded"]


@pytest.mark.parametrize(
    "executor", ["claude-cli", "claude-desktop", "codex-cli", "cursor"]
)
@pytest.mark.parametrize(
    ("event_name", "posture"),
    [
        ("SessionStart", "unknown"),
        ("UserPromptSubmit", "running"),
        ("Stop", "waiting"),
        ("SessionEnd", "waiting"),
    ],
)
def test_lifecycle_uses_wire_project_without_server_checkout(
    client,
    monkeypatch,
    tmp_path,
    executor,
    event_name,
    posture,
) -> None:
    from yoke_core.domain import db_helpers
    from yoke_contracts import project_defaults
    from yoke_core.domain.schema_harness_session_columns import (
        apply_harness_session_columns,
    )

    with db_helpers.connect() as conn:
        apply_harness_session_columns(conn)

    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(project_defaults, "default_project_for_directory", lambda _: "")
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    session_id = f"explicit-project-{executor}-{event_name}"
    # Register through a tool hook before testing terminal events, which
    # observe existing sessions and intentionally cannot register one.
    assert (
        client.post(
            "/v1/hooks/evaluate",
            json=_request_body(
                executor=executor,
                stdin=json.dumps(
                    {
                        "session_id": session_id,
                        "cwd": "/client/repo",
                        "tool_name": "Read",
                        "tool_input": {},
                    }
                ),
            ),
        ).status_code
        == 200
    )
    response = client.post(
        "/v1/hooks/evaluate",
        json=_request_body(
            event_name=event_name,
            executor=executor,
            stdin=json.dumps({"session_id": session_id, "cwd": "/client/repo"}),
        ),
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "completed"
    with db_helpers.connect() as conn:
        row = conn.execute(
            "SELECT turn_posture FROM harness_sessions WHERE session_id=%s",
            (session_id,),
        ).fetchone()
        assert row["turn_posture"] == posture
        telemetry = conn.execute(
            "SELECT hook_event_name FROM events WHERE session_id=%s "
            "AND event_name='HookDispatchTelemetry'",
            (session_id,),
        ).fetchall()
        assert any(row["hook_event_name"] == event_name for row in telemetry)
        project = conn.execute("SELECT id FROM projects WHERE id=1").fetchone()["id"]
    assert (
        tmp_path
        / str(project)
        / "hook-markers"
        / f"dispatch-server-{event_name}-{session_id}"
    ).exists()


@pytest.mark.parametrize(
    "executor", ["claude-cli", "claude-desktop", "codex-cli", "cursor"]
)
@pytest.mark.parametrize(
    "event_name", ["SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"]
)
def test_missing_wire_project_never_reaches_remote_entry(
    client, monkeypatch, executor, event_name
):
    def unexpected_evaluation(**kwargs):
        pytest.fail("missing wire project must be refused before remote_entry")

    monkeypatch.setattr(
        "yoke_core.api.routes.hooks.evaluate_remote", unexpected_evaluation
    )
    response = client.post(
        "/v1/hooks/evaluate",
        json=_request_body(event_name=event_name, executor=executor, project_id=None),
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "denied"
    assert "no configured project id" in response.json()["stdout"]
