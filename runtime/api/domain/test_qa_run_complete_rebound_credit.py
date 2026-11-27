"""A pass started before release takeover credits the successor when it completes."""

import json

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.machine_qa_host_test_support import machine_case_request
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.deployment_qa_requirement_target_refresh import rebind_subject
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on
from yoke_core.domain.qa_requirement_pass_currency import (
    has_current_passing_run,
    recorded_execution_target_digest,
    stamp_executed_method_config,
)
from yoke_core.domain.qa_run_verdict_record import insert_qa_run
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.handler_registry_runtime import ensure_handlers_registered
from yoke_core.domain.yoke_function_registry import lookup

MEMBER = takeover.WAITING


def _case(conn):
    """The member case wherever takeover moved it."""
    row = conn.execute(
        "SELECT * FROM qa_requirements WHERE deployment_member_item_id=%s "
        "AND deployment_stage=%s AND superseded_by_requirement_id IS NULL",
        (MEMBER, ITEM_QA_STAGE),
    ).fetchone()
    return dict(row)


@pytest.fixture
def started(test_db):
    """A member case whose run started on the predecessor's target."""
    plan = create_smoke_plan(test_db, project="yoke", slug="late-pass-credit")
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=takeover.OLD,
        project="yoke",
        stages=item_qa_stage_definitions(plan),
        members=(MEMBER,),
        lineage=takeover.OLD_LINEAGE,
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=takeover.OLD,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )
    requirement = takeover._requirement(test_db, takeover.OLD, ITEM_QA_STAGE, MEMBER)
    frozen = test_db.execute(
        "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
        (requirement,),
    ).fetchone()[0]
    run_id = _start(test_db, requirement)
    return {
        "requirement": requirement,
        "run_id": run_id,
        "frozen": json.loads(frozen),
    }


def _start(conn, requirement):
    """Record an attempt that started on the requirement's current target."""
    row = conn.execute(
        "SELECT method_config,execution_target_digest FROM qa_requirements WHERE id=%s",
        (requirement,),
    ).fetchone()
    started_at = parse_instant("2026-11-27T04:17:08Z")
    run_id = insert_qa_run(
        conn,
        qa_requirement_id=requirement,
        performed_by="worktree_run",
        qa_kind="plan_case",
        verdict=None,
        raw_result=stamp_executed_method_config(
            "{}",
            row["method_config"],
            execution_target_digest=row["execution_target_digest"],
        ),
        started_at=started_at,
        completed_at=None,
        created_at=started_at,
    ).run_id
    conn.commit()
    return int(run_id)


def _take_over_and_rebind(conn, frozen, *, same_destination):
    takeover._seed_new(conn)
    transfer_qa_on(conn, old_id=takeover.OLD, new_id=takeover.NEW, moving={MEMBER})
    conn.execute(
        "UPDATE deployment_runs SET supersedes_run_id=%s WHERE id=%s",
        (takeover.OLD, takeover.NEW),
    )
    target = {
        **frozen,
        "deployment": {
            **frozen["deployment"],
            "run_id": takeover.NEW,
            "release_lineage": takeover.NEW_LINEAGE,
        },
    }
    if not same_destination:
        target["endpoints"] = {
            **target["endpoints"],
            "app_url": "https://moved.example.test",
        }
    rebound = rebind_subject(
        conn,
        subject={
            "id": takeover.NEW,
            "stage": {"name": ITEM_QA_STAGE},
            "member_item_id": MEMBER,
        },
        target=target,
    )
    conn.commit()
    return rebound


def _complete(requirement, run_id, verdict="pass"):
    ensure_handlers_registered()
    handler = lookup("qa.run.complete").handler
    return handler(
        machine_case_request(
            requirement,
            function="qa.run.complete",
            payload={"run_id": run_id, "verdict": verdict},
        )
    )


@pytest.mark.parametrize("same_destination", [True, False])
def test_late_pass_credits_successor_only_on_the_same_destination(
    test_db, started, same_destination
):
    requirement, run_id, frozen = (
        started["requirement"],
        started["run_id"],
        started["frozen"],
    )
    assert _take_over_and_rebind(
        test_db, frozen, same_destination=same_destination
    ) == [requirement]
    before = _case(test_db)
    assert before["rebound_at"] is not None and before["rebound_from_digest"] is None
    assert has_current_passing_run(test_db, requirement) is False

    outcome = _complete(requirement, run_id)
    assert outcome.primary_success, outcome.error

    after = _case(test_db)
    attempt = test_db.execute(
        "SELECT verdict,raw_result FROM qa_runs WHERE id=%s", (run_id,)
    ).fetchone()
    # The attempt keeps attributing its evidence to the predecessor target.
    assert attempt["verdict"] == "pass"
    assert recorded_execution_target_digest(attempt["raw_result"]) == target_digest(
        frozen
    )
    assert after["execution_target_json"] == before["execution_target_json"]
    assert has_current_passing_run(test_db, requirement) is same_destination
    assert after["rebound_from_digest"] == (
        target_digest(frozen) if same_destination else None
    )


