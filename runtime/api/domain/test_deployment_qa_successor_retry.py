"""Takeover moves shared item QA; the successor's deployment is what QA tests.

A FAIL recorded on the older release is retried on the same requirement once
the successor deploys, against the successor's pinned release and source, and
its owner is told once to retry. An execution still walking at takeover keeps
its identity, cursor, completed results and host custody.
"""

from __future__ import annotations

import pytest

from runtime.api.domain import test_deployment_qa_shared_plans as shared
from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.test_deployment_qa_stage_execution import _stages
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    _bodies,
    _claim,
    _project,
    seed_session,
)
from yoke_core.domain import delivery_evidence_ladder
from yoke_core.domain import deployment_qa_release_version as release_version
from yoke_core.domain import deployment_run_candidate_containment as containment
from yoke_core.domain.deployment_qa_failure_handoff import (
    failure_handoff_key,
    notify_member_qa_failure,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_run_project_sources import run_source_sha
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)
from yoke_core.domain.qa_case_execution_context import get_case_execution_context
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import (
    plan_execution_view,
    select_plan_execution,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.work_claim_targets import make_item_target

MEMBER = shared.MEMBERS[0]


@pytest.fixture(autouse=True)
def _pinned_release(monkeypatch):
    """Each delivered commit pins its own Yoke release."""
    monkeypatch.setattr(release_version, "_pin_file", lambda conn, pid: "pin.txt")
    monkeypatch.setattr(
        release_version, "_pinned_version", lambda conn, pid, sha, path: f"v-{sha[:6]}"
    )


def _plan(conn) -> int:
    plan_id = int(
        create_plan(
            conn,
            project="yoke",
            slug="successor-retry",
            name="Successor retry",
            infer_target_environment=False,
        )["id"]
    )
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": f"run {key}",
                "expected_outcome": "the command passes",
                "method_config": {"command": "true"},
            }
            for position, key in ((1, "carried-pass"), (2, "retried-fail"))
        ],
    )
    return plan_id


def _record(conn, execution, ordinal, verdict):
    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )

    requirement_id = int(execution["roster"][ordinal]["requirement_id"])
    stamp = "2026-10-14T00:02:00Z"
    config = conn.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0]
    raw = stamp_executed_method_config(
        f"{verdict} evidence", config, conn=conn, requirement_id=requirement_id
    )
    run_id = int(
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
            "raw_result,started_at,completed_at,created_at) VALUES "
            "(%s,'worktree_run','plan_case',%s,%s,%s,%s,%s) RETURNING id",
            (requirement_id, verdict, raw, stamp, stamp, stamp),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
        (run_id, f"evidence://{verdict}", stamp),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=ordinal,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": verdict,
            "case_outcome": "passed" if verdict == "pass" else "failed",
            "run_id": run_id,
        },
    )
    return requirement_id, run_id


def _seed_shared_execution(conn, monkeypatch, *, producer=HOLDER_A):
    plan_id = _plan(conn)
    stages = _stages(plan_id)
    stages[1].pop("cases")
    shared._seed_run(conn, run_id=shared.RUN, stages=stages, members=shared.MEMBERS)
    for member in shared.MEMBERS:
        shared._attach(conn, member, plan_id)
        shared._materialize(conn, member)
    conn.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id=ANY(%s)",
        (f"flow-{shared.RUN}", list(shared.MEMBERS)),
    )
    _project(conn)
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(MEMBER).scope_json(),
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=shared.RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        actor_id="1",
        session_id=producer,
    )
    monkeypatch.setattr(
        delivery_evidence_ladder, "item_merge_identity", lambda conn, item: "e" * 40
    )
    takeover._contains(monkeypatch)
    return execution


def _take_over_and_deploy(conn, monkeypatch=None, state=containment.CONTAINED):
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,created_at,composition_frozen_at,requirement_snapshot) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,'created',"
        "created_at,composition_frozen_at,requirement_snapshot FROM deployment_runs "
        "WHERE id=%s",
        (takeover.NEW, takeover.NEW_LINEAGE, shared.RUN),
    )
    assert (
        takeover.take_over_waiting_run(
            conn, takeover.NEW, session_id=takeover.DRIVER_SESSION
        )
        == shared.RUN
    )
    conn.execute(
        "UPDATE deployment_runs SET status='executing',current_stage='deploy' WHERE id=%s",
        (takeover.NEW,),
    )
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=takeover.NEW,
        stage_name="deploy",
        correlation_id="successor-deploy-1",
        target_kind="persistent_environment",
        executor="test",
        commit=False,
    )
    complete_deployment_stage_receipt(
        conn,
        run_id=takeover.NEW,
        receipt_id=int(receipt["id"]),
        correlation_id=str(receipt["correlation_id"]),
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage=takeover.NEW_LINEAGE,
        executor_receipt="test://successor-ready",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s",
        (takeover.NEW,),
    )
    conn.commit()
    if monkeypatch is not None:
        takeover._contains(monkeypatch, state)


