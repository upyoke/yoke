"""A manual-wake owner parked behind a scheduled recheck is waiting, not stale.

The "waiting on manual wake" row names the owner's earliest pending recheck
instead of its liveness; an owner holding none is flagged so steering knows
nobody will look at the evidence again on their own.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from runtime.api.domain.test_deployment_qa_manual_wake import _report_run
from runtime.api.steering_fleet_test_helpers import ACTOR_ID, WORKER_SESSION, compose
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_qa_manual_wake import NO_OWNER
from yoke_core.domain.session_scheduled_wake import (
    recheck_label,
    schedule_session_wake,
)
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.work_claim_targets import make_item_target

MEMBER = 3467


def _owned_report_run(test_db: Any) -> Any:
    conn = _report_run(test_db)
    conn.execute(
        "INSERT INTO work_claims(session_id,target_kind,scope,claimed_at,"
        "last_heartbeat) VALUES (%s,'item',%s,%s,%s)",
        (
            WORKER_SESSION,
            make_item_target(MEMBER).scope_json(),
            iso8601_now(),
            iso8601_now(),
        ),
    )
    conn.commit()
    return conn


def _schedule(conn: Any, *, at: Any, now: Any, reason: str) -> None:
    schedule_session_wake(
        conn,
        session_id=WORKER_SESSION,
        actor_id=ACTOR_ID,
        at=at,
        reason=reason,
        now=now,
    )
    conn.commit()


def _report(conn: Any) -> tuple[Any, str, dict]:
    report = compose(conn, now=iso8601_now())
    (wake,) = report.deployment_runs[0].manual_wakes
    (row,) = report_dict(report)["deployment_runs"][0]["manual_wakes"]
    return wake, report_body(report), row


def test_owner_with_a_future_recheck_reads_next_recheck_not_stale(test_db: Any) -> None:
    conn = _owned_report_run(test_db)
    now = utc_now()
    due = now + timedelta(hours=2)
    _schedule(conn, at=due + timedelta(hours=1), now=now, reason="later recheck")
    _schedule(conn, at=due, now=now, reason="check the required evidence")

    wake, body, row = _report(conn)

    assert wake.next_recheck_at == due
    label = recheck_label(due, now=utc_now())
    assert wake.owner() == (
        f"session {WORKER_SESSION} (mode {wake.owner_mode}, next recheck {label})"
        if wake.owner_mode
        else f"session {WORKER_SESSION} (next recheck {label})"
    )
    assert "stale" not in wake.owner()
    assert f"owner {wake.owner()}" in body
    assert row["next_recheck_at"] == format_instant(due)


def test_owner_with_only_a_past_recheck_is_flagged(test_db: Any) -> None:
    # Consumed rows are excluded by the same read; test_session_scheduled_wake pins it.
    conn = _owned_report_run(test_db)
    now = utc_now()
    # Past but not yet swept: no longer a recheck the owner is waiting on.
    _schedule(
        conn, at=now - timedelta(minutes=5), now=now - timedelta(hours=1), reason="past"
    )

    wake, body, row = _report(conn)

    assert wake.next_recheck_at is None
    assert wake.owner() == (
        f"session {WORKER_SESSION} ({wake.owner_state}) — no recheck scheduled"
    )
    assert wake.owner_liveness and wake.owner_liveness in wake.owner_state
    assert "no recheck scheduled" in body
    assert row["next_recheck_at"] is None


def test_unowned_row_still_says_no_owner(test_db: Any) -> None:
    conn = _report_run(test_db)

    wake, _body, row = _report(conn)

    assert wake.owner() == NO_OWNER
    assert row["next_recheck_at"] is None
