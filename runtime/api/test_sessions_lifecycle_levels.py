"""Level healing and level stamping coverage for session registration."""

from __future__ import annotations

import pytest

from yoke_core.api.routing_config import load_routing_config
from yoke_core.api.service_client_sessions_lifecycle_begin import begin_session
from yoke_core.domain.sessions import SessionError, end_session
from runtime.api.test_sessions import _p, _register, conn  # noqa: F401
from yoke_contracts.session_model_facts import SessionModelFacts

_PROJECT_ROUTING = {
    "executor_default_level_claude*": "DARIUS",
    "executor_default_level_codex*": "ALTMAN",
}


def _stored_level(connection, session_id: str) -> str:
    row = connection.execute(
        "SELECT execution_level FROM harness_sessions WHERE session_id = "
        f"{_p(connection)}",
        (session_id,),
    ).fetchone()
    assert row is not None
    return row["execution_level"]


class TestBeginSessionStampsRoutedLevel:
    """The wrapper-begin entry path resolves the level from project policy."""

    @pytest.fixture(autouse=True)
    def _project_routing(self, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.api.service_client_sessions_lifecycle_begin"
            "._load_routing_config",
            lambda **_kw: load_routing_config(
                "",
                project_settings=_PROJECT_ROUTING,
            ),
        )

    @pytest.mark.parametrize(
        "executor,expected",
        [
            ("claude-desktop", "DARIUS"),
            ("claude-code", "DARIUS"),
            ("codex-desktop", "ALTMAN"),
            ("codex", "ALTMAN"),
        ],
    )
    def test_each_executor_surface_stamps_its_family_level(
        self,
        conn,  # noqa: F811
        executor,
        expected,  # noqa: F811
    ):
        result = begin_session(
            conn,  # noqa: F811
            session_id=f"begin-{executor}",
            executor=executor,
            provider="anthropic",
            model_facts=SessionModelFacts(requested_model="test-model"),
            workspace="/tmp/work",
            project_id=1,
        )

        assert result["session"]["execution_level"] == expected
        assert _stored_level(conn, f"begin-{executor}") == expected


class TestRegisterSessionLevelHealing:
    def test_duplicate_upgrades_primary_level_to_real_level(self, conn):  # noqa: F811
        _register(conn, session_id="level-upgrade")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="level-upgrade", execution_level="DARIUS")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_level(conn, "level-upgrade") == "DARIUS"

    def test_duplicate_never_downgrades_real_level_to_primary(self, conn):  # noqa: F811
        _register(conn, session_id="level-stable", execution_level="ALTMAN")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="level-stable", execution_level="primary")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_level(conn, "level-stable") == "ALTMAN"

    def test_duplicate_never_swaps_real_level_laterally(self, conn):  # noqa: F811
        _register(conn, session_id="level-lateral", execution_level="DARIUS")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="level-lateral", execution_level="ALTMAN")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_level(conn, "level-lateral") == "DARIUS"

    def test_reactivation_never_downgrades_real_level_to_primary(self, conn):  # noqa: F811
        _register(conn, session_id="level-reactivate", execution_level="ALTMAN")
        end_session(conn, "level-reactivate")

        result = _register(conn, session_id="level-reactivate")

        assert result["execution_level"] == "ALTMAN"
        assert _stored_level(conn, "level-reactivate") == "ALTMAN"

    def test_reactivation_upgrades_primary_level_to_real_level(self, conn):  # noqa: F811
        _register(conn, session_id="level-reactivate-upgrade")
        end_session(conn, "level-reactivate-upgrade")

        result = _register(
            conn,  # noqa: F811
            session_id="level-reactivate-upgrade",
            execution_level="DARIUS",
        )

        assert result["execution_level"] == "DARIUS"
        assert _stored_level(conn, "level-reactivate-upgrade") == "DARIUS"


_MODEL_ROUTING = {
    "executor_default_levels": {"claude*": "DARIUS", "codex*": "ALTMAN"},
    "level_metadata": {"DARIUS": {}, "ALTMAN": {}, "MUSKY": {}},
    "level_rules": [
        {"model": "claude-opus-*", "level": "MUSKY"},
        {"harness": "codex", "model": "gpt-5", "level": "MUSKY"},
    ],
}


class TestBeginSessionRoutesOnModel:
    """A selector routes the session that is registering, not its harness."""

    @pytest.fixture(autouse=True)
    def _project_routing(self, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.api.service_client_sessions_lifecycle_begin"
            "._load_routing_config",
            lambda **_kw: load_routing_config(
                "",
                project_settings=_MODEL_ROUTING,
            ),
        )

    @pytest.mark.parametrize(
        "session_id,executor,facts,expected",
        [
            (
                "model-served",
                "claude-cli",
                SessionModelFacts(model="claude-opus-5"),
                "MUSKY",
            ),
            (
                "model-asked",
                "claude-cli",
                SessionModelFacts(requested_model="claude-opus-5[1m]"),
                "MUSKY",
            ),
            (
                "model-other",
                "claude-cli",
                SessionModelFacts(model="claude-sonnet-5"),
                "DARIUS",
            ),
            (
                "model-none",
                "claude-cli",
                SessionModelFacts(),
                "DARIUS",
            ),
            (
                "model-combined",
                "codex-cli",
                SessionModelFacts(model="gpt-5"),
                "MUSKY",
            ),
        ],
    )
    def test_the_registering_session_lands_on_its_selector_level(
        self,
        conn,  # noqa: F811
        session_id,
        executor,
        facts,
        expected,  # noqa: F811
    ):
        result = begin_session(
            conn,  # noqa: F811
            session_id=session_id,
            executor=executor,
            provider="anthropic",
            model_facts=facts,
            workspace="/tmp/work",
            project_id=1,
        )

        assert result["session"]["execution_level"] == expected
        assert _stored_level(conn, session_id) == expected

    def test_a_routing_change_leaves_an_already_stamped_session_alone(
        self,
        conn,  # noqa: F811
        monkeypatch,  # noqa: F811
    ):
        # Level is stamped once, at registration. Rewriting a live session's
        # level would move work away from a session already running it.
        begin_session(
            conn,  # noqa: F811
            session_id="stamped-before-change",
            executor="claude-cli",
            provider="anthropic",
            model_facts=SessionModelFacts(model="claude-sonnet-5"),
            workspace="/tmp/work",
            project_id=1,
        )
        assert _stored_level(conn, "stamped-before-change") == "DARIUS"

        monkeypatch.setattr(
            "yoke_core.api.service_client_sessions_lifecycle_begin"
            "._load_routing_config",
            lambda **_kw: load_routing_config(
                "",
                project_settings={
                    **_MODEL_ROUTING,
                    "level_rules": [
                        {"model": "claude-sonnet-*", "level": "ALTMAN"},
                    ],
                },
            ),
        )
        begin_session(
            conn,  # noqa: F811
            session_id="stamped-after-change",
            executor="claude-cli",
            provider="anthropic",
            model_facts=SessionModelFacts(model="claude-sonnet-5"),
            workspace="/tmp/work",
            project_id=1,
        )

        assert _stored_level(conn, "stamped-before-change") == "DARIUS"
        assert _stored_level(conn, "stamped-after-change") == "ALTMAN"
