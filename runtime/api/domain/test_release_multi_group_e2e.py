"""One driver runs independent release plans while another target awaits review."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.fixtures.carried_release_candidate import (
    git,
    insert_run,
    record_landing_receipt,
    release_repository,
    serve_repositories,
)
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest
from yoke_core.domain.deployment_qa_pending_plans import (
    QaDispatchResult,
    pending_stage_plans,
)
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deploy_pipeline_qa_wait import dispatch_until_qa_resolves
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import QaPlanError, replace_plan_cases

RUN = "run-multiple-release-plans"
MEMBERS = (9911, 9912, 9913)


def _case(command: str) -> dict:
    return {
        "case_key": "command-smoke",
        "method_id": "command",
        "instructions": "Run the candidate command",
        "expected_outcome": "It passes",
        "method_config": {"command": command},
    }


def _attach(conn, member, plan_id):
    conn.execute(
        "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,'release','post_deploy','2026-10-28T00:00:00Z')",
        (member, plan_id),
    )
    conn.commit()


def _transport(monkeypatch, actor):
    from yoke_cli.transport import dispatcher
    from yoke_core.domain.yoke_function_dispatch import dispatch

    def call(*, function_id, target, payload=None, **kwargs):
        return dispatch(
            FunctionCallRequest(
                function=function_id,
                actor=kwargs.get("actor") or actor,
                target=target,
                payload=payload or {},
            )
        )

    monkeypatch.setattr(dispatcher, "call_dispatcher", call)
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution.execution_actor", lambda _: actor
    )


def test_driver_runs_candidate_plans_beside_a_pending_review(tmp_path, monkeypatch):
    with test_database() as conn:
        repo, baseline, tip = release_repository(tmp_path, "release")
        (repo / "t.py").write_text("def test_candidate():\n    assert 2 + 2 == 4\n")
        git(repo, "add", "t.py")
        git(repo, "commit", "-m", "Add candidate probe")
        tip = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "--detach", tip)
        serve_repositories(monkeypatch, {1: repo})
        from yoke_core.domain import qa_candidate_checkout

        provision = qa_candidate_checkout.provision_test_environment

        def candidate_environment(root, **kwargs):
            result = provision(root, **kwargs)
            # The tiny fixture uses this test interpreter's installed pytest.
            (Path(root) / ".venv").symlink_to(sys.prefix, target_is_directory=True)
            return result

        monkeypatch.setattr(
            qa_candidate_checkout, "provision_test_environment", candidate_environment
        )
        plans = [
            _plan(conn, slug)
            for slug in ("candidate-tests", "candidate-command", "review")
        ]
        replace_plan_cases(
            conn, plan_id=plans[0], cases=[_case("yoke watch pytest -- t.py")]
        )
        with pytest.raises(QaPlanError, match="qa_plan_member_reference_unsupported"):
            replace_plan_cases(
                conn, plan_id=plans[1], cases=[_case("echo $DEPLOYMENT_MEMBER_REF")]
            )
        replace_plan_cases(
            conn, plan_id=plans[1], cases=[_case("git rev-parse --verify HEAD")]
        )
        replace_plan_cases(
            conn,
            plan_id=plans[2],
            cases=[
                {
                    **_case("true"),
                    "method_id": "browser-inspection",
                    "method_config": {
                        "steps": [
                            {"action": "navigate", "route": "/"},
                            {
                                "action": "screenshot",
                                "label": "release",
                                "capture": True,
                            },
                        ]
                    },
                }
            ],
        )
        stages = _stages(plans[0])
        stages[1].pop("cases")
        _seed_run(conn, run_id=RUN, stages=stages, members=MEMBERS, release_lineage=tip)
        for member, plan_id in zip(MEMBERS, plans):
            _attach(conn, member, plan_id)
        from runtime.api.fixtures.backlog_inserts import insert_item
        from yoke_core.domain.deployment_run_carried_membership import (
            enroll_carried_members,
        )

        late_item = 9941
        flow = f"flow-{RUN}"
        insert_item(
            conn,
            id=late_item,
            project_sequence=late_item,
            workflow_id="dash",
            status="reviewing-implementation",
            deployment_flow=flow,
        )
        record_landing_receipt(conn, late_item, branch="landed-closeout", tip=tip)
        _attach(conn, late_item, plans[0])
        insert_run(
            conn, "run-previous-groups", lineage=baseline, status="succeeded", flow=flow
        )
        from runtime.api.fixtures.completed_delivery import pin_run_delivery

        pin_run_delivery(conn, "run-previous-groups", environment="stage")
        conn.execute(
            "UPDATE deployment_runs SET composition_frozen_at=NULL,status='created' WHERE id=%s",
            (RUN,),
        )
        conn.commit()
        enrolled = enroll_carried_members(conn, RUN)
        from yoke_core.domain.deployment_run_carried_work import derive_carried_work
        from yoke_core.domain.deployment_run_carried_membership import (
            carried_enrollment_blocked,
        )

        assert enrolled, (
            derive_carried_work(conn, RUN),
            carried_enrollment_blocked(conn, RUN),
        )
        assert (
            conn.execute(
                "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
                (RUN, late_item),
            ).fetchone()
            is not None
        )
        from yoke_core.domain.deployment_requirement_snapshots import (
            snapshot_member_requirements,
            requirement_selection,
        )

        snapshot = snapshot_member_requirements(
            conn,
            run_id=RUN,
            item_id=late_item,
            selection_json=requirement_selection(),
        )
        conn.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=%s "
            "WHERE run_id=%s AND item_id=%s",
            (snapshot, RUN, late_item),
        )
        # Close-out finishes after admission; resume the fixture's frozen QA state.
        conn.execute("UPDATE items SET status='release' WHERE id=%s", (late_item,))
        conn.execute(
            "UPDATE deployment_runs SET status='executing',"
            "composition_frozen_at='2026-09-14T00:01:00Z' WHERE id=%s",
            (RUN,),
        )
        conn.commit()
        actor = ActorContext(
            actor_id=str(register_session_actor(conn, DRIVER_SESSION)),
            session_id=DRIVER_SESSION,
        )
        conn.execute(
            "UPDATE harness_sessions SET executor='codex',executor_surface='codex-cli',"
            "executor_version='0.161.0' WHERE session_id=%s",
            (DRIVER_SESSION,),
        )
        conn.commit()
        _transport(monkeypatch, actor)
        ensure_groups(conn, RUN, "item-qa")
        conn.commit()
        review = begin_plan_execution(
            conn,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            plan="review",
            actor_id=actor.actor_id,
            session_id=actor.session_id,
        )
        conn.execute(
            "UPDATE qa_plan_executions SET state='awaiting_walk_review' WHERE id=%s",
            (review["id"],),
        )
        conn.commit()
        now = [0.0]
        lines = []

        def dispatch(stage, **kwargs):
            code, message = materialize_and_gate_deployment_qa_stage(
                conn, stage, run_id=RUN
            )
            return QaDispatchResult(
                code, message, pending_stage_plans(conn, stage, RUN)
            )

        result = dispatch_until_qa_resolves(
            dispatch,
            stages[1],
            run_id=RUN,
            project="yoke",
            timeout_seconds=1,
            fingerprint=lambda: str(now[0]),
            monotonic=lambda: now[0],
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
            write=lines.append,
        )
        rows = conn.execute(
            "SELECT p.slug,q.verdict FROM qa_requirements r JOIN qa_plans p ON p.id=r.plan_id "
            "LEFT JOIN qa_runs q ON q.qa_requirement_id=r.id WHERE r.deployment_run_id=%s "
            "ORDER BY p.slug,q.id",
            (RUN,),
        ).fetchall()
        assert ("candidate-tests", "pass") in [tuple(row) for row in rows], (
            rows,
            lines,
        )
        assert ("candidate-command", "pass") in [tuple(row) for row in rows], (
            rows,
            lines,
        )
        assert result[0] == -4, result
        assert (
            conn.execute(
                "SELECT state FROM qa_plan_executions WHERE id=%s", (review["id"],)
            ).fetchone()[0]
            == "awaiting_walk_review"
        )
        assert (
            conn.execute(
                "SELECT COUNT(DISTINCT execution_target_digest) FROM qa_plan_executions "
                "WHERE deployment_run_id=%s",
                (RUN,),
            ).fetchone()[0]
            == 3
        )
        assert not any("Run each" in line for line in lines)
        notices = conn.execute(
            "SELECT body FROM session_messages WHERE idempotency_key LIKE %s",
            (f"deployment-qa-stage-wait:{RUN}:item-qa:plan-groups:%",),
        ).fetchall()
        assert notices
        for notice in notices:
            assert "--plan review" in notice[0]
            assert "--plan candidate-tests" not in notice[0]
            assert "yoke qa " not in notice[0]
            assert "yoke watch " not in notice[0]
            assert "yoke --env " in notice[0]


def test_command_ci_cannot_be_attached_or_added_to_a_deployment_plan(test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_plan_attachments import attach_plan_to_item

    item_id = 9931
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="release",
    )
    plan_id = _plan(test_db, "deployment-ci-refused")
    ci = {
        **_case("true"),
        "method_id": "command-ci",
        "method_config": {"command": "true", "ci_workflow": "ci.yml"},
    }
    replace_plan_cases(test_db, plan_id=plan_id, cases=[ci])
    with pytest.raises(QaPlanError, match="deployment_ci_case_unsupported"):
        attach_plan_to_item(
            test_db,
            plan_id=plan_id,
            item_id=item_id,
            transition_id="release",
            qa_phase="post_deploy",
        )
    test_db.rollback()
    replace_plan_cases(test_db, plan_id=plan_id, cases=[_case("true")])
    attach_plan_to_item(
        test_db,
        plan_id=plan_id,
        item_id=item_id,
        transition_id="release",
        qa_phase="post_deploy",
    )
    with pytest.raises(QaPlanError, match="deployment_ci_case_unsupported"):
        replace_plan_cases(test_db, plan_id=plan_id, cases=[ci])