def test_late_failure_or_superseded_attempt_earns_no_credit(test_db, started):
    requirement, run_id = started["requirement"], started["run_id"]
    _take_over_and_rebind(test_db, started["frozen"], same_destination=True)
    later = parse_instant("2026-11-27T05:00:00Z")
    newer = insert_qa_run(
        test_db,
        qa_requirement_id=requirement,
        performed_by="worktree_run",
        qa_kind="plan_case",
        verdict=None,
        raw_result="{}",
        started_at=later,
        completed_at=None,
        created_at=later,
    ).run_id
    test_db.commit()
    _complete(requirement, run_id)
    assert _case(test_db)["rebound_from_digest"] is None

    failed = _complete(requirement, int(newer), verdict="fail")
    assert failed.primary_success, failed.error
    assert _case(test_db)["rebound_from_digest"] is None
    assert has_current_passing_run(test_db, requirement) is False


def test_late_pass_settles_the_member_after_real_takeover(test_db, monkeypatch):
    """Start on the predecessor, admit the successor, then complete the pass."""
    from runtime.api.domain.deployment_qa_successor_receipt_test_support import _arrive
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        materialize_and_gate_deployment_qa_stage,
    )

    requirement = takeover._seed_old(test_db, run_qa=False)[MEMBER]
    takeover._close_passed(test_db)
    run_id = _start(test_db, requirement)
    test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES (%s,'log','text/plain',%s,now())",
        (run_id, "evidence://late-pass"),
    )
    frozen = json.loads(
        test_db.execute(
            "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
            (requirement,),
        ).fetchone()[0]
    )
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
    materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=takeover.NEW)
    rebound = _case(test_db)
    assert rebound["id"] == requirement and rebound["rebound_from_digest"] is None
    assert json.loads(rebound["rebound_from_target_json"]) == frozen

    outcome = _complete(requirement, run_id)
    assert outcome.primary_success, outcome.error

    assert _case(test_db)["rebound_from_digest"] == target_digest(frozen)
    assert has_current_passing_run(test_db, requirement)
    # Ordinary settlement accepted the member and moved the successor on.
    assert (
        test_db.execute(
            "SELECT current_stage FROM deployment_runs WHERE id=%s", (takeover.NEW,)
        ).fetchone()[0]
        != ITEM_QA_STAGE
    )
    attempt = test_db.execute(
        "SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert recorded_execution_target_digest(attempt[0]) == target_digest(frozen)


THIRD = "run-takeover-third"


def _take_over_again(conn, *, same_destination):
    """A second takeover moves the open case from the successor onto THIRD."""
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,"
        "target_environment_id,release_lineage,status,supersedes_run_id,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,"
        "'created',%s,created_at FROM deployment_runs WHERE id=%s",
        (THIRD, "d" * 40, takeover.NEW, takeover.OLD),
    )
    transfer_qa_on(conn, old_id=takeover.NEW, new_id=THIRD, moving={MEMBER})
    current = json.loads(_case(conn)["execution_target_json"])
    target = {
        **current,
        "deployment": {
            **current["deployment"],
            "run_id": THIRD,
            "release_lineage": "d" * 40,
        },
    }
    target["deployment"].pop("starting_run_id", None)
    if not same_destination:
        target["endpoints"] = {**target["endpoints"], "app_url": "https://moved.test"}
    subject = {"id": THIRD, "stage": {"name": ITEM_QA_STAGE}, "member_item_id": MEMBER}
    rebound = rebind_subject(conn, subject=subject, target=target)
    conn.commit()
    return rebound, current


def _previous_digest(conn):
    return target_digest(json.loads(_case(conn)["rebound_from_target_json"]))


@pytest.mark.parametrize("same_destination", [True, False])
def test_pass_started_on_a_credits_after_two_takeovers(
    test_db, started, same_destination
):
    requirement, run_id, frozen = (
        started["requirement"],
        started["run_id"],
        started["frozen"],
    )
    _take_over_and_rebind(test_db, frozen, same_destination=True)
    rebound, immediate = _take_over_again(test_db, same_destination=same_destination)
    assert rebound == [requirement]
    # The open attempt's own start target survives the second rebind.
    assert _previous_digest(test_db) == target_digest(
        frozen if same_destination else immediate
    )

    outcome = _complete(requirement, run_id)
    assert outcome.primary_success, outcome.error

    after = _case(test_db)
    assert after["deployment_run_id"] == THIRD
    assert has_current_passing_run(test_db, requirement) is same_destination
    assert after["rebound_from_digest"] == (
        target_digest(frozen) if same_destination else None
    )
    attempt = test_db.execute(
        "SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert recorded_execution_target_digest(attempt[0]) == target_digest(frozen)


def test_newer_attempt_on_the_immediate_target_keeps_it(test_db, started):
    requirement, run_id = started["requirement"], started["run_id"]
    _take_over_and_rebind(test_db, started["frozen"], same_destination=True)
    newer = _start(test_db, requirement)
    test_db.execute(
        "UPDATE qa_runs SET started_at=%s WHERE id=%s",
        (parse_instant("2026-11-27T05:00:00Z"), newer),
    )
    _, immediate = _take_over_again(test_db, same_destination=True)
    assert _previous_digest(test_db) == target_digest(immediate)

    _complete(requirement, run_id)
    assert _case(test_db)["rebound_from_digest"] is None
    assert has_current_passing_run(test_db, requirement) is False
