# ruff: noqa: F401, F811
"""A parked holder keeps its claim through the reclaim paths.

Both reclaim surfaces — the item-scoped sweep session-offer runs, and the
race-safe reclaim a competing acquisition performs — read the same
``claim_holder_staleness`` predicate, so a session that parked on purpose is
never released out from under its own wait. An ended park is not a wait, and
is still reclaimed.
"""

from __future__ import annotations

from runtime.api.sessions_api_stale_test_helpers import (
    _ago_minutes,
    conn,  # noqa: F401  (backend-aware pytest fixture)
)
from runtime.api.test_sessions_reclaim_item_claims import (
    _capture_session_events,
    _claim_row,
    _seed_holder,
    conn_with_events,  # noqa: F401  (pytest fixture)
)
from yoke_core.domain.claim_holder_staleness import REASON_PARKED_HOLDER


def _park(conn, session_id: str) -> None:
    conn.execute(
        "UPDATE harness_sessions SET mode = 'parked', quiet_reason = %s "
        "WHERE session_id = %s",
        ("awaiting delivery", session_id),
    )
    conn.commit()


class TestParkedHolderKeepsItsClaim:
    def test_offer_sweep_leaves_a_parked_holder_alone(
        self, conn_with_events, monkeypatch
    ):
        c = conn_with_events
        captured = _capture_session_events(monkeypatch)
        _seed_holder(
            c,
            holder_session_id="parked-holder",
            item_id=5201,
            holder_heartbeat_ago_min=240,
            claim_heartbeat_ago_min=240,
        )
        _park(c, "parked-holder")

        from yoke_core.domain.sessions import reclaim_stale_item_claims

        assert reclaim_stale_item_claims(c, "5201", stale_threshold_minutes=10) == 0
        assert _claim_row(c, "parked-holder", 5201)["released_at"] is None
        aborts = [e for e in captured if e["event_name"] == "ReclaimAborted"]
        assert aborts and aborts[-1]["context"]["abort_reason"] == REASON_PARKED_HOLDER

    def test_offer_sweep_reclaims_an_ended_parked_holder(self, conn_with_events):
        c = conn_with_events
        _seed_holder(
            c,
            holder_session_id="parked-ended-holder",
            item_id=5202,
            holder_heartbeat_ago_min=240,
            claim_heartbeat_ago_min=240,
        )
        _park(c, "parked-ended-holder")
        c.execute(
            "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
            (_ago_minutes(30), "parked-ended-holder"),
        )
        c.commit()

        from yoke_core.domain.sessions import reclaim_stale_item_claims

        assert reclaim_stale_item_claims(c, "5202", stale_threshold_minutes=10) == 1
        assert _claim_row(c, "parked-ended-holder", 5202)["released_at"] is not None

    def test_offer_sweep_reclaims_a_parked_holder_whose_native_died(
        self, conn_with_events
    ):
        c = conn_with_events
        _seed_holder(
            c,
            holder_session_id="parked-crashed-holder",
            item_id=5203,
            holder_heartbeat_ago_min=240,
            claim_heartbeat_ago_min=240,
        )
        _park(c, "parked-crashed-holder")
        # The death has to be the latest thing known about the session:
        # activity after it would prove a replacement process took over.
        c.execute(
            "UPDATE harness_sessions SET native_process_gone_at = %s, "
            "native_process_gone_evidence = %s, episode_started_at = %s "
            "WHERE session_id = %s",
            (
                _ago_minutes(60),
                '{"pids": [9001], "exit_code": 137}',
                _ago_minutes(240),
                "parked-crashed-holder",
            ),
        )
        c.commit()

        from yoke_core.domain.sessions import reclaim_stale_item_claims

        assert reclaim_stale_item_claims(c, "5203", stale_threshold_minutes=10) == 1
        assert _claim_row(c, "parked-crashed-holder", 5203)["released_at"] is not None
