"""A member's own plan refreshes beside a live run-wide walk of its shared plan."""

import pytest

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _attach,
    _begin,
    _materialize,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)


def _instructions(conn, member):
    return {
        int(row["plan_id"]): str(row["instructions"])
        for row in conn.execute(
            "SELECT plan_id,instructions FROM qa_requirements "
            "WHERE deployment_run_id=%s AND COALESCE(deployment_member_item_id,0)=%s",
            (RUN, member or 0),
        ).fetchall()
    }


def _refresh(conn, plan):
    return rematerialize_for_deployment_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[1],
        plan=plan,
    )


def _seed_shared_walk_and_private_plan(conn):
    shared = _seed(conn)
    private = _plan(conn, "member-private-plan")
    _attach(conn, MEMBERS[1], private)
    for member in MEMBERS:
        _materialize(conn, member)
    walk = _begin(conn, MEMBERS[0])
    assert walk["deployment_member_item_id"] is None
    return shared, private


@pytest.mark.parametrize("by", ["id", "slug"])
def test_named_private_plan_refreshes_while_run_wide_walk_is_live(test_db, by):
    shared, private = _seed_shared_walk_and_private_plan(test_db)
    shared_before = _instructions(test_db, None)
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions=%s WHERE plan_id IN (%s,%s)",
        ("Run the corrected command.", shared, private),
    )
    test_db.commit()

    result = _refresh(test_db, private if by == "id" else "member-private-plan")

    assert result["plan_ids"] == [private]
    assert len(result["refreshed_requirement_ids"]) == 1
    assert _instructions(test_db, MEMBERS[1]) == {private: "Run the corrected command."}
    assert _instructions(test_db, None) == shared_before


def test_named_plan_matching_no_member_rows_refuses_with_its_name(test_db):
    _seed_shared_walk_and_private_plan(test_db)
    with pytest.raises(QaPlanError, match="no materialized cases from plan 'absent'"):
        _refresh(test_db, "absent")


def test_named_plan_refuses_when_member_has_no_own_rows(test_db):
    _seed(test_db)
    _materialize(test_db, MEMBERS[1])
    with pytest.raises(QaPlanError, match="shared_plan_refresh_selection"):
        _refresh(test_db, "absent")
