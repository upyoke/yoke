"""Who holds an item claim, read from the claims themselves.

The report needs the current item-claim holders of one project. It reads
exactly those, in one statement, rather than building every session's
whole holding history and keeping the few rows it wanted.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.statement_counter import CountingConnection
from runtime.api.steering_fleet_test_helpers import (
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain.steering_fleet_report_holders import claim_holders
from yoke_core.domain.work_claim_targets import make_item_target


def _claim(conn, session_id: str, item_id: int, *, released_at: str | None = None):
    target = make_item_target(item_id)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat,"
        "released_at) VALUES (%s,%s,%s,'exclusive',%s,%s,%s)",
        (
            session_id,
            target.kind,
            target.scope_json(),
            LONG_AGO,
            LONG_AGO,
            released_at,
        ),
    )
    conn.commit()


def test_one_session_holding_two_items_is_two_holder_rows(test_db) -> None:
    fleet = seed_steering_scope(test_db)
    seed_session(fleet, "busy-worker", last_tool_call_at=LONG_AGO)
    _claim(fleet, "busy-worker", 1)
    _claim(fleet, "busy-worker", 2)

    holders = claim_holders(fleet, project_id=PROJECT_ID, now=NOW)

    assert [(row.session_id, row.item_id, row.public_ref) for row in holders] == [
        ("busy-worker", 1, "YOK-1"),
        ("busy-worker", 2, "YOK-2"),
    ]


def test_a_claim_on_another_project_stays_out_of_this_project(test_db) -> None:
    fleet = seed_steering_scope(test_db)
    insert_item(fleet, id=90, title="Elsewhere", project="platform", status="idea")
    seed_session(fleet, "cross-project-worker", last_tool_call_at=LONG_AGO)
    _claim(fleet, "cross-project-worker", 90)
    _claim(fleet, "cross-project-worker", 3)

    holders = claim_holders(fleet, project_id=PROJECT_ID, now=NOW)

    assert [(row.session_id, row.item_id) for row in holders] == [
        ("cross-project-worker", 3)
    ]


def test_a_terminated_session_holds_nothing_the_report_shows(test_db) -> None:
    fleet = seed_steering_scope(test_db)
    seed_session(fleet, "gone-worker", last_tool_call_at=LONG_AGO)
    _claim(fleet, "gone-worker", 1)
    fleet.execute(
        "UPDATE harness_sessions SET terminated_at=%s WHERE session_id=%s",
        (NOW, "gone-worker"),
    )
    fleet.commit()

    assert claim_holders(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_released_claim_is_not_a_current_holding(test_db) -> None:
    fleet = seed_steering_scope(test_db)
    seed_session(fleet, "finished-worker", last_tool_call_at=LONG_AGO)
    _claim(fleet, "finished-worker", 1, released_at=NOW)

    assert claim_holders(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_an_item_awaiting_landing_reads_as_a_landing_wait(test_db) -> None:
    """The landing flag survives the narrower read the holders now use."""
    fleet = seed_steering_scope(test_db)
    seed_session(fleet, "landing-worker", last_tool_call_at=LONG_AGO)
    fleet.execute(
        "UPDATE items SET merge_queue_pr_number='7', merge_queue_enqueued_at=%s "
        "WHERE id=1",
        (LONG_AGO,),
    )
    _claim(fleet, "landing-worker", 1)

    holders = claim_holders(fleet, project_id=PROJECT_ID, now=NOW)

    assert holders[0].item_id == 1
    assert holders[0].native_process_gone is False


def test_the_holder_read_is_one_statement_whatever_else_was_ever_held(
    test_db,
) -> None:
    fleet = seed_steering_scope(test_db)
    for index, item_id in enumerate((1, 2, 3), start=1):
        seed_session(fleet, f"holder-{index}", last_tool_call_at=LONG_AGO)
        _claim(fleet, f"holder-{index}", item_id)
    seed_session(fleet, "historical-worker", last_tool_call_at=LONG_AGO)
    _claim(fleet, "historical-worker", 1, released_at=NOW)
    counted = CountingConnection(fleet)

    holders = claim_holders(counted, project_id=PROJECT_ID, now=NOW)

    assert len(holders) == 3
    assert counted.count == 1
