"""Server-side authority guardrail coverage for ``POST /v1/hooks/evaluate``."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from runtime.api.test_api_hooks_evaluate_route import _request_body


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def _seed_recent_claim_denial_state(
    *, session_id: str, holder_session_id: str, item_id: int,
) -> None:
    from yoke_core.domain import db_helpers

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db_helpers.connect()
    try:
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
               (id, session_id, target_kind, item_id, claim_type,
                claimed_at, last_heartbeat, released_at, release_reason)
               VALUES (%s, %s, 'item', %s, 'exclusive',
                       '2026-06-16T17:59:00Z', '2026-06-16T18:00:00Z',
                       NULL, NULL)""",
            (902, holder_session_id, item_id),
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
        stdin=json.dumps({
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "python3 -m yoke_core.cli.db_router "
                    f"items update {item_id} status implementing"
                )
            },
            "cwd": "/client/repo",
            "session_id": session_id,
            "tool_use_id": "mutation-after-denial",
            "project_id": 1,
        }),
    )

    response = client.post("/v1/hooks/evaluate", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["exit_code"] == 2
    assert payload["outcome"] == "denied"
    assert "claim-boundary bypass after live claim denial" in payload["stdout"]
    assert holder in payload["stdout"]
    assert "yoke_core.domain.lint_claim_ownership_mutations" not in (
        payload["degraded"]
    )
    assert "yoke_core.domain.lint_workspace_cwd_match" in payload["degraded"]
