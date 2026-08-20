"""Coverage for the ``sessions.identity`` read-back handler.

Identity is resolved once at registration and read back here. The handler
must return the stored row verbatim — never a locally derived substitute —
and must refuse rather than invent when the authority has no row.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.sessions_identity import handle_identity
from yoke_core.domain.sessions_identity_read import (
    SessionIdentity,
    resolve_session_identity,
)


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _request(session_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.identity",
        actor=ActorContext(actor_id=None, session_id=session_id),
        target=TargetRef(kind="global"),
        payload={},
    )


def _insert_session(
    conn,
    session_id: str,
    *,
    executor: str = "claude-code",
    executor_display_name: str | None = "claude-desktop",
    provider: str = "anthropic",
    model: str = "claude-opus-5",
    lane: str = "DARIUS",
    workspace: str = "/tmp/workspace",
    project_id: int | None = 1,
    ended_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, executor_display_name, provider, model, "
        "execution_lane, workspace, project_id, mode, offered_at, "
        "last_heartbeat, ended_at"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            executor,
            executor_display_name,
            provider,
            model,
            lane,
            workspace,
            project_id,
            "wait",
            _iso(),
            _iso(),
            ended_at,
        ),
    )
    conn.commit()


class TestResolveSessionIdentity:
    def test_projects_the_stored_row(self, test_db):
        _insert_session(test_db, "identity-stored")
        identity = resolve_session_identity(test_db, "identity-stored")
        assert isinstance(identity, SessionIdentity)
        assert identity.executor == "claude-code"
        assert identity.executor_display_name == "claude-desktop"
        assert identity.provider == "anthropic"
        assert identity.model == "claude-opus-5"
        assert identity.execution_lane == "DARIUS"
        assert identity.workspace == "/tmp/workspace"
        assert identity.project_id == 1
        assert identity.ended_at is None

    def test_missing_row_raises_with_recovery(self, test_db):
        from yoke_core.domain.sessions import SessionError

        with pytest.raises(SessionError) as caught:
            resolve_session_identity(test_db, "identity-absent")
        assert caught.value.code == "NO_SESSION"
        # The refusal must point at registration, never at a local guess.
        assert "hook" in caught.value.message.lower()


class TestHandleIdentity:
    def test_returns_stored_identity_not_a_local_guess(self, test_db, monkeypatch):
        _insert_session(
            test_db,
            "identity-handler",
            executor="cursor",
            executor_display_name="cursor-desktop",
            provider="cursor",
            model="composer-1",
            lane="MUSKY",
        )
        monkeypatch.setattr(
            "yoke_core.domain.handlers.sessions_identity._connect_rw",
            lambda: _NonClosing(test_db),
        )
        outcome = handle_identity(_request("identity-handler"))
        assert outcome.error is None
        payload = outcome.result_payload
        assert payload["session_id"] == "identity-handler"
        assert payload["executor"] == "cursor"
        assert payload["executor_display_name"] == "cursor-desktop"
        assert payload["provider"] == "cursor"
        assert payload["model"] == "composer-1"
        assert payload["execution_lane"] == "MUSKY"
        assert payload["workspace"] == "/tmp/workspace"
        assert isinstance(payload["lane_allowed_paths"], list)
        assert isinstance(payload["max_chain_steps"], int)

    def test_no_session_id_is_refused(self):
        outcome = handle_identity(_request(""))
        assert outcome.error is not None
        assert outcome.error.code == "session_required"

    def test_unregistered_session_is_refused_not_invented(
        self, test_db, monkeypatch,
    ):
        monkeypatch.setattr(
            "yoke_core.domain.handlers.sessions_identity._connect_rw",
            lambda: _NonClosing(test_db),
        )
        outcome = handle_identity(_request("identity-unregistered"))
        assert outcome.error is not None
        assert outcome.error.code == "no_session"

    def test_ended_session_is_refused_with_recovery(self, test_db, monkeypatch):
        _insert_session(test_db, "identity-ended", ended_at=_iso())
        monkeypatch.setattr(
            "yoke_core.domain.handlers.sessions_identity._connect_rw",
            lambda: _NonClosing(test_db),
        )
        outcome = handle_identity(_request("identity-ended"))
        assert outcome.error is not None
        assert outcome.error.code == "session_ended"


class _NonClosing:
    """Hand the handler the fixture connection without letting it close it."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *_exc):
        return False
