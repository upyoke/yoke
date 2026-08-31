"""Service-client lane-override coverage.

``service_client session-offer --lane`` forwards the value as a caller
override. The session-row lane is the default when ``--lane`` is omitted
or is the documented ``default`` sentinel.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (  # noqa: F401
    _pre_register_session,
    session_offer_db,
)


def _set_row_lane(db_path: str, session_id: str, lane: str) -> None:
    """Override the session row's execution_lane after session-begin."""
    conn = connect_test_db(db_path)
    conn.execute(
        "UPDATE harness_sessions SET execution_lane = %s WHERE session_id = %s",
        (lane, session_id),
    )
    conn.commit()
    conn.close()


def _lane_override_event_count(db_path: str, session_id: str) -> int:
    conn = connect_test_db(db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE event_name = 'SessionOfferLaneOverrideApplied' "
        "AND session_id = %s",
        (session_id,),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def _envelope_lane(db_path: str, session_id: str) -> str | None:
    conn = connect_test_db(db_path)
    row = conn.execute(
        "SELECT offer_envelope FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0]).get("execution_lane")
    except json.JSONDecodeError:
        return None


class TestCallerSuppliedLaneOverridesRow:
    """--lane wins over the session row when the caller supplies it."""

    def test_caller_primary_against_darius_row_emits_applied(
        self, session_offer_db, monkeypatch  # noqa: F811
    ):
        monkeypatch.delenv("YOKE_EVENTS_ISOLATION", raising=False)
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        sid = "lane-anchor-applied"
        _pre_register_session(
            session_offer_db["db_path"],
            sid,
            executor="claude-code",
            workspace=session_offer_db["tmp_dir"],
        )
        _set_row_lane(session_offer_db["db_path"], sid, "DARIUS")

        result = _run_client(
            [
                "session-offer",
                "--lane",
                "primary",
                "--session-id",
                sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert _lane_override_event_count(session_offer_db["db_path"], sid) == 1
        assert _envelope_lane(session_offer_db["db_path"], sid) == "primary"

    def test_caller_default_sentinel_does_not_override(self, session_offer_db):  # noqa: F811
        sid = "lane-anchor-default"
        _pre_register_session(
            session_offer_db["db_path"],
            sid,
            executor="claude-code",
            workspace=session_offer_db["tmp_dir"],
        )
        _set_row_lane(session_offer_db["db_path"], sid, "DARIUS")

        result = _run_client(
            [
                "session-offer",
                "--lane",
                "default",
                "--session-id",
                sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert _lane_override_event_count(session_offer_db["db_path"], sid) == 0
        assert _envelope_lane(session_offer_db["db_path"], sid) == "DARIUS"

    def test_no_lane_argument_uses_row(self, session_offer_db):  # noqa: F811
        sid = "lane-anchor-none"
        _pre_register_session(
            session_offer_db["db_path"],
            sid,
            executor="claude-code",
            workspace=session_offer_db["tmp_dir"],
        )
        _set_row_lane(session_offer_db["db_path"], sid, "DARIUS")

        result = _run_client(
            [
                "session-offer",
                "--session-id",
                sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert _lane_override_event_count(session_offer_db["db_path"], sid) == 0
        assert _envelope_lane(session_offer_db["db_path"], sid) == "DARIUS"


class TestSessionOfferCarriesResolvedLaneToDecisionEngine:
    """The SessionOffer fed into decide_next_action carries the resolved lane."""

    def test_offer_envelope_persists_row_lane_when_omitted(self, session_offer_db):  # noqa: F811
        sid = "carry-row-lane"
        _pre_register_session(
            session_offer_db["db_path"],
            sid,
            executor="claude-code",
            workspace=session_offer_db["tmp_dir"],
        )
        _set_row_lane(session_offer_db["db_path"], sid, "DARIUS")
        _run_client(
            [
                "session-offer",
                "--session-id",
                sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert _envelope_lane(session_offer_db["db_path"], sid) == "DARIUS"
