"""A failure recorded against a superseded run's target no longer grades the new one.

A superseding run rebinds its carried requirements to its own target. Seen
on run-20261120-020: a fail recorded against run-016's target stayed red, the
driver skipped the plan, and the steering report asked for a decision. A
non-pass now counts only against the requirement's current target digest.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.deployment_qa_plan_groups_test_support import RUN
from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain.deployment_qa_case_failure_kinds import (
    FAILURE_RED,
    FAILURE_UNRUN,
)
from yoke_core.domain.deployment_qa_pending_plans import pending_stage_plans
from yoke_core.domain.deployment_qa_stage_case_failures import case_failures
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_red_requirements import red_blocking_requirements

SUPERSEDING_DIGEST = "f" * 64


def _seeded(conn):
    plan_id = _plan(conn, "automatic-smoke")
    stages = _stages(plan_id)
    stages[1]["scope"] = "run"
    _seed_run(conn, run_id=RUN, stages=stages, members=())
    stage = stages[1]
    result, message = materialize_and_gate_deployment_qa_stage(conn, stage, run_id=RUN)
    assert result == -4, message
    pending = pending_stage_plans(conn, stage, RUN)
    assert len(pending) == 1
    requirement = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND plan_id=%s AND method_id IS NOT NULL ORDER BY id LIMIT 1",
        (RUN, plan_id),
    ).fetchone()[0]
    return stage, int(requirement), pending


def _rebind(conn, requirement_id: int) -> None:
    """The superseding run's materialization moves the obligation's target."""
    conn.execute(
        "UPDATE qa_requirements SET execution_target_digest=%s WHERE id=%s",
        (SUPERSEDING_DIGEST, requirement_id),
    )


def _failures(conn, stage, digest):
    return case_failures(
        conn,
        run_id=RUN,
        stage_name=stage["name"],
        member_item_id=None,
        execution_target_digest=digest,
    )


def _digest(conn, requirement_id: int) -> str:
    return conn.execute(
        "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()[0]


@pytest.mark.parametrize("verdict", ["fail", "error"])
def test_fail_against_current_target_stays_red(test_db, verdict):
    stage, requirement, _ = _seeded(test_db)
    record_case_verdict(test_db, requirement, verdict, evidence=True)

    red = red_blocking_requirements(test_db, [RUN])[RUN]
    assert [entry.requirement_id for entry in red] == [requirement]
    kinds = [f.kind for f in _failures(test_db, stage, _digest(test_db, requirement))]
    assert kinds == [FAILURE_RED]
    assert pending_stage_plans(test_db, stage, RUN) == []


@pytest.mark.parametrize("verdict", ["fail", "error"])
def test_fail_against_superseded_target_grades_as_unrun(test_db, verdict):
    stage, requirement, pending = _seeded(test_db)
    record_case_verdict(test_db, requirement, verdict, evidence=True)
    _rebind(test_db, requirement)

    assert red_blocking_requirements(test_db, [RUN]) == {}
    failures = _failures(test_db, stage, SUPERSEDING_DIGEST)
    assert [(f.requirement_id, f.kind) for f in failures] == [
        (requirement, FAILURE_UNRUN)
    ]
    assert pending_stage_plans(test_db, stage, RUN) == pending


def test_fail_recaptured_on_new_target_is_red_again(test_db):
    stage, requirement, _ = _seeded(test_db)
    record_case_verdict(test_db, requirement, "fail", evidence=True)
    _rebind(test_db, requirement)
    record_case_verdict(test_db, requirement, "fail", evidence=True)

    assert [r.requirement_id for r in red_blocking_requirements(test_db, [RUN])[RUN]] == [
        requirement
    ]
    assert pending_stage_plans(test_db, stage, RUN) == []


DETACHED, ENROLLED = 9771, 9772
MEMBER_RUN = "run-detached-member-red"


def _member_fails(conn) -> dict[int, int]:
    """Both members' item QA failed; returns each member's requirement id."""
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )

    stages = _stages(_plan(conn, "member-smoke"))
    _seed_run(conn, run_id=MEMBER_RUN, stages=stages, members=(DETACHED, ENROLLED))
    found = {}
    for member in (DETACHED, ENROLLED):
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=MEMBER_RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
        found[member] = int(conn.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_member_item_id=%s AND blocking_mode='blocking' "
            "ORDER BY id LIMIT 1",
            (MEMBER_RUN, member),
        ).fetchone()[0])
        record_case_verdict(conn, found[member], "fail", evidence=True)
    return found


def test_set_aside_member_fail_is_not_a_current_red_blocker(test_db):
    from yoke_core.domain.deployment_run_member_removal import remove_members_on
    from yoke_core.domain.deployment_run_member_set_aside import (
        FROZEN_SET_ASIDE_REASON,
    )

    requirements = _member_fails(test_db)
    remove_members_on(
        test_db, MEMBER_RUN, (DETACHED,), reason=FROZEN_SET_ASIDE_REASON, preserve_qa=True
    )

    red = red_blocking_requirements(test_db, [MEMBER_RUN])[MEMBER_RUN]
    assert [(r.requirement_id, r.item_id) for r in red] == [
        (requirements[ENROLLED], ENROLLED)
    ]
    kept = test_db.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s",
        (requirements[DETACHED],),
    ).fetchall()
    assert [row["verdict"] for row in kept] == ["fail"]  # history stays


def test_enrolled_member_fail_stays_red(test_db):
    requirements = _member_fails(test_db)

    red = red_blocking_requirements(test_db, [MEMBER_RUN])[MEMBER_RUN]
    assert sorted(r.requirement_id for r in red) == sorted(requirements.values())
