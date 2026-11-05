"""Successor dispatch refreshes inherited obligations, preserving frozen work."""

import json

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.test_deployment_qa_successor_receipt import _arrive
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain import deployment_qa_stage_materialization as materialization
from yoke_core.domain.deployment_qa_dispatch_preparation import prepare_members
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution


def _rows(conn, table, where, params):
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE {where} ORDER BY id", params
        ).fetchall()
    ]


def test_takeover_dispatch_rebinds_once_without_restarting_execution(
    test_db, monkeypatch
):
    cases = takeover._seed_old(test_db, run_qa=False)
    takeover._close_passed(test_db)
    requirement = cases[takeover.WAITING]
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=takeover.OLD,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=takeover.WAITING,
        actor_id="1",
        session_id=takeover.DRIVER_SESSION,
    )
    attempt = record_case_verdict(test_db, requirement, "fail", evidence=True)
    attempts = _rows(test_db, "qa_runs", "id=%s", (attempt,))
    artifacts = _rows(test_db, "qa_artifacts", "qa_run_id=%s", (attempt,))
    original = _rows(test_db, "qa_requirements", "id=%s", (requirement,))[0]
    frozen = _rows(test_db, "qa_plan_executions", "id=%s", (execution["id"],))[0]
    takeover._seed_new(test_db)
    takeover._contains(monkeypatch)
    assert takeover._take_over(test_db) == takeover.OLD
    _arrive(test_db, ready=True)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
        (ITEM_QA_STAGE, takeover.NEW),
    )
    test_db.commit()
    stage = json.loads(
        test_db.execute(
            "SELECT stages FROM deployment_flows WHERE id=%s",
            (f"flow-{takeover.OLD}",),
        ).fetchone()[0]
    )[1]
    # Suppress only the external owner handoff; materialization and gates run.
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_failure_handoff.notify_member_qa_failure",
        lambda *a, **k: "held",
    )
    calls = []
    real = materialization.materialize_deployment_qa_stage

    def materialize(*args, **kwargs):
        calls.append(kwargs["deployment_member_item_id"])
        return real(*args, **kwargs)

    monkeypatch.setattr(materialization, "materialize_deployment_qa_stage", materialize)
    assert (
        materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=takeover.NEW)[0]
        == -4
    )
    refreshed = _rows(
        test_db, "qa_requirements", "deployment_run_id=%s", (takeover.NEW,)
    )
    assert len(refreshed) == 1
    row = refreshed[0]
    assert row["id"] == requirement
    target = json.loads(row["execution_target_json"])
    assert target["deployment"]["run_id"] == takeover.NEW
    assert target["observation"]["observed_release_lineage"] == takeover.NEW_LINEAGE
    assert target["deployment"]["release_lineage"] == takeover.NEW_LINEAGE
    assert row["rebound_at"] is not None
    assert row["rebound_from_target_json"] == original["execution_target_json"]
    assert row["created_at"] == original["created_at"]
    moved = _rows(test_db, "qa_plan_executions", "id=%s", (execution["id"],))[0]
    assert moved["deployment_run_id"] == takeover.NEW
    for key in ("created_at", "execution_target_json", "execution_target_digest"):
        assert moved[key] == frozen[key]
    assert _rows(test_db, "qa_runs", "id=%s", (attempt,)) == attempts
    assert _rows(test_db, "qa_artifacts", "qa_run_id=%s", (attempt,)) == artifacts

    counting = CountingConnection(test_db)
    assert (
        materialize_and_gate_deployment_qa_stage(counting, stage, run_id=takeover.NEW)[
            0
        ]
        == -4
    )
    assert calls == [takeover.WAITING]
    assert (
        _rows(test_db, "qa_requirements", "deployment_run_id=%s", (takeover.NEW,))
        == refreshed
    )
    assert not any(
        sql.startswith(("UPDATE qa_requirements", "INSERT INTO qa_requirements"))
        for sql in counting.statements
    )


@pytest.mark.parametrize("excluded", ["retracted", "superseded", "shared", "unbound"])
def test_ineligible_stale_target_does_not_trigger_materialization(
    test_db, monkeypatch, excluded
):
    cases = takeover._seed_old(test_db, run_qa=False)
    requirement = cases[takeover.WAITING]
    row = _rows(test_db, "qa_requirements", "id=%s", (requirement,))[0]
    target = json.loads(row["execution_target_json"])
    target["deployment"]["run_id"] = "another-run"
    if excluded == "shared":
        target["deployment"]["shared_plan"] = {"group_id": "frozen-group"}
    test_db.execute(
        "UPDATE qa_requirements SET execution_target_json=%s WHERE id=%s",
        (json.dumps(target), requirement),
    )
    if excluded == "retracted":
        test_db.execute(
            "UPDATE qa_requirements SET retracted_at=now() WHERE id=%s", (requirement,)
        )
    elif excluded == "superseded":
        test_db.execute(
            "UPDATE qa_requirements SET superseded_by_requirement_id=%s WHERE id=%s",
            (cases[takeover.PASSED], requirement),
        )
    elif excluded == "unbound":
        test_db.execute(
            "UPDATE qa_requirements SET execution_target_digest=NULL WHERE id=%s",
            (requirement,),
        )

    def unexpected(*args, **kwargs):
        pytest.fail("ineligible requirement triggered materialization")

    monkeypatch.setattr(materialization, "materialize_deployment_qa_stage", unexpected)
    assert (
        prepare_members(
            test_db,
            {"name": ITEM_QA_STAGE},
            run_id=takeover.OLD,
            members=[takeover.WAITING],
        )
        == {}
    )
