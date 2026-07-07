"""Service-client lane-anchor coverage.

Exercises the CLI side of the fix: ``service_client
session-offer`` accepts ``--lane`` for backward compatibility but
never forwards the value into ``resolve_execution_lane``. The
authoritative lane is always the session row, and the regression
fixture replays the chain-step-2 conditions from session
``1776a63a-4aa0-43a8-bd0a-586d3e48484d``.
"""

from __future__ import annotations

import json
import os

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
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
        "WHERE event_name = 'SessionOfferLaneOverrideIgnored' "
        "AND session_id = %s",
        (session_id,),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def _post_decision_lane(db_path: str, session_id: str) -> str | None:
    """Read the actual_lane recorded by emit_post_decision_telemetry."""
    conn = connect_test_db(db_path)
    row = conn.execute(
        "SELECT envelope FROM events "
        "WHERE event_name = 'NextActionChosen' AND session_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        ctx = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    # NextActionChosen envelope nests the routing context under different
    # keys across emitters; check the common ones.
    return (
        ctx.get("actual_lane")
        or ctx.get("execution_lane")
        or ctx.get("offer", {}).get("execution_lane")
    )


class TestCallerSuppliedLaneIsIgnored:
    """AC-4: --lane is accepted but never wins over the session row."""

    def test_caller_primary_against_darius_row_emits_warning(self, session_offer_db):
        sid = "lane-anchor-warning"
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
                "--executor", "claude-code",
                "--provider", "anthropic",
                "--model", "claude-opus-4-7",
                "--workspace", session_offer_db["tmp_dir"],
                "--lane", "primary",
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert _lane_override_event_count(session_offer_db["db_path"], sid) == 1

    def test_caller_default_sentinel_does_not_warn(self, session_offer_db):
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
                "--executor", "claude-code",
                "--provider", "anthropic",
                "--model", "claude-opus-4-7",
                "--workspace", session_offer_db["tmp_dir"],
                "--lane", "default",
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert _lane_override_event_count(session_offer_db["db_path"], sid) == 0

    def test_no_lane_argument_does_not_warn(self, session_offer_db):
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
                "--executor", "claude-code",
                "--provider", "anthropic",
                "--model", "claude-opus-4-7",
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert _lane_override_event_count(session_offer_db["db_path"], sid) == 0


class TestRegressionDariusPrimaryNoPolish:
    """AC-5 regression replay of session 1776a63a chain-step-2."""

    def _config_with_lane_policy(self, db_dir: str) -> None:
        config_path = os.path.join(db_dir, "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write(
                "executor_default_lane_claude*=DARIUS\n"
                "lane_paths_darius=shepherd,advance,conduct,usher\n"
                "lane_paths_altman=refine,polish\n"
            )

    def test_darius_session_primary_lane_offer_persists_row_lane(
        self, session_offer_db
    ):
        """AC-5 regression: replay the chain-step-2 setup.

        The original failure mode persisted ``execution_lane=primary``
        on the offer envelope because resolve_execution_lane let the
        caller value win. Afterwards, the envelope must persist
        the row value (DARIUS) regardless of what the caller passed.
        """
        sid = "regression-1776a63a"
        _pre_register_session(
            session_offer_db["db_path"],
            sid,
            executor="claude-code",
            workspace=session_offer_db["tmp_dir"],
        )
        self._config_with_lane_policy(os.path.dirname(session_offer_db["db_path"]))
        _set_row_lane(session_offer_db["db_path"], sid, "DARIUS")

        result = _run_client(
            [
                "session-offer",
                "--executor", "claude-code",
                "--provider", "anthropic",
                "--model", "claude-opus-4-7",
                "--workspace", session_offer_db["tmp_dir"],
                "--lane", "primary",
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Read the persisted offer envelope from the test DB.
        conn = connect_test_db(session_offer_db["db_path"])
        envelope_blob = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()[0]
        conn.close()
        envelope = json.loads(envelope_blob)
        # AC-5: envelope must record DARIUS (the row), not the caller's
        # 'primary' override. Previously, this asserted 'primary'.
        assert envelope["execution_lane"] == "DARIUS"


class TestSessionOfferCarriesRowLaneToDecisionEngine:
    """AC-15: the SessionOffer fed into decide_next_action carries the row lane."""

    def test_offer_envelope_persisted_with_row_lane(self, session_offer_db):
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
                "--executor", "claude-code",
                "--provider", "anthropic",
                "--model", "claude-opus-4-7",
                "--workspace", session_offer_db["tmp_dir"],
                "--lane", "primary",
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()
        envelope = json.loads(row[0])
        assert envelope["execution_lane"] == "DARIUS"
