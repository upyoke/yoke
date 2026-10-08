"""The shared liveness projection and its activity-only routing half."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yoke_core.domain.session_staleness import (
    activity_liveness,
    session_liveness,
    stale_reclaim_candidate,
)

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
QUIET = "2026-10-01T00:00:00Z"
FRESH = "2026-10-08T11:59:00Z"


def _row(**fields):
    return {
        "executor": "claude-code",
        "last_heartbeat": QUIET,
        "last_tool_call_at": None,
        "mode": "wait",
        "holds_work_claim": False,
        **fields,
    }


@pytest.mark.parametrize(
    ("fields", "display", "routing"),
    [
        ({"mode": "parked", "holds_work_claim": True}, "waiting", "stale"),
        (
            {"mode": "parked", "holds_work_claim": True, "last_heartbeat": FRESH},
            "waiting",
            "active",
        ),
        ({"holds_work_claim": True}, "stale", "stale"),
        ({"mode": "parked"}, "stale", "stale"),
        ({"last_heartbeat": FRESH}, "active", "active"),
        ({"mode": "parked", "holds_work_claim": True, "ended_at": QUIET}, "ended", "ended"),
    ],
)
def test_display_liveness_overlays_waiting_on_activity(fields, display, routing):
    row = _row(**fields)
    assert session_liveness(row, now=NOW) == display
    assert activity_liveness(row, now=NOW) == routing


def test_a_read_without_the_claim_fact_refuses_rather_than_calling_it_stale():
    row = _row(mode="parked")
    del row["holds_work_claim"]
    with pytest.raises(KeyError, match="holds_work_claim"):
        session_liveness(row, now=NOW)


def test_only_a_claim_free_quiet_session_is_a_reclaim_candidate():
    assert stale_reclaim_candidate(QUIET, executor="claude-code", holds_work_claim=False)
    assert not stale_reclaim_candidate(
        QUIET, executor="claude-code", holds_work_claim=True
    )
