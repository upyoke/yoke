"""A plan group moved by takeover runs against its successor's delivered build."""

from __future__ import annotations

import json

from runtime.api.domain.deployment_qa_plan_group_rebind_test_support import (
    FIRST,
    LINEAGES,
    SECOND,
    begin_group,
    order,
    pass_first_case,
    resume,
    row_targets,
    seed_open_group,
    take_over,
    wait_for_host,
)
from runtime.api.domain.deployment_qa_plan_groups_test_support import RUN
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_execution_store import select_plan_execution


def _deployment(execution):
    return execution["execution_target"]["deployment"]


def test_fresh_run_after_two_takeovers_freezes_the_last_successors_build(test_db):
    plan_id = seed_open_group(test_db)
    (created,) = run_groups(test_db, [RUN], "item-qa")
    take_over(test_db, plan_id, RUN, FIRST)
    take_over(test_db, plan_id, FIRST, SECOND)

    execution = begin_group(test_db, SECOND)

    deployment = _deployment(execution)
    assert deployment["run_id"] == SECOND
    assert deployment["release_lineage"] == LINEAGES[SECOND]
    assert deployment["starting_run_id"] == RUN
    assert deployment["shared_plan"]["group_id"] == created.group_id
    observation = execution["execution_target"]["observation"]
    assert observation["observed_release_lineage"] == LINEAGES[SECOND]
    (group,) = run_groups(test_db, [SECOND], "item-qa")
    assert group.group_id == created.group_id
    assert group.requirement_ids == created.requirement_ids
    assert group.digest == execution["execution_target_digest"]
    for target in row_targets(test_db, SECOND):
        assert target["deployment"]["run_id"] == SECOND
    rebound = test_db.execute(
        "SELECT rebound_from_target_json,rebind_rationale FROM qa_requirements "
        "WHERE id=%s",
        (created.requirement_ids[0],),
    ).fetchone()
    # Nothing ran in FIRST, so the group moved straight from RUN's build.
    assert json.loads(rebound[0])["deployment"]["run_id"] == RUN
    assert "moved plan group" in rebound[1]


def test_waiting_group_execution_re_freezes_in_place_across_two_takeovers(test_db):
    plan_id = seed_open_group(test_db)
    execution = begin_group(test_db, RUN)
    place = order(test_db, execution["id"])
    wait_for_host(test_db, execution)

    take_over(test_db, plan_id, RUN, FIRST)
    again = begin_group(test_db, FIRST)
    assert again["id"] == execution["id"]
    assert _deployment(again)["run_id"] == FIRST
    assert order(test_db, execution["id"]) == place

    wait_for_host(test_db, again)
    take_over(test_db, plan_id, FIRST, SECOND)
    # The host-turn wake resumes by execution id.
    resumed = resume(test_db, execution["id"])
    assert resumed is not None and resumed["id"] == execution["id"]
    assert resumed["state"] == "active"
    assert _deployment(resumed)["run_id"] == SECOND
    assert _deployment(resumed)["release_lineage"] == LINEAGES[SECOND]
    assert _deployment(resumed)["starting_run_id"] == RUN
    assert order(test_db, execution["id"]) == place
    (group,) = run_groups(test_db, [SECOND], "item-qa")
    assert group.digest == resumed["execution_target_digest"]


def test_dispatch_rebinds_a_moved_group_and_carries_its_same_destination_pass(
    test_db,
):
    from yoke_core.domain.qa_latest_execution import latest_executions
    from yoke_core.domain.qa_requirement_pass_currency import (
        passing_requirements_for_rows,
    )

    plan_id = seed_open_group(test_db, cases=2)
    passed = pass_first_case(test_db, begin_group(test_db, RUN))
    (before,) = run_groups(test_db, [RUN], "item-qa")
    assert before.open
    take_over(test_db, plan_id, RUN, FIRST)

    ensure_groups(test_db, FIRST, "item-qa")
    test_db.commit()

    (group,) = run_groups(test_db, [FIRST], "item-qa")
    assert group.group_id == before.group_id and group.digest != before.digest
    assert group.target["deployment"]["run_id"] == FIRST
    row = test_db.execute(
        "SELECT * FROM qa_requirements WHERE id=%s", (passed,)
    ).fetchone()
    assert json.loads(row["execution_target_json"]) == group.target
    assert json.loads(row["rebound_from_target_json"]) == before.target
    assert row["rebound_from_digest"] == before.digest
    attempts = latest_executions(test_db, [passed])
    assert passed in passing_requirements_for_rows(test_db, [row], attempts)


def test_a_begun_group_walk_keeps_its_target(test_db):
    plan_id = seed_open_group(test_db)
    execution = begin_group(test_db, RUN)
    test_db.execute(
        "UPDATE qa_plan_executions SET cursor_ordinal=1 WHERE id=%s",
        (execution["id"],),
    )
    test_db.commit()
    (before,) = run_groups(test_db, [RUN], "item-qa")
    take_over(test_db, plan_id, RUN, FIRST)

    ensure_groups(test_db, FIRST, "item-qa")
    test_db.commit()

    (group,) = run_groups(test_db, [FIRST], "item-qa")
    assert group.digest == before.digest
    kept = select_plan_execution(test_db, execution["id"], lock=False)
    assert kept["execution_target_digest"] == target_digest(before.target)
    assert resume(test_db, execution["id"]) is None
