"""Relayed hook identity repairs active sessions after late resolution."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import db_helpers
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


def _stored_pair(session_id: str) -> tuple[str | None, str | None]:
    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT executor_surface, executor_version FROM harness_sessions "
            "WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert row is not None
        return row["executor_surface"], row["executor_version"]
    finally:
        conn.close()


def test_second_hook_backfills_codex_surface_and_version(
    client,
    hooks_db,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.hooks.helpers.detect_entrypoint",
        lambda: None,
    )
    session_id = "late-codex-surface-session"
    stdin = json.dumps(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "/client/repo/file.py"},
            "cwd": "/client/repo",
            "session_id": session_id,
            "project_id": 1,
        }
    )

    first = client.post(
        "/v1/hooks/evaluate",
        json=_request_body(executor="codex", stdin=stdin),
    )
    assert first.status_code == 200
    assert _stored_pair(session_id) == (None, None)

    second = client.post(
        "/v1/hooks/evaluate",
        json=_request_body(
            executor="codex",
            entrypoint="codex-cli",
            executor_version="0.150.0",
            stdin=stdin,
        ),
    )
    assert second.status_code == 200
    assert _stored_pair(session_id) == ("codex-cli", "0.150.0")
