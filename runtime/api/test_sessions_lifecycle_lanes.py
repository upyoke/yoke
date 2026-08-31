"""Lane healing and lane stamping coverage for session registration."""

from __future__ import annotations

import pytest

from yoke_core.api.routing_config import load_routing_config
from yoke_core.api.service_client_sessions_lifecycle_begin import begin_session
from yoke_core.domain.sessions import SessionError, end_session
from runtime.api.test_sessions import _p, _register, conn  # noqa: F401
from yoke_contracts.session_model_facts import SessionModelFacts

_PROJECT_ROUTING = {
    "executor_default_lane_claude*": "DARIUS",
    "executor_default_lane_codex*": "ALTMAN",
}


def _stored_lane(connection, session_id: str) -> str:
    row = connection.execute(
        "SELECT execution_lane FROM harness_sessions WHERE session_id = "
        f"{_p(connection)}",
        (session_id,),
    ).fetchone()
    assert row is not None
    return row["execution_lane"]


class TestBeginSessionStampsRoutedLane:
    """The wrapper-begin entry path resolves the lane from project policy."""

    @pytest.fixture(autouse=True)
    def _project_routing(self, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.api.service_client_sessions_lifecycle_begin"
            "._load_routing_config",
            lambda **_kw: load_routing_config(
                "", project_settings=_PROJECT_ROUTING,
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
    def test_each_executor_surface_stamps_its_family_lane(
        self, conn, executor, expected,  # noqa: F811
    ):
        result = begin_session(
            conn,
            session_id=f"begin-{executor}",
            executor=executor,
            provider="anthropic",
            model_facts=SessionModelFacts(requested_model="test-model"),
            workspace="/tmp/work",
            project_id=1,
        )

        assert result["session"]["execution_lane"] == expected
        assert _stored_lane(conn, f"begin-{executor}") == expected


class TestRegisterSessionLaneHealing:
    def test_duplicate_upgrades_primary_lane_to_real_lane(self, conn):  # noqa: F811
        _register(conn, session_id="lane-upgrade")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="lane-upgrade", execution_lane="DARIUS")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_lane(conn, "lane-upgrade") == "DARIUS"

    def test_duplicate_never_downgrades_real_lane_to_primary(self, conn):  # noqa: F811
        _register(conn, session_id="lane-stable", execution_lane="ALTMAN")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="lane-stable", execution_lane="primary")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_lane(conn, "lane-stable") == "ALTMAN"

    def test_duplicate_never_swaps_real_lane_laterally(self, conn):  # noqa: F811
        _register(conn, session_id="lane-lateral", execution_lane="DARIUS")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="lane-lateral", execution_lane="ALTMAN")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_lane(conn, "lane-lateral") == "DARIUS"

    def test_reactivation_never_downgrades_real_lane_to_primary(self, conn):  # noqa: F811
        _register(conn, session_id="lane-reactivate", execution_lane="ALTMAN")
        end_session(conn, "lane-reactivate")

        result = _register(conn, session_id="lane-reactivate")

        assert result["execution_lane"] == "ALTMAN"
        assert _stored_lane(conn, "lane-reactivate") == "ALTMAN"

    def test_reactivation_upgrades_primary_lane_to_real_lane(self, conn):  # noqa: F811
        _register(conn, session_id="lane-reactivate-upgrade")
        end_session(conn, "lane-reactivate-upgrade")

        result = _register(
            conn,
            session_id="lane-reactivate-upgrade",
            execution_lane="DARIUS",
        )

        assert result["execution_lane"] == "DARIUS"
        assert _stored_lane(conn, "lane-reactivate-upgrade") == "DARIUS"
