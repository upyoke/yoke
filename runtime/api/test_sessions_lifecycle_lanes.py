"""Lane healing coverage for session registration."""

from __future__ import annotations

import pytest

from yoke_core.domain.sessions import SessionError, end_session
from runtime.api.test_sessions import _p, _register, conn  # noqa: F401


def _stored_lane(conn, session_id: str) -> str:
    row = conn.execute(
        f"SELECT execution_lane FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    assert row is not None
    return row["execution_lane"]


class TestRegisterSessionLaneHealing:
    def test_duplicate_upgrades_primary_lane_to_real_lane(self, conn):
        _register(conn, session_id="lane-upgrade")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="lane-upgrade", execution_lane="DARIUS")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_lane(conn, "lane-upgrade") == "DARIUS"

    def test_duplicate_never_downgrades_real_lane_to_primary(self, conn):
        _register(conn, session_id="lane-stable", execution_lane="ALTMAN")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="lane-stable", execution_lane="primary")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_lane(conn, "lane-stable") == "ALTMAN"

    def test_duplicate_never_swaps_real_lane_laterally(self, conn):
        _register(conn, session_id="lane-lateral", execution_lane="DARIUS")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="lane-lateral", execution_lane="ALTMAN")

        assert exc_info.value.code == "SESSION_EXISTS"
        assert _stored_lane(conn, "lane-lateral") == "DARIUS"

    def test_reactivation_never_downgrades_real_lane_to_primary(self, conn):
        _register(conn, session_id="lane-reactivate", execution_lane="ALTMAN")
        end_session(conn, "lane-reactivate")

        result = _register(conn, session_id="lane-reactivate")

        assert result["execution_lane"] == "ALTMAN"
        assert _stored_lane(conn, "lane-reactivate") == "ALTMAN"

    def test_reactivation_upgrades_primary_lane_to_real_lane(self, conn):
        _register(conn, session_id="lane-reactivate-upgrade")
        end_session(conn, "lane-reactivate-upgrade")

        result = _register(
            conn,
            session_id="lane-reactivate-upgrade",
            execution_lane="DARIUS",
        )

        assert result["execution_lane"] == "DARIUS"
        assert _stored_lane(conn, "lane-reactivate-upgrade") == "DARIUS"
