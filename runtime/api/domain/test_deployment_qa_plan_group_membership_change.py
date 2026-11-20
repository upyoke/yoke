"""A plan that becomes a group retires its sole attacher's own copies, and a
group that shrinks to one attacher keeps the credit its pass already gave."""

from runtime.api.domain.deployment_qa_plan_group_takeover_test_support import (
    NEW,
    _take_over,
)
from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _seed,
)
from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group
from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_plan_ownership import plan_owners
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_completion_preconditions import (
    unresolved_blocking_qa,
)
from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on
from yoke_core.domain.deployment_run_stage_entry import set_current_stage
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

THIRD = "run-plan-groups-shrunk"
FIRST, SECOND = MEMBERS[:2]


def _member_rows(conn, run_id, member):
    return conn.execute(
        "SELECT id,retracted_at,retraction_rationale,retraction_source "
        "FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND plan_id IS NOT NULL ORDER BY id",
        (run_id, member),
    ).fetchall()


def _sole_owner_copies(conn):
    plan_id = _seed(conn, attached=(FIRST,))
    set_current_stage(conn, RUN, "item-qa")
    conn.commit()
    assert ensure_groups(conn, RUN, "item-qa") == []
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=FIRST,
    )
    conn.commit()
    assert plan_owners(conn, RUN)[plan_id] == FIRST
    copies = _member_rows(conn, RUN, FIRST)
    assert copies and all(row[1] is None for row in copies)
    return plan_id, [row[0] for row in copies]


def _join_through_takeover(conn):
    plan_id, copies = _sole_owner_copies(conn)
    _take_over(conn, plan_id)
    _attach(conn, SECOND, plan_id)
    ensure_groups(conn, NEW, "item-qa")
    conn.commit()
    return plan_id, copies


def _pass_group(conn, run_id):
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=None,
        plan=SLUG,
        actor_id="2",
        session_id="plan-group-qa",
    )
    _complete_case(conn, execution)
    (group,) = run_groups(conn, [run_id], "item-qa")
    if not group.closed:
        settle_group(
            conn, group_subject(conn, run_id, "item-qa", group, require_active=False)
        )
    conn.commit()
    (group,) = run_groups(conn, [run_id], "item-qa")
    return group


def _shrink(conn, plan_id):
    """FIRST closed: a takeover carries only SECOND into the next run."""
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(conn, run_id=THIRD, stages=stages, members=(), existing_members=(SECOND,))
    conn.execute(
        "UPDATE deployment_runs SET supersedes_run_id=%s,created_at=%s WHERE id=%s",
        (NEW, "2026-09-16T00:00:00Z", THIRD),
    )
    transfer_qa_on(conn, old_id=NEW, new_id=THIRD, moving={SECOND})
    conn.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (NEW,))
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s", (f"flow-{THIRD}", SECOND)
    )
    conn.commit()


def test_a_second_member_joining_retracts_the_first_members_unrun_copies(test_db):
    plan_id, copies = _join_through_takeover(test_db)

    (group,) = run_groups(test_db, [NEW], "item-qa")
    assert group.open and plan_owners(test_db, NEW)[plan_id] is None
    rows = _member_rows(test_db, NEW, FIRST)
    assert [row[0] for row in rows] == copies
    for _, retracted_at, rationale, source in rows:
        assert retracted_at is not None
        assert rationale == f"replaced by plan group {group.group_id}"
        assert source == "deployment_run"
    assert unresolved_blocking_qa(test_db, NEW) == [
        f"requirement #{rid} (plan_case): no passing run"
        for rid in group.requirement_ids
    ]


def test_copies_a_retry_restored_are_retired_again(test_db):
    _, copies = _join_through_takeover(test_db)
    test_db.execute(
        "UPDATE qa_requirements SET retracted_at=NULL,retraction_rationale=NULL,"
        "retraction_source=NULL WHERE id=ANY(%s)",
        (copies,),
    )
    test_db.commit()
    assert ensure_groups(test_db, NEW, "item-qa") == []
    test_db.commit()
    assert all(row[1] is not None for row in _member_rows(test_db, NEW, FIRST))


def test_a_shrunk_group_settles_and_its_survivor_owes_no_new_copies(test_db):
    plan_id, _ = _join_through_takeover(test_db)
    group = _pass_group(test_db, NEW)
    assert group.covered_item_ids == (FIRST, SECOND)
    assert unresolved_blocking_qa(test_db, NEW) == []

    _shrink(test_db, plan_id)
    assert unresolved_blocking_qa(test_db, THIRD) == []
    assert ensure_groups(test_db, THIRD, "item-qa") == []
    test_db.commit()
    assert plan_owners(test_db, THIRD)[plan_id] is None
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=THIRD,
        deployment_stage="item-qa",
        deployment_member_item_id=SECOND,
    )
    test_db.commit()
    assert _member_rows(test_db, THIRD, SECOND) == []
    assert run_groups(test_db, [THIRD]) == []
    assert unresolved_blocking_qa(test_db, THIRD) == []
