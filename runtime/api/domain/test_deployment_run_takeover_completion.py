"""A takeover settles the older run in the same transaction that creates the new one.

The older run keeps only members its own passed item QA closed, so it reads
succeeded at once — even while the driver that took it over is still attached
— and never sits executing without a driver.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover_case
from runtime.api.domain.test_independent_member_delivery_close_out import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _settle,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain import deployment_delivery_close_out_notice as notices
from yoke_core.domain import deployment_run_candidate_containment as containment
from yoke_core.domain import deployment_run_carried_work as carried_work
from yoke_core.domain import deployment_run_completion_preconditions as preconditions
from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_driver_attachment import live_attachment_for_run
from yoke_core.domain.deployment_run_takeover_settlement import (
    SETTLEMENT_REFUSED_CODE,
    finish_settled_takeover,
)
from yoke_core.domain.deployment_run_target_takeover import (
    TakeoverRefused,
    take_over_waiting_run,
)

OLD = "run-takeover-finish-old"
NEW = "run-takeover-finish-new"


def _run(conn: Any, run_id: str) -> dict:
    return dict(
        conn.execute(
            "SELECT status,current_stage,superseded_by_run_id FROM deployment_runs "
            "WHERE id=%s",
            (run_id,),
        ).fetchone()
    )


def _seed_new(conn: Any) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,"
        "target_environment_id,release_lineage,status,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,"
        "'created',created_at FROM deployment_runs WHERE id=%s",
        (NEW, "c" * 40, OLD),
    )
    conn.commit()


def test_a_closed_member_stays_and_the_older_run_succeeds_in_the_takeover(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    monkeypatch.setattr(
        containment,
        "candidate_contains_commit",
        lambda *_a, **_k: containment.ContainmentVerdict(containment.CONTAINED),
    )
    _seed_final_run(test_db, OLD, shared_qa=False)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=OLD,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER_B,
    )
    _settle(test_db, run_id=OLD, stage="item-qa", member=MEMBER_A)
    assert _status(test_db, MEMBER_A) == "done"
    assert live_attachment_for_run(test_db, run_id_value=OLD, now=utc_now())
    _seed_new(test_db)

    assert take_over_waiting_run(test_db, NEW, session_id=DRIVER_SESSION) == OLD
    assert _run(test_db, OLD) == {
        "status": "succeeded",
        "current_stage": "complete",
        "superseded_by_run_id": NEW,
    }
    test_db.commit()

    assert takeover_case._members(test_db, OLD) == {MEMBER_A}
    assert takeover_case._members(test_db, NEW) == {MEMBER_B}
    assert _status(test_db, MEMBER_B) == "release"
    assert _run(test_db, NEW)["status"] == "created"

    after_commit: list[tuple[str, str]] = []
    monkeypatch.setattr(
        carried_work,
        "record_carried_work",
        lambda conn, run_id: after_commit.append(("carried_work", run_id)),
    )
    monkeypatch.setattr(
        notices,
        "notify_delivery_cleared",
        lambda conn, *, run_id: after_commit.append(("notice", run_id)),
    )
    assert finish_settled_takeover(test_db, NEW) == OLD
    assert after_commit == [("carried_work", OLD), ("notice", OLD)]


def _append_stage(conn: Any, stage: dict) -> None:
    flow = f"flow-{takeover_case.OLD}"
    stages = json.loads(
        conn.execute(
            "SELECT stages FROM deployment_flows WHERE id=%s", (flow,)
        ).fetchone()[0]
    )
    conn.execute(
        "UPDATE deployment_flows SET stages=%s WHERE id=%s",
        (json.dumps([*stages, stage]), flow),
    )
    conn.commit()


def test_an_approval_after_item_qa_cancels_and_is_never_skipped(
    test_db: Any, monkeypatch
) -> None:
    takeover_case._seed_old(test_db, run_qa=False)
    _append_stage(
        test_db,
        {
            "name": "approve-release",
            "step_runner": "human-approval",
            "stage_kind": "execution",
            "scope": "run",
            "approvals": {"roles": ["owner"], "actors": []},
        },
    )
    takeover_case._close_passed(test_db)
    takeover_case._seed_new(test_db)
    takeover_case._contains(monkeypatch)

    assert takeover_case._take_over(test_db) == takeover_case.OLD

    old = takeover_case._run(test_db, takeover_case.OLD)
    assert old["status"] == "cancelled"
    assert takeover_case._members(test_db, takeover_case.NEW) == {takeover_case.WAITING}


def test_a_refused_succeeded_gate_refuses_the_takeover_and_changes_nothing(
    test_db: Any, monkeypatch
) -> None:
    takeover_case._seed_old(test_db, run_qa=False)
    takeover_case._close_passed(test_db)
    takeover_case._seed_new(test_db)
    takeover_case._contains(monkeypatch)
    monkeypatch.setattr(
        preconditions,
        "refuse_succeeded",
        lambda conn, run_id: "Error: cannot set status=succeeded -- QA unresolved.",
    )

    with pytest.raises(TakeoverRefused) as refused:
        take_over_waiting_run(
            test_db, takeover_case.NEW, session_id=DRIVER_SESSION, actor_id=1
        )
    test_db.rollback()

    assert refused.value.code == SETTLEMENT_REFUSED_CODE
    assert "QA unresolved." in str(refused.value)
    assert "terminalize" in str(refused.value)
    old = takeover_case._run(test_db, takeover_case.OLD)
    assert old["status"] == "executing" and old["superseded_by_run_id"] is None
    assert takeover_case._members(test_db, takeover_case.OLD) == {
        takeover_case.PASSED,
        takeover_case.WAITING,
    }


@pytest.mark.parametrize("apply", [False, True])
def test_run_qa_wait_transfers_failed_requirement_and_cursor_without_rewriting(
    test_db, monkeypatch, apply
):
    from yoke_core.domain.qa_plan_execution_store import roster_digest

    cases = takeover_case._seed_old(test_db, run_qa=True)
    requirement = takeover_case._memberless_copy(
        test_db, cases[takeover_case.WAITING], stage=takeover_case.RUN_QA_STAGE
    )
    takeover_case.record_case_verdict(test_db, requirement, "fail", evidence=True)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
        (takeover_case.RUN_QA_STAGE, takeover_case.OLD),
    )
    test_db.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "actor_id,session_id,roster_digest,roster_json,cursor_ordinal,state,"
        "created_at,heartbeat_at) VALUES ('retained-cursor',%s,%s,'1',%s,%s,"
        "'[]',0,'waiting',now()-interval '6 hours',now())",
        (
            takeover_case.OLD,
            takeover_case.RUN_QA_STAGE,
            DRIVER_SESSION,
            roster_digest([]),
        ),
    )
    takeover_case._seed_new(test_db)
    takeover_case._contains(monkeypatch)
    before = dict(
        test_db.execute(
            "SELECT * FROM qa_plan_executions WHERE id='retained-cursor'"
        ).fetchone()
    )
    assert (
        take_over_waiting_run(
            test_db, takeover_case.NEW, session_id=DRIVER_SESSION, apply=apply
        )
        == takeover_case.OLD
    )
    after = dict(
        test_db.execute(
            "SELECT * FROM qa_plan_executions WHERE id='retained-cursor'"
        ).fetchone()
    )
    assert after == {**before, "deployment_run_id": takeover_case.NEW}
    assert test_db.execute(
        "SELECT deployment_run_id,retracted_at FROM qa_requirements WHERE id=%s",
        (requirement,),
    ).fetchone() == (takeover_case.NEW, None)
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s", (requirement,)
        ).fetchone()[0]
        == "fail"
    )
    test_db.rollback()
    assert (
        dict(
            test_db.execute(
                "SELECT * FROM qa_plan_executions WHERE id='retained-cursor'"
            ).fetchone()
        )
        == before
    )
    assert takeover_case._members(test_db, takeover_case.OLD) == {
        takeover_case.PASSED,
        takeover_case.WAITING,
    }
    assert takeover_case._members(test_db, takeover_case.NEW) == set()


def test_failed_successor_keeps_obligations_for_another_takeover(test_db, monkeypatch):
    from yoke_core.domain.deployment_run_terminalization import terminalize_run_on
    from yoke_core.domain.qa_plan_execution_store import roster_digest

    cases = takeover_case._seed_old(test_db, run_qa=True)
    requirement = takeover_case._memberless_copy(
        test_db, cases[takeover_case.WAITING], stage=takeover_case.RUN_QA_STAGE
    )
    takeover_case.record_case_verdict(test_db, requirement, "fail", evidence=True)
    test_db.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "actor_id,session_id,roster_digest,roster_json,cursor_ordinal,state,"
        "execution_target_json,execution_target_digest,created_at,heartbeat_at) "
        "SELECT 'carried-cursor',deployment_run_id,deployment_stage,'1',%s,%s,"
        "'[]',0,'waiting',execution_target_json,execution_target_digest,now(),now() "
        "FROM qa_requirements WHERE id=%s",
        (DRIVER_SESSION, roster_digest([]), requirement),
    )
    takeover_case._seed_new(test_db)
    takeover_case._contains(monkeypatch)
    assert takeover_case._take_over(test_db) == takeover_case.OLD
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id=%s",
        (takeover_case.NEW,),
    )
    terminalize_run_on(
        test_db,
        takeover_case.NEW,
        disposition="failed",
        reason="deployment failed",
        actor_id=1,
        session_id=DRIVER_SESSION,
    )
    test_db.commit()
    assert (
        test_db.execute(
            "SELECT state FROM qa_plan_executions WHERE id='carried-cursor'"
        ).fetchone()[0]
        == "waiting"
    )
    assert (
        test_db.execute(
            "SELECT retracted_at FROM qa_requirements WHERE id=%s", (requirement,)
        ).fetchone()[0]
        is None
    )
    third = "run-takeover-recovery"
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,created_at) SELECT %s,project_id,flow,target_tier,"
        "target_environment_id,%s,'created',created_at FROM deployment_runs WHERE id=%s",
        (third, "d" * 40, takeover_case.NEW),
    )
    assert (
        take_over_waiting_run(test_db, third, session_id=DRIVER_SESSION)
        == takeover_case.NEW
    )
    assert takeover_case._run(test_db, takeover_case.NEW)["status"] == "failed"
    assert test_db.execute(
        "SELECT deployment_run_id,state FROM qa_plan_executions WHERE id='carried-cursor'"
    ).fetchone() == (third, "waiting")
    assert test_db.execute(
        "SELECT deployment_run_id,retracted_at FROM qa_requirements WHERE id=%s",
        (requirement,),
    ).fetchone() == (third, None)
    test_db.rollback()
