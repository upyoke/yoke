"""A carried result names the run that recorded it; reads stay batched."""

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _attach,
    _fail,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_shipping_reads import CountedConnection
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_activity_reads import read_activity

SUCCESSOR = "run-shared-plans-successor"


def _materialize(conn, run_id, member):
    return materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )["created_requirement_ids"]


def _take_over(conn, plan_id):
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(
        conn, run_id=SUCCESSOR, stages=stages, members=(), existing_members=MEMBERS
    )
    conn.execute(
        "UPDATE deployment_runs SET supersedes_run_id=%s,created_at=%s WHERE id=%s",
        (RUN, "2026-10-20T00:00:00Z", SUCCESSOR),
    )
    conn.execute(
        "UPDATE qa_requirements SET deployment_run_id=%s WHERE deployment_run_id=%s",
        (SUCCESSOR, RUN),
    )
    conn.commit()


def _owner(conn, requirement_id):
    rows = read_activity(conn, project="yoke", deployment_run_id=SUCCESSOR)["rows"]
    (row,) = [row for row in rows if row["requirement_id"] == requirement_id]
    return row["verdict_run_id"]


def test_moved_result_names_its_run_until_the_successor_records_one(test_db):
    plan_id = _seed(test_db)
    (requirement_id,) = _materialize(test_db, RUN, MEMBERS[0])
    _fail(test_db, requirement_id)
    _take_over(test_db, plan_id)
    assert _owner(test_db, requirement_id) == RUN
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,completed_at,created_at) VALUES "
        "(%s,'worktree_run','plan_case','pass','rerun',%s,%s,%s)",
        (requirement_id, *["2026-10-21T00:00:00Z"] * 3),
    )
    test_db.commit()
    assert _owner(test_db, requirement_id) is None


def _seed_wide(conn, run_id, members, plans):
    stages = _stages(plans[0])
    stages[1].pop("cases")
    _seed_run(conn, run_id=run_id, stages=stages, members=members)
    for member in members:
        for plan_id in plans:
            _attach(conn, member, plan_id)


def _statements(conn, run_id):
    counted = CountedConnection(conn)
    read_activity(counted, project="yoke", deployment_run_id=run_id)
    return sum(counted.queries.values())


def test_activity_read_count_does_not_grow_with_members(test_db):
    plans = [_plan(test_db, "wide-one"), _plan(test_db, "wide-two")]
    _seed_wide(test_db, "run-narrow", (9801, 9802), plans)
    _seed_wide(test_db, "run-wide", tuple(range(9811, 9819)), plans)
    # Before any copy exists, both plans are pending shared groups.
    assert _statements(test_db, "run-narrow") == _statements(test_db, "run-wide")
    for run_id, first in (("run-narrow", 9801), ("run-wide", 9811)):
        for requirement_id in _materialize(test_db, run_id, first):
            _fail(test_db, requirement_id)
    assert _statements(test_db, "run-narrow") == _statements(test_db, "run-wide")
