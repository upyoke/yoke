"""Receipt changes rebind open cases; cutover converges duplicate obligations."""

import importlib
import json

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.test_deployment_qa_successor_retry import (
    HOLDER_A,
    MEMBER,
    _seed_member_execution,
    _record,
    _take_over_and_deploy,
    _pinned_release as _pinned_release,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_plan_execution
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import (
    plan_execution_view,
    select_plan_execution,
)
from yoke_core.domain.qa_requirement_pass_currency import current_passing_requirements


def _plan_run(conn, monkeypatch, run_id):
    """Exercise the plan-run path through materialization and durable begin.

    Transport stays in-process; stop at the host boundary so the test can
    inspect the real frozen roster without executing an external command.
    """

    def call(*, function_id, **kwargs):
        scope = dict(
            deployment_run_id=run_id,
            deployment_stage="item-qa",
            deployment_member_item_id=MEMBER,
        )
        if function_id == "qa.plan.materialize":
            return materialize_deployment_qa_stage(conn, **scope)
        assert function_id == "qa.plan_execution.begin", function_id
        execution = begin_plan_execution(
            conn, **scope, actor_id="1", session_id=HOLDER_A
        )
        return plan_execution_view(conn, execution)

    monkeypatch.setattr(qa_plan_execution, "_call_plan_function", call)
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_run.execute_begun_plan",
        lambda **kwargs: kwargs["execution"],
    )
    from yoke_core.domain.project_identity import render_item_ref

    return qa_plan_execution.execute_plan(
        public_ref=render_item_ref(conn, MEMBER),
        deployment_stage="item-qa",
        project="yoke",
        actor=ActorContext(actor_id="1", session_id=HOLDER_A),
    )


@pytest.mark.parametrize("same_destination", [True, False])
def test_plan_run_rebinds_in_place_and_carries_only_matching_pass(
    test_db,
    monkeypatch,
    same_destination,
):
    execution = _seed_member_execution(test_db, monkeypatch)
    passed = int(execution["roster"][0]["requirement_id"])
    if not same_destination:
        # Change the original evidence's destination, keeping its digest honest.
        from yoke_core.domain.qa_execution_environment_target import (
            canonical_target,
            target_digest,
        )

        row = test_db.execute(
            "SELECT execution_target_json FROM qa_requirements WHERE id=%s", (passed,)
        ).fetchone()
        old = json.loads(row[0])
        old["endpoints"]["app_url"] = "https://different.example.test"
        digest = target_digest(old)
        test_db.execute(
            "UPDATE qa_requirements SET execution_target_json=%s,execution_target_digest=%s WHERE id=%s",
            (canonical_target(old), digest, passed),
        )
        test_db.commit()
    passed, _ = _record(test_db, execution, 0, "pass")
    failed, _ = _record(test_db, execution, 1, "fail")
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")
    before = select_plan_execution(test_db, execution["id"], lock=False)
    _take_over_and_deploy(test_db)
    fresh = _plan_run(test_db, monkeypatch, takeover.NEW)
    rows = test_db.execute(
        "SELECT * FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s ORDER BY id",
        (takeover.NEW, MEMBER),
    ).fetchall()
    assert [row["id"] for row in rows] == [passed, failed]
    assert {row["execution_target_digest"] for row in rows} == {
        fresh["execution_target_digest"]
    }
    assert all(row["rebound_from_target_json"] for row in rows)
    assert current_passing_requirements(test_db, [passed, failed]) == (
        {passed} if same_destination else set()
    )
    assert [r["requirement_id"] for r in fresh["requirements"]] == (
        [failed] if same_destination else [passed, failed]
    )
    frozen = select_plan_execution(test_db, execution["id"], lock=False)
    assert frozen["execution_target_digest"] == before["execution_target_digest"]
    assert frozen["roster"] == before["roster"]


