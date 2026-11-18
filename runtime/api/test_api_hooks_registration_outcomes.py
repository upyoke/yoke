"""Authoritative registration persists prompts and exposes fail-open refusals."""

from __future__ import annotations

import json
import uuid

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture
from runtime.api.api_hooks_evaluate_route_test_support import _request_body
from yoke_core.domain import db_helpers
from yoke_core.domain.sessions_analytics import SessionError


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()

@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def _read(session_id):
    conn = db_helpers.connect()
    try:
        return conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id = %s", (session_id,)
        ).fetchone()
    finally:
        conn.close()


def _opening(client, executor, event, sid):
    body = _request_body(
        executor=executor,
        stdin=json.dumps(
            {
                "session_id": sid,
                "cwd": "/client/repo",
                "project_id": 1,
                "transcript_path": "/client/saved.jsonl",
                "prompt": str(uuid.uuid4()),
            }
        ),
    )
    body["event_name"] = event
    response = client.post("/v1/hooks/evaluate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_prompt_stamp_does_not_depend_on_client_marker(client, executor):
    sid = f"prompt-{executor}"
    start = _opening(client, executor, "SessionStart", sid)
    assert start["registration_outcome"] == "registered"
    assert _read(sid)["first_user_prompt_at"] is None
    # The server delegates orientation to the client; it must persist the
    # prompt even when that client already consumed its first-prompt marker.
    prompt = _opening(client, executor, "UserPromptSubmit", sid)
    assert prompt["registration_outcome"] == "exists"
    first = _read(sid)["first_user_prompt_at"]
    assert first is not None
    assert (
        _opening(client, executor, "UserPromptSubmit", sid)["registration_outcome"]
        == "exists"
    )
    assert _read(sid)["first_user_prompt_at"] == first


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize(
    "code", ["SESSION_INSERT_REFUSED", "ACTOR_REQUIRED", "SESSION_ORG_UNRESOLVED"]
)
def test_refusals_keep_hook_allowed_and_emit_named_event(
    client, monkeypatch, executor, code
):
    from yoke_core.domain import sessions_lifecycle_registry

    def refuse(*a, **kw):
        raise SessionError(code, "named cause; repair registration and retry")

    monkeypatch.setattr(sessions_lifecycle_registry, "register_session", refuse)
    sid = f"refused-{executor}-{code}"
    response = _opening(client, executor, "SessionStart", sid)
    assert response["exit_code"] == 0
    assert response["outcome"] == "completed"
    assert response["registration_outcome"] == f"refused:{code}"
    assert f"session_registration_refused:{code}" in response["degraded"]
    assert _read(sid) is None
    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT envelope FROM events WHERE event_name = %s AND session_id = %s",
            ("SessionRegistrationRefused", sid),
        ).fetchone()
        assert row is not None
        context = row["envelope"]
        if isinstance(context, str):
            context = json.loads(context)
        assert context["context"]["code"] == code
    finally:
        conn.close()


def test_real_insert_constraint_is_not_reported_as_duplicate(client):
    conn = db_helpers.connect()
    try:
        conn.execute(
            "ALTER TABLE harness_sessions ADD CONSTRAINT refused_registration CHECK (session_id <> 'invalid-insert')"
        )
        conn.commit()
    finally:
        conn.close()
    result = _opening(client, "codex", "SessionStart", "invalid-insert")
    assert result["exit_code"] == 0
    assert result["registration_outcome"] == "refused:SESSION_INSERT_REFUSED"
    assert _read("invalid-insert") is None
    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT envelope FROM events WHERE event_name = 'SessionRegistrationRefused' AND session_id = 'invalid-insert'"
        ).fetchone()
        assert row is not None
        assert "refused_registration" in row["envelope"]
    finally:
        conn.close()


def test_failed_prompt_stamp_refuses_then_retries_identical_prompt(client):
    sid = "prompt-retry"
    _opening(client, "codex", "SessionStart", sid)
    conn = db_helpers.connect()
    try:
        conn.execute("ALTER TABLE harness_sessions DROP COLUMN first_user_prompt_at")
        conn.commit()
    finally:
        conn.close()
    body = _request_body(
        executor="codex",
        event_name="UserPromptSubmit",
        stdin=json.dumps(
            {
                "session_id": sid,
                "cwd": "/client/repo",
                "project_id": 1,
                "transcript_path": "/client/saved.jsonl",
                "prompt": "Reply ok",
            }
        ),
    )
    failed = client.post("/v1/hooks/evaluate", json=body).json()
    assert failed["exit_code"] == 0
    assert failed["registration_outcome"] == "refused:SESSION_PROMPT_STAMP_REFUSED"
    conn = db_helpers.connect()
    try:
        conn.execute(
            "ALTER TABLE harness_sessions ADD COLUMN first_user_prompt_at TIMESTAMPTZ"
        )
        conn.commit()
    finally:
        conn.close()
    retried = client.post("/v1/hooks/evaluate", json=body).json()
    assert retried["registration_outcome"] == "exists"
    assert _read(sid)["first_user_prompt_at"] is not None


def test_codex_prompt_proves_conversation_before_transcript_is_saved(client):
    body = _request_body(
        executor="codex",
        event_name="SessionStart",
        stdin=json.dumps(
            {
                "session_id": "unsaved-conversation",
                "cwd": "/client/repo",
                "project_id": 1,
            }
        ),
    )
    start = client.post("/v1/hooks/evaluate", json=body).json()
    assert start["registration_outcome"] == "skipped:unsaved_transcript"
    assert _read("unsaved-conversation") is None
    body["event_name"] = "UserPromptSubmit"
    prompt = client.post("/v1/hooks/evaluate", json=body).json()
    assert prompt["registration_outcome"] == "registered"
    assert _read("unsaved-conversation")["first_user_prompt_at"] is not None


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit"])
def test_retired_project_refuses_registration_by_name(client, executor, event):
    """The reachable public-surface refusal: a retired project's checkout."""
    conn = db_helpers.connect()
    try:
        # The shared fixture predates retirement; served schemas carry it.
        conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS retired_at TIMESTAMPTZ")
        conn.execute("UPDATE projects SET retired_at = now() WHERE id = 1")
        conn.commit()
    finally:
        conn.close()
    sid = f"retired-{executor}-{event}"
    result = _opening(client, executor, event, sid)
    assert result["exit_code"] == 0
    assert result["outcome"] == "completed"
    assert result["registration_outcome"] == "refused:SESSION_PROJECT_RETIRED"
    assert "session_registration_refused:SESSION_PROJECT_RETIRED" in result["degraded"]
    assert _read(sid) is None
    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT envelope FROM events WHERE event_name = %s AND session_id = %s",
            ("SessionRegistrationRefused", sid),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    envelope = row["envelope"]
    envelope = json.loads(envelope) if isinstance(envelope, str) else envelope
    assert envelope["context"]["code"] == "SESSION_PROJECT_RETIRED"
    assert "unretire" in envelope["context"]["reason"]
