"""Takeover moves open plan groups whole; a closed group stays where it passed."""

from runtime.api.domain.test_deployment_qa_plan_group_execution import (
    OTHER,
    _begin,
    _fail_case,
    _settle,
)
from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _pass_group,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on

NEW = "run-plan-groups-taken-over"
LATE = 9914


def _take_over(conn, plan_id, *, late=()):
    """Seed a successor run holding every member, move QA and drop old membership."""
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(conn, run_id=NEW, stages=stages, members=late, existing_members=MEMBERS)
    conn.execute(
        "UPDATE deployment_runs SET supersedes_run_id=%s,created_at=%s WHERE id=%s",
        (RUN, "2026-09-15T00:00:00Z", NEW),
    )
    transfer_qa_on(conn, old_id=RUN, new_id=NEW, moving=set(MEMBERS))
    conn.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (RUN,))
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=ANY(%s)",
        (f"flow-{NEW}", [*MEMBERS, *late]),
    )
    conn.commit()


def _shape(groups):
    return [(g.run_id, g.group_id, g.covered_item_ids, g.requirement_ids) for g in groups]


def test_a_closed_group_stays_and_a_new_member_is_owed_a_new_group(test_db):
    plan_id = _seed(test_db, attached=MEMBERS[:2])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)
    before = _shape(run_groups(test_db, [RUN]))

    _take_over(test_db, plan_id, late=(LATE,))
    _attach(test_db, LATE, plan_id)
    created = ensure_groups(test_db, NEW, "item-qa")
    test_db.commit()

    assert _shape(run_groups(test_db, [RUN])) == before
    (closed,) = run_groups(test_db, [RUN])
    assert closed.covered_item_ids == tuple(sorted(MEMBERS[:2]))
    (fresh,) = run_groups(test_db, [NEW], "item-qa")
    assert fresh.open and fresh.group_id == f"{NEW}:1"
    assert sorted(fresh.requirement_ids) == sorted(created)
    for member in MEMBERS[:2]:
        assert plan_credit_misses(test_db, member) == []
    assert [(m["plan_slug"], m["deployment_run_id"]) for m in plan_credit_misses(
        test_db, LATE
    )] == [(SLUG, NEW)]


def test_mixed_plans_the_closed_group_stays_and_the_failed_open_group_moves(test_db):
    smoke = _seed(test_db)
    other = _plan(test_db, OTHER)
    for member in MEMBERS:
        _attach(test_db, member, other)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _complete_case(test_db, _begin(test_db))
    failed_id = _fail_case(test_db, _begin(test_db, OTHER, session="other-plan-qa"))
    for group in run_groups(test_db, [RUN], "item-qa"):
        _settle(test_db, group)
    groups = {g.plan_id: g for g in run_groups(test_db, [RUN], "item-qa")}
    assert groups[smoke].closed and groups[other].open

    _take_over(test_db, smoke)

    (stayed,) = run_groups(test_db, [RUN])
    assert (stayed.group_id, stayed.plan_id) == (groups[smoke].group_id, smoke)
    assert stayed.covered_item_ids == tuple(sorted(MEMBERS))
    (moved,) = run_groups(test_db, [NEW])
    assert (moved.group_id, moved.digest) == (groups[other].group_id, groups[other].digest)
    assert moved.requirement_ids == groups[other].requirement_ids and moved.open
    verdict = test_db.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s ORDER BY id DESC LIMIT 1",
        (failed_id,),
    ).fetchone()[0]
    assert verdict == "fail"
    moved_executions = test_db.execute(
        "SELECT COUNT(*) FROM qa_plan_executions WHERE deployment_run_id=%s", (NEW,)
    ).fetchone()[0]
    stayed_executions = test_db.execute(
        "SELECT COUNT(*) FROM qa_plan_executions WHERE deployment_run_id=%s", (RUN,)
    ).fetchone()[0]
    assert (moved_executions, stayed_executions) == (1, 1)
    # The moved group is still the open one: no second group of the plan forms.
    assert ensure_groups(test_db, NEW, "item-qa") == []
    for member in MEMBERS:
        assert [m["plan_slug"] for m in plan_credit_misses(test_db, member)] == [OTHER]
