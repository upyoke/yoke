"""The fleet report says what each item-QA member is doing (YOK-5617).

A run whose members were all walking or queued for a Test Machine used to
read as stalled ("!" and "runs needing a decision"), a queued member read as
walking, a member or plan group with a live execution still got a run
recipe, and a walking mission got review commands. Each row now counts the
members by activity and names the live execution instead.
"""

from __future__ import annotations

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    RUN,
    _begin,
    _seed as _seed_plan_group_run,
)
from runtime.api.domain.deployment_qa_plan_group_scenarios_test_support import (
    _dispatch,
    _form,
    _manual_plan,
)
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    SESSION_ACTOR_ID,
    _project,
    seed_session,
)
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    record_case_verdict,
    seed_run_standing_on_qa_stage,
)
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.coordination_claims import acquire
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.qa_constants import AGENT_VERDICT_PATH
from yoke_core.domain.qa_host_turns import join_host_queue
from yoke_core.domain.qa_pending_agent_review import pending_review_verdict_refusal
from yoke_core.domain.steering_fleet_report_run_progress import run_progress
from yoke_core.domain.work_claim_targets import make_qa_admission_target

RUN_ID = "run-20261121-activity"
WALKING, QUEUED, IDLE = 19501, 19502, 19503
MACHINE = "windows-native-lab"
WALK_MACHINE = "test-mac-studio"


def _seed(conn, members=(WALKING, QUEUED)) -> dict[int, int]:
    plan_id = create_smoke_plan(conn, project="yoke", slug=f"smoke-{RUN_ID}")
    seed_run_standing_on_qa_stage(
        conn,
        run_id=RUN_ID,
        project="yoke",
        stages=item_qa_stage_definitions(plan_id),
        members=members,
        lineage="b" * 40,
    )
    cases = {}
    for member in members:
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=RUN_ID,
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=member,
        )
        row = conn.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_member_item_id=%s AND method_id IS NOT NULL",
            (RUN_ID, member),
        ).fetchone()
        cases[member] = int(row["id"])
    conn.commit()
    release_seeded_driver(conn, RUN_ID)
    return cases


def _execution(conn, execution_id, member, state, *, machine=None, digest=None) -> None:
    session = f"walker-{member}"
    seed_session(conn, session)
    lease = None
    if machine is not None:
        acquire(conn, make_qa_admission_target(machine), session, reason="walk", commit=False)
        lease = conn.execute(
            "SELECT id FROM work_claims WHERE session_id=%s AND released_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (session,),
        ).fetchone()[0]
    digest = digest or conn.execute(
        "SELECT execution_target_digest FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND method_id IS NOT NULL",
        (RUN_ID, member),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,session_id,roster_digest,roster_json,state,"
        "created_at,heartbeat_at,execution_target_digest,test_machine_lease_id) "
        "VALUES (%s,%s,%s,%s,%s,'roster','[]',%s,now(),now(),%s,%s)",
        (execution_id, RUN_ID, ITEM_QA_STAGE, member, session, state, digest, lease),
    )
    conn.commit()


def _queue(conn, execution_id, session, *, ahead=2) -> None:
    target = make_qa_admission_target(MACHINE)
    for index in range(ahead):
        seed_session(conn, f"earlier-{index}")
        join_host_queue(
            conn, target, session_id=f"earlier-{index}", actor_id=1, resume_command="resume"
        )
    join_host_queue(
        conn,
        target,
        session_id=session,
        actor_id=1,
        resume_command="resume",
        execution_id=execution_id,
    )
    conn.commit()


def _progress(conn):
    (progress,) = run_progress(
        conn, project_id=resolve_project_id(conn, "yoke"), now=utc_now()
    )
    return progress


def _member_line(progress, member) -> str:
    return next(line for line in progress.member_lines if str(member) in line)


def test_walking_and_queued_members_are_counted_not_flagged(test_db) -> None:
    _seed(test_db)
    _execution(test_db, "exec-walk", WALKING, "walking", machine=WALK_MACHINE)
    _execution(test_db, "exec-queued", QUEUED, "waiting")
    _queue(test_db, "exec-queued", f"walker-{QUEUED}")

    progress = _progress(test_db)

    assert progress.member_counts == (
        "item QA: 2 open: 1 walking, 1 queued, 0 not started, 0 red"
    )
    assert not progress.qa_notice_stalled
    assert not progress.needs_action
    queued = _member_line(progress, QUEUED)
    place = f"queued for {MACHINE}, 3rd for {MACHINE}"
    assert place in queued and "walking" not in queued
    assert "yoke qa case run" not in queued and "yoke qa plan run" not in queued
    assert "plan execution exec-queued (waiting) already owns it" in queued
    walking = _member_line(progress, WALKING)
    assert f"walking on {WALK_MACHINE} under session walker-{WALKING}" in walking
    assert "yoke qa case run" not in walking


