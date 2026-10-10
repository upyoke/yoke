"""Level stamping and level healing across the session-registration paths.

The wrapper ``begin_session``, the in-process hook registrar, and the
``POST /v1/sessions`` route each stamp the level the registering session's
harness, model, and effort match in the levels its project reads.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from yoke_contracts.session_level import UNRESOLVED_EXECUTION_LEVEL
from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.api.main import app
from yoke_core.api.service_client_sessions_lifecycle_begin import begin_session
from yoke_core.domain.sessions import SessionError, end_session
from yoke_core.hooks.registration_in_process import _register_in_process
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.level_store import (
    levels_doc,
    option,
    store_project_levels,
    store_universe_levels,
)
from runtime.api.sessions_api_test_support import session_test_db  # noqa: F401
from runtime.api.test_sessions import _p, _register, conn  # noqa: F401

_PROJECT_ID = 1
_OPUS = "claude-opus-5-5"
_UNIVERSE_DOC = levels_doc(("UNIVERSE_ONLY", [option("claude-cli", _OPUS, "medium")]))
_PROJECT_DOC = levels_doc(("PROJECT_ONLY", [option("claude-cli", _OPUS, "medium")]))


def _sid(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:8]}"


def _stored_level(connection, session_id: str) -> str:
    row = connection.execute(
        "SELECT execution_level FROM harness_sessions WHERE session_id = "
        f"{_p(connection)}",
        (session_id,),
    ).fetchone()
    assert row is not None
    return row["execution_level"] if hasattr(row, "keys") else row[0]


def _begin(connection, executor: str, facts: SessionModelFacts) -> str:
    session_id = _sid("begin")
    result = begin_session(
        connection,
        session_id=session_id,
        executor=executor,
        provider="test-provider",
        model_facts=facts,
        workspace="/tmp/work",
        project_id=_PROJECT_ID,
    )
    assert result["session"]["execution_level"] == _stored_level(connection, session_id)
    return result["session"]["execution_level"]


class TestBeginSessionStampsLevel:
    """The wrapper-begin path resolves the level from the level stores."""

    @pytest.mark.parametrize(
        "executor,facts,expected",
        [
            ("claude-code", SessionModelFacts(model=_OPUS), "SENIOR"),
            (
                "claude-desktop",
                SessionModelFacts(requested_model=f"{_OPUS}[1m]"),
                "SENIOR",
            ),
            (
                "codex-desktop",
                SessionModelFacts(model="gpt-6-luna", reasoning_effort="max"),
                "INTERN",
            ),
            (
                "claude-cli",
                SessionModelFacts(model="claude-haiku-5-5", reasoning_effort="max"),
                "INTERN",
            ),
            ("claude-code", SessionModelFacts(model="claude-unlisted"), "primary"),
            ("claude-code", SessionModelFacts(), "primary"),
        ],
    )
    def test_shipped_options_label_when_nothing_is_stored(
        self,
        conn,  # noqa: F811
        executor,
        facts,
        expected,
    ):
        assert _begin(conn, executor, facts) == expected

    def test_stored_universe_definition_changes_the_stamp(self, conn):  # noqa: F811
        store_universe_levels(conn, _UNIVERSE_DOC)
        assert _begin(conn, "claude-code", SessionModelFacts(model=_OPUS)) == (
            "UNIVERSE_ONLY"
        )

    def test_project_override_wins_over_the_universe(self, conn):  # noqa: F811
        store_universe_levels(conn, _UNIVERSE_DOC)
        store_project_levels(conn, _PROJECT_ID, _PROJECT_DOC)
        assert _begin(conn, "claude-code", SessionModelFacts(model=_OPUS)) == (
            "PROJECT_ONLY"
        )

    def test_a_level_change_leaves_an_already_stamped_session_alone(
        self,
        conn,  # noqa: F811
    ):
        # Level is stamped once, at registration. Rewriting a live session's
        # level would move work away from a session already running it.
        facts = SessionModelFacts(model=_OPUS)
        before = _sid("before")
        begin_session(
            conn,
            session_id=before,
            executor="claude-code",
            provider="test-provider",
            model_facts=facts,
            workspace="/tmp/work",
            project_id=_PROJECT_ID,
        )
        store_universe_levels(conn, _UNIVERSE_DOC)

        assert _begin(conn, "claude-code", facts) == "UNIVERSE_ONLY"
        assert _stored_level(conn, before) == "SENIOR"


class TestInProcessRegistrationStampsLevel:
    def _register(self, connection, *, model, level=None) -> str:
        session_id = _sid("in-process")
        error = _register_in_process(
            session_id,
            "claude-code",
            "test-provider",
            SessionModelFacts(requested_model=model),
            "/tmp/work",
            None,
            execution_level=level,
            project_id=_PROJECT_ID,
        )
        assert error == ""
        return _stored_level(connection, session_id)

    def test_shipped_options_label_the_session(self, conn):  # noqa: F811
        assert self._register(conn, model=f"{_OPUS}[1m]") == "SENIOR"

    def test_project_override_labels_the_session(self, conn):  # noqa: F811
        store_universe_levels(conn, _UNIVERSE_DOC)
        store_project_levels(conn, _PROJECT_ID, _PROJECT_DOC)
        assert self._register(conn, model=_OPUS) == "PROJECT_ONLY"

    def test_explicit_level_wins(self, conn):  # noqa: F811
        assert self._register(conn, model=_OPUS, level="CHOSEN") == "CHOSEN"

    def test_unmatched_model_stays_unresolved(self, conn):  # noqa: F811
        assert self._register(conn, model="claude-unlisted") == (
            UNRESOLVED_EXECUTION_LEVEL
        )


class TestRegisterRouteStampsLevel:
    @pytest.fixture(autouse=True)
    def _client(self, session_test_db):  # noqa: F811
        self.client = TestClient(app)
        self.client.headers.update(session_test_db["auth_headers"])
        self.db_path = session_test_db["db_path"]

    def _post(self, **body) -> str:
        session_id = _sid("route")
        payload = {
            "session_id": session_id,
            "executor": "claude-code",
            "provider": "test-provider",
            "workspace": "/tmp/work",
            "project_id": _PROJECT_ID,
            **body,
        }
        resp = self.client.post("/v1/sessions", json=payload)
        assert resp.status_code == 201, resp.text
        connection = connect_test_db(self.db_path)
        try:
            return _stored_level(connection, session_id)
        finally:
            connection.close()

    def _store(self, writer, *args) -> None:
        connection = connect_test_db(self.db_path)
        try:
            writer(connection, *args)
        finally:
            connection.close()

    def test_shipped_options_label_the_session(self):
        assert self._post(requested_model=f"{_OPUS}[1m]") == "SENIOR"

    def test_stored_universe_definition_changes_the_stamp(self):
        self._store(store_universe_levels, _UNIVERSE_DOC)
        assert self._post(model=_OPUS) == "UNIVERSE_ONLY"

    def test_project_override_wins_over_the_universe(self):
        self._store(store_universe_levels, _UNIVERSE_DOC)
        self._store(store_project_levels, _PROJECT_ID, _PROJECT_DOC)
        assert self._post(model=_OPUS) == "PROJECT_ONLY"

    def test_explicit_level_wins(self):
        assert self._post(model=_OPUS, execution_level="CHOSEN") == "CHOSEN"

    def test_unmatched_model_stays_unresolved(self):
        assert self._post(model="claude-unlisted") == UNRESOLVED_EXECUTION_LEVEL


class TestRegisterSessionLevelHealing:
    def test_duplicate_upgrades_primary_level_to_real_level(self, conn):  # noqa: F811
        _register(conn, session_id="level-upgrade")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="level-upgrade", execution_level="SENIOR")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_level(conn, "level-upgrade") == "SENIOR"

    def test_duplicate_never_downgrades_real_level_to_primary(self, conn):  # noqa: F811
        _register(conn, session_id="level-stable", execution_level="INTERN")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="level-stable", execution_level="primary")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_level(conn, "level-stable") == "INTERN"

    def test_duplicate_never_swaps_real_level_laterally(self, conn):  # noqa: F811
        _register(conn, session_id="level-lateral", execution_level="SENIOR")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="level-lateral", execution_level="INTERN")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_level(conn, "level-lateral") == "SENIOR"

    def test_reactivation_never_downgrades_real_level_to_primary(self, conn):  # noqa: F811
        _register(conn, session_id="level-reactivate", execution_level="INTERN")
        end_session(conn, "level-reactivate")

        result = _register(conn, session_id="level-reactivate")

        assert result["execution_level"] == "INTERN"
        assert _stored_level(conn, "level-reactivate") == "INTERN"

    def test_reactivation_upgrades_primary_level_to_real_level(self, conn):  # noqa: F811
        _register(conn, session_id="level-reactivate-upgrade")
        end_session(conn, "level-reactivate-upgrade")

        result = _register(
            conn,
            session_id="level-reactivate-upgrade",
            execution_level="SENIOR",
        )

        assert result["execution_level"] == "SENIOR"
        assert _stored_level(conn, "level-reactivate-upgrade") == "SENIOR"