def _release(view) -> str:
    return view["execution_target"]["endpoints"]["release_version"]


def test_an_uncontained_merge_keeps_the_rework_handoff(test_db, monkeypatch):
    execution = _seed_shared_execution(
        test_db,
        monkeypatch,
        producer="separate-qa-session",
    )
    _record(test_db, execution, 0, "pass")
    _failed, fail_run = _record(test_db, execution, 1, "fail")
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")
    _take_over_and_deploy(test_db, monkeypatch, containment.UNDETERMINED)
    status = deployment_qa_stage_status(
        test_db, run_id=takeover.NEW, stage_name="item-qa", member_item_id=MEMBER
    )
    notify_member_qa_failure(
        test_db, run_id=takeover.NEW, stage="item-qa", item_id=MEMBER, status=status
    )
    key = failure_handoff_key(
        takeover.NEW, "item-qa", MEMBER, str(status["target_digest"]), fail_run
    )
    [body] = _bodies(test_db, key)
    assert "Classify the failure and start rework" in body
    assert "retry the case" not in body


def test_a_failed_case_is_retried_on_the_successor_and_its_owner_told_once(
    test_db, monkeypatch
):
    execution = _seed_shared_execution(test_db, monkeypatch)
    passed, pass_run = _record(test_db, execution, 0, "pass")
    failed, fail_run = _record(test_db, execution, 1, "fail")
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")
    assert _release(plan_execution_view(test_db, execution)) == "v-aaaaaa"
    _take_over_and_deploy(test_db)

    status = deployment_qa_stage_status(
        test_db, run_id=takeover.NEW, stage_name="item-qa", member_item_id=MEMBER
    )
    assert status["outcome"] == "blocked"
    key = failure_handoff_key(
        takeover.NEW, "item-qa", MEMBER, str(status["target_digest"]), fail_run
    )
    for _ in range(2):  # A repeat dispatch sends no duplicate.
        delivery = notify_member_qa_failure(
            test_db, run_id=takeover.NEW, stage="item-qa", item_id=MEMBER, status=status
        )
        assert delivery in {"delivered", "undelivered"}, (
            delivery,
            status["case_failures"],
        )
    # HOLDER_A produced the FAIL itself and still gets exactly one retry notice.
    [body] = _bodies(test_db, key)
    assert "contains the item's merge; retry the case" in body
    from yoke_core.domain.project_identity import render_item_ref

    ref = render_item_ref(test_db, MEMBER)
    assert f"yoke qa plan run --item {ref} --stage item-qa --project yoke" in body

    retry = begin_plan_execution(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        actor_id="1",
        session_id=HOLDER_A,
    )
    assert retry["id"] != execution["id"]
    assert [int(case["requirement_id"]) for case in retry["roster"]] == [failed]
    assert retry["execution_target_digest"] == execution["execution_target_digest"]
    assert _release(plan_execution_view(test_db, retry)) == "v-cccccc"
    context = get_case_execution_context(test_db, requirement_id=failed)
    assert context["deployment_source_revision"] == run_source_sha(
        test_db, takeover.NEW, int(context["project_id"])
    )
    verdicts = dict(
        test_db.execute(
            "SELECT id,verdict FROM qa_runs WHERE id=ANY(%s)", ([pass_run, fail_run],)
        ).fetchall()
    )
    assert verdicts == {pass_run: "pass", fail_run: "fail"}
    assert passed != failed


def test_an_active_execution_continues_through_the_successor_deployment(
    test_db, monkeypatch
):
    execution = _seed_shared_execution(test_db, monkeypatch)
    passed, pass_run = _record(test_db, execution, 0, "pass")
    test_db.execute(
        "UPDATE qa_plan_executions SET machine_lease_id=4242 WHERE id=%s",
        (execution["id"],),
    )
    test_db.commit()
    _take_over_and_deploy(test_db)

    moved = select_plan_execution(test_db, execution["id"], lock=False)
    assert moved["id"] == execution["id"]
    assert moved["state"] == "active"
    assert moved["deployment_run_id"] == takeover.NEW
    assert moved["machine_lease_id"] == 4242
    assert moved["roster_digest"] == execution["roster_digest"]
    view = plan_execution_view(test_db, moved)
    assert [row["requirement_id"] for row in view["results"]] == [passed]
    assert _release(view) == "v-cccccc"
    # The walk resumes at its cursor: the next case records, nothing replays.
    _record(test_db, moved, 1, "pass")
    finished = select_plan_execution(test_db, execution["id"], lock=False)
    assert [row["requirement_id"] for row in plan_execution_view(test_db, finished)[
        "results"
    ]] == [passed, int(moved["roster"][1]["requirement_id"])]
    assert (
        test_db.execute("SELECT verdict FROM qa_runs WHERE id=%s", (pass_run,)).fetchone()[0]
        == "pass"
    )