def test_a_carried_walk_on_its_frozen_target_still_owns_the_members_cases(
    test_db,
) -> None:
    """A takeover carries a walk onto the successor run with the target it
    froze, so its digest differs from the rebound requirement's. It still
    owns the member's cases: no recipe beside it (run-20261121-016)."""
    _seed(test_db, members=(WALKING,))
    _execution(test_db, "exec-carried", WALKING, "walking", digest="predecessor-target")

    progress = _progress(test_db)
    line = _member_line(progress, WALKING)

    assert "plan execution exec-carried (walking) already owns it" in line
    assert "yoke qa case run" not in line


def test_a_red_member_still_raises_the_mark(test_db) -> None:
    cases = _seed(test_db)
    _execution(test_db, "exec-queued", QUEUED, "waiting")
    _queue(test_db, "exec-queued", f"walker-{QUEUED}", ahead=0)
    record_case_verdict(test_db, cases[WALKING], "fail", evidence=True)
    test_db.commit()

    progress = _progress(test_db)

    assert progress.member_counts == (
        "item QA: 2 open: 0 walking, 1 queued, 0 not started, 1 red"
    )
    assert progress.needs_action


def test_an_unwakeable_idle_member_raises_the_mark(test_db) -> None:
    _seed(test_db, members=(IDLE,))

    progress = _progress(test_db)

    assert progress.member_counts == (
        "item QA: 1 open: 0 walking, 0 queued, 1 not started, 0 red"
    )
    assert "not woken: no addressable holder" in _member_line(progress, IDLE)
    assert progress.qa_notice_stalled and progress.needs_action


def test_a_walking_mission_names_the_walk_and_still_refuses_a_capture_verdict(
    test_db,
) -> None:
    cases = _seed(test_db, members=(WALKING,))
    _execution(test_db, "exec-walk", WALKING, "walking", machine=WALK_MACHINE)
    test_db.execute(
        "INSERT INTO qa_plan_review_bundles(id,execution_id,roster_digest,"
        "bundle_digest,bundle_json,state,created_at) "
        "VALUES ('bundle-1','exec-walk','roster','digest',%s,'pending',now())",
        (f'{{"cases":[{{"requirement_id":{cases[WALKING]}}}]}}',),
    )
    test_db.commit()

    progress = _progress(test_db)
    text = " ".join((*progress.unresolved, *progress.member_lines))

    assert f"mission walk in progress on {WALK_MACHINE}" in text
    assert "review-begin" not in text and "review-submit" not in text
    refusal = pending_review_verdict_refusal(
        test_db,
        cases[WALKING],
        "pass",
        {"verdict_path": AGENT_VERDICT_PATH, "method_id": "command"},
    )
    assert refusal is not None
    assert "mission walk still in progress" in refusal
    assert "review-begin" not in refusal


def test_a_queued_plan_group_execution_replaces_the_group_recipe(test_db) -> None:
    plan_id = _seed_group(test_db)
    seed_session(test_db, "plan-group-qa")
    execution = _begin(test_db, actor_id=SESSION_ACTOR_ID)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='waiting' WHERE id=%s", (execution["id"],)
    )
    test_db.commit()
    _queue(test_db, str(execution["id"]), "plan-group-qa", ahead=0)

    (progress,) = run_progress(test_db, project_id=1, now=utc_now())
    text = " ".join((*progress.unresolved, *progress.member_lines))

    assert f"plan execution {execution['id']} (waiting) already owns it" in text
    assert f"queued for {MACHINE}, 1st for {MACHINE}" in text
    assert "yoke qa plan run --deployment-run-id" not in text
    assert "yoke qa plan partitions --deployment-run-id" not in text
    assert not progress.qa_notice_stalled
    assert plan_id


def _seed_group(conn) -> int:
    plan_id = _seed_plan_group_run(conn)
    _manual_plan(conn, plan_id)
    _project(conn)
    seed_session(conn, "run-starter")
    release_seeded_driver(conn, RUN)
    conn.execute(
        "UPDATE deployment_runs SET created_by_session_id='run-starter' WHERE id=%s",
        (RUN,),
    )
    conn.commit()
    _form(conn)
    _dispatch(conn)
    return plan_id
