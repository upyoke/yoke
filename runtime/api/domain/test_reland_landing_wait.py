"""A re-land armed in the merge queue is a landing wait, not unfinished work.

An item that already landed keeps its earlier landing on its own columns
while a re-land pull request rides an open attempt. Every reader that asks
whether a claim holder is waiting on GitHub reads that attempt first.
"""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    LONG_AGO,
    NOW,
    PROJECT_ID,
    WORKER_SESSION,
    seed_steering_scope,
)
from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.domain.sessions_holdings_claim_facts import (
    ITEM_AWAITING_LANDING_KEY,
    claimed_item_facts,
)
from yoke_core.domain.steering_fleet_report_holders import _held_item_rows
from yoke_core.domain.turn_end_unfinished_work import (
    stop_is_legitimate,
    waiting_on_landing,
)
from yoke_core.domain.work_claim_targets import make_item_target

ITEM_ID = 1


def _landed_then_reopened(conn, *, attempt_enqueued_at, attempt_closed_at=None):
    """Item 1 landed long ago, reopened, and a re-land pull request opened."""
    conn.execute(
        "UPDATE items SET status='implementing', merged_at=%s, "
        "merge_queue_enqueued_at=%s, merge_queue_landed_at=%s WHERE id=%s",
        (LONG_AGO, LONG_AGO, LONG_AGO, ITEM_ID),
    )
    conn.execute(
        "INSERT INTO merge_queue_landing_attempts "
        "(item_id,project_id,pr_number,enqueued_at,opened_at,closed_at) "
        "VALUES (%s,%s,'2612',%s,%s,%s)",
        (ITEM_ID, PROJECT_ID, attempt_enqueued_at, NOW, attempt_closed_at),
    )
    target = make_item_target(ITEM_ID)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        "VALUES (%s,%s,%s,'exclusive',%s,%s)",
        (WORKER_SESSION, target.kind, target.scope_json(), LONG_AGO, LONG_AGO),
    )
    conn.commit()


def _readings(conn) -> dict[str, bool]:
    claim = gate._live_claim(conn, WORKER_SESSION)
    held = {row["item_id"]: row for row in _held_item_rows(conn, project_id=PROJECT_ID)}
    return {
        "stop_gate": stop_is_legitimate(claim),
        "holdings": claimed_item_facts(conn, [ITEM_ID])[ITEM_ID][
            ITEM_AWAITING_LANDING_KEY
        ],
        "fleet_holders": waiting_on_landing(held[ITEM_ID]),
    }


def test_an_armed_open_reland_is_a_landing_wait_for_every_reader(test_db) -> None:
    fleet = seed_steering_scope(test_db)
    _landed_then_reopened(fleet, attempt_enqueued_at=NOW)

    assert _readings(fleet) == {
        "stop_gate": True,
        "holdings": True,
        "fleet_holders": True,
    }


@pytest.mark.parametrize(
    "attempt",
    [
        {"attempt_enqueued_at": None},
        {"attempt_enqueued_at": NOW, "attempt_closed_at": NOW},
    ],
    ids=["opened-not-armed", "closed"],
)
def test_landed_item_without_an_armed_open_reland_still_owes_work(
    test_db, attempt
) -> None:
    fleet = seed_steering_scope(test_db)
    _landed_then_reopened(fleet, **attempt)

    assert _readings(fleet) == {
        "stop_gate": False,
        "holdings": False,
        "fleet_holders": False,
    }