@pytest.mark.parametrize("has_pass", [False, True])
def test_duplicate_cutover_prefers_completed_pass_and_is_idempotent(
    test_db, monkeypatch, has_pass
):
    execution = _seed_member_execution(test_db, monkeypatch)
    first = int(execution["roster"][0]["requirement_id"])
    from yoke_core.domain.qa_deployment_scope_schema import (
        REQUIREMENT_SCOPE_INDEX_NAMES,
    )

    for name in REQUIREMENT_SCOPE_INDEX_NAMES[1:]:
        test_db.execute(f'DROP INDEX "{name}"')
    test_db.execute(
        "CREATE UNIQUE INDEX idx_qa_requirement_deployment_member_stage_materialization "
        "ON qa_requirements(deployment_run_id,deployment_stage,deployment_member_item_id,"
        "plan_id,plan_case_key,COALESCE(host_baseline,''),execution_target_digest) "
        "WHERE deployment_run_id IS NOT NULL AND deployment_stage IS NOT NULL "
        "AND deployment_member_item_id IS NOT NULL AND plan_id IS NOT NULL"
    )
    row = dict(
        test_db.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (first,)
        ).fetchone()
    )
    row.pop("id")
    row["execution_target_digest"] = "another-receipt"
    columns = list(row)
    duplicate = test_db.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))}) RETURNING id",
        tuple(row.values()),
    ).fetchone()[0]
    if has_pass:
        test_db.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,completed_at,created_at) "
            "VALUES (%s,'worktree_run','plan_case','pass',now(),now())",
            (duplicate,),
        )
    from yoke_core.domain.qa_deployment_requirement_identity_schema import (
        ensure_requirement_scope_indexes,
    )

    ensure_requirement_scope_indexes(
        test_db
    )  # Boot must defer uniqueness until history converges.
    migration = importlib.import_module(
        "yoke_core.domain.migrations.0098_qa_requirement_case_identity"
    )
    for _ in range(2):
        migration.apply(test_db)
        migration.invariants(test_db)
        ensure_requirement_scope_indexes(test_db)
    rows = test_db.execute(
        "SELECT id,superseded_by_requirement_id,supersession_source FROM qa_requirements "
        "WHERE id=ANY(%s) ORDER BY id",
        ([first, duplicate],),
    ).fetchall()
    survivor, loser = (duplicate, first) if has_pass else (first, duplicate)
    by_id = {row["id"]: row for row in rows}
    assert by_id[loser]["superseded_by_requirement_id"] == survivor
    assert by_id[loser]["supersession_source"] == "migration"
    assert by_id[survivor]["superseded_by_requirement_id"] is None
    assert migration.MINIMUM_SERVING_VERSION == "next-release"


def test_original_pass_digest_survives_two_takeovers(test_db, monkeypatch):
    from yoke_core.domain.deployment_stage_receipts import (
        allocate_deployment_stage_receipt,
        complete_deployment_stage_receipt,
    )

    execution = _seed_member_execution(test_db, monkeypatch)
    passed, _ = _record(test_db, execution, 0, "pass")
    _record(test_db, execution, 1, "fail")
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")
    _take_over_and_deploy(test_db)
    fresh = _plan_run(test_db, monkeypatch, takeover.NEW)
    finish_plan_execution(
        test_db,
        select_plan_execution(test_db, fresh["execution_id"], lock=False),
        state="aborted",
        reason="second takeover",
    )
    third = "run-third-owner"
    test_db.execute(
        "UPDATE deployment_runs SET status='failed' WHERE id=%s", (takeover.NEW,)
    )
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,created_at,composition_frozen_at,requirement_snapshot) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,'created',"
        "now(),composition_frozen_at,requirement_snapshot FROM deployment_runs WHERE id=%s",
        (third, "d" * 40, takeover.NEW),
    )
    assert (
        takeover.take_over_waiting_run(
            test_db, third, session_id=takeover.DRIVER_SESSION
        )
        == takeover.NEW
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='executing',current_stage='deploy' WHERE id=%s",
        (third,),
    )
    receipt = allocate_deployment_stage_receipt(
        test_db,
        run_id=third,
        stage_name="deploy",
        correlation_id="third-receipt",
        target_kind="persistent_environment",
        executor="test",
    )
    complete_deployment_stage_receipt(
        test_db,
        run_id=third,
        receipt_id=int(receipt["id"]),
        correlation_id="third-receipt",
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage="d" * 40,
        executor_receipt="test://third-ready",
    )
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s", (third,)
    )
    test_db.commit()
    again = _plan_run(test_db, monkeypatch, third)
    row = test_db.execute(
        "SELECT rebound_from_digest,execution_target_digest FROM qa_requirements WHERE id=%s",
        (passed,),
    ).fetchone()
    assert row["rebound_from_digest"] == execution["execution_target_digest"]
    assert row["execution_target_digest"] == again["execution_target_digest"]
    assert row["execution_target_digest"] != fresh["execution_target_digest"]
    assert current_passing_requirements(test_db, [passed]) == {passed}


def test_failed_case_keeps_its_correction_pointer_after_rebinding(test_db, monkeypatch):
    from yoke_core.domain.qa_plan_rematerialize_deployment import (
        rematerialize_for_deployment_stage,
    )

    execution = _seed_member_execution(test_db, monkeypatch)
    _record(test_db, execution, 0, "pass")
    failed, _ = _record(test_db, execution, 1, "fail")
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions='Corrected probe' WHERE case_key='retried-fail'"
    )
    refreshed = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=execution["deployment_run_id"],
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )
    [correction] = refreshed["created_requirement_ids"]
    _take_over_and_deploy(test_db)
    _plan_run(test_db, monkeypatch, takeover.NEW)
    row = test_db.execute(
        "SELECT replacement_requirement_id,execution_target_digest FROM qa_requirements WHERE id=%s",
        (failed,),
    ).fetchone()
    target = test_db.execute(
        "SELECT execution_target_digest FROM qa_requirements WHERE id=%s", (correction,)
    ).fetchone()[0]
    assert row["replacement_requirement_id"] == correction
    assert row["execution_target_digest"] == target
