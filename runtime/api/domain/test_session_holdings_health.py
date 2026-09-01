"""Current-holdings health: fleet-report thresholds, one closed tone."""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_core.domain.session_holdings_health import (
    HOLDINGS_HEALTH_GREEN,
    HOLDINGS_HEALTH_ORANGE,
    HOLDINGS_HEALTH_RED,
    HOLDINGS_HEALTH_YELLOW,
    classify_current_holdings_health,
)


STAFFING = 5 * 60
IDLE = 20 * 60


def _classify(**overrides):
    payload = {
        "parked": False,
        "idle_seconds": 0,
        "staffing_after_seconds": STAFFING,
        "idle_after_seconds": IDLE,
        "stale_eligible": False,
        "item_blocked": False,
        "landed_open": False,
        "qa_failed": False,
    }
    payload.update(overrides)
    return classify_current_holdings_health(**payload)


def test_recent_unflagged_holder_is_green() -> None:
    assert _classify(idle_seconds=30) == HOLDINGS_HEALTH_GREEN


def test_quiet_past_staffing_below_idle_is_yellow() -> None:
    assert _classify(idle_seconds=STAFFING) == HOLDINGS_HEALTH_YELLOW
    assert _classify(idle_seconds=IDLE - 1) == HOLDINGS_HEALTH_YELLOW


def test_idle_alarm_or_blocked_item_is_orange() -> None:
    assert _classify(idle_seconds=IDLE) == HOLDINGS_HEALTH_ORANGE
    assert _classify(idle_seconds=10, item_blocked=True) == HOLDINGS_HEALTH_ORANGE


def test_act_now_flags_are_red() -> None:
    assert _classify(stale_eligible=True) == HOLDINGS_HEALTH_RED
    assert _classify(landed_open=True) == HOLDINGS_HEALTH_RED
    assert _classify(qa_failed=True) == HOLDINGS_HEALTH_RED


def test_parked_stays_calm_and_never_orange() -> None:
    assert _classify(parked=True, idle_seconds=IDLE * 2) == HOLDINGS_HEALTH_GREEN
    assert _classify(parked=True, item_blocked=True) == HOLDINGS_HEALTH_GREEN
    assert (
        _classify(parked=True, idle_seconds=STAFFING, item_blocked=True)
        == HOLDINGS_HEALTH_GREEN
    )


def test_parked_still_surfaces_act_now_red() -> None:
    assert _classify(parked=True, landed_open=True) == HOLDINGS_HEALTH_RED
    assert _classify(parked=True, stale_eligible=True) == HOLDINGS_HEALTH_RED


def test_worst_of_red_beats_orange_and_yellow() -> None:
    assert (
        _classify(
            idle_seconds=IDLE,
            item_blocked=True,
            qa_failed=True,
        )
        == HOLDINGS_HEALTH_RED
    )


def test_projection_paints_blocked_item_orange() -> None:
    import sqlite3

    from yoke_core.domain.session_holdings_health import (
        current_holdings_health_by_session,
    )
    from yoke_core.domain.work_claim_targets import make_item_target

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            status TEXT,
            blocked INTEGER,
            merged_at TEXT,
            merge_queue_landed_at TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO items VALUES (7,'implementing',1,NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO work_claims VALUES (1,'s1','item',?,?,NULL)",
        (make_item_target(7).scope_json(), "2026-09-01T12:00:00Z"),
    )
    now = datetime(2026, 9, 1, 12, 1, tzinfo=timezone.utc)
    tones = current_holdings_health_by_session(
        conn,
        [{"session_id": "s1", "mode": "dash", "liveness": "active", "project_id": None}],
        {"s1": {"last_tool_call_at": "2026-09-01T12:00:50Z"}},
        {"s1": {"stale_eligible_at": "2026-09-01T12:30:00Z"}},
        now=now,
    )
    assert tones["s1"] == HOLDINGS_HEALTH_ORANGE
