"""Removing a blocker names the members it leaves waiting on it."""

from runtime.api.domain.deployment_run_member_removal_test_support import (
    ITEM,
    REASON,
    RUN,
    _red_member,
)
from runtime.api.domain.structural_status_gate_test_helpers import insert_dependency
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item

DEPENDENT = ITEM + 1


def _created_run_with_dependent(conn, *, depends: bool) -> None:
    _red_member(conn)
    release_seeded_driver(conn, RUN)
    insert_item(conn, id=DEPENDENT, workflow_id="dash", status="release")
    conn.execute(
        "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
        "VALUES (%s,%s,'2026-10-16T00:00:00Z')",
        (RUN, DEPENDENT),
    )
    conn.execute(
        "UPDATE deployment_runs SET status='created',composition_frozen_at=NULL "
        "WHERE id=%s",
        (RUN,),
    )
    conn.commit()
    if depends:
        insert_dependency(conn, DEPENDENT, ITEM, "activation", "status:done")


def test_removing_a_blocker_names_its_same_run_dependents(test_db):
    _created_run_with_dependent(test_db, depends=True)

    message = cmd_remove_item(RUN, ITEM, reason=REASON)

    assert f"YOK-{DEPENDENT} (blocked by YOK-{ITEM})" in message
    assert f"yoke deployment-runs remove-item {RUN} <dependent>" in message
    assert "first release after the blocker ships" in message


def test_removing_an_item_nothing_depends_on_names_no_dependents(test_db):
    _created_run_with_dependent(test_db, depends=False)

    message = cmd_remove_item(RUN, ITEM, reason=REASON)

    assert "blocked by" not in message
