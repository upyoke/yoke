"""Dispatch scales with unfinished members and permits concurrent settlement."""

import threading
import time

from runtime.api.domain.deployment_qa_materialization_lock_window_test_support import (
    _seed,
    STAGE,
)
from runtime.api.domain.deployment_qa_stage_execution_test_support import _complete_case
from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)


def _stage(conn, run_id):
    return next(s for s in pinned_stages(conn, run_id) if s["name"] == STAGE)


def test_closed_members_do_not_enter_the_ladder(test_db, monkeypatch):
    from yoke_core.domain import deployment_qa_stage_gate as gate

    run_id = "run-dispatch-open-members"
    members = _seed(test_db, run_id, 22001, 37, requirements=1)
    test_db.execute(
        "UPDATE items SET status='done' WHERE id=ANY(%s)", (list(members[:32]),)
    )
    test_db.execute("UPDATE items SET status='release' WHERE id=ANY(%s)", (list(members[32:]),))
    test_db.commit()
    calls = []
    real = gate.deployment_qa_stage_status

    def status(conn, **kwargs):
        calls.append(kwargs["member_item_id"])
        return real(conn, **kwargs)

    monkeypatch.setattr(gate, "deployment_qa_stage_status", status)
    started = time.monotonic()
    materialize_and_gate_deployment_qa_stage(
        test_db, _stage(test_db, run_id), run_id=run_id
    )
    assert calls == list(members[32:])
    assert time.monotonic() - started < 30
    assert (
        test_db.execute(
            "SELECT COUNT(DISTINCT deployment_member_item_id) FROM qa_requirements "
            "WHERE deployment_run_id=%s AND deployment_member_item_id IS NOT NULL",
            (run_id,),
        ).fetchone()[0]
        == 5
    )


def test_peer_verdict_does_not_reread_a_member(test_db, monkeypatch):
    from yoke_core.domain import deployment_qa_materialization_projection as projections
    from yoke_core.domain.deployment_run_qa_fingerprint import run_qa_fingerprint
    from yoke_core.domain.qa_run_verdict_record import insert_qa_run
    from yoke_core.domain.db_helpers import utc_now

    run_id = "run-dispatch-peer-progress"
    member, peer = _seed(test_db, run_id, 22101, 2, requirements=1)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=peer,
    )
    requirement = test_db.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND method_id IS NOT NULL",
        (run_id, peer),
    ).fetchone()[0]
    reads = []
    real = projections.MaterializationProjection.__init__

    def read(self, conn, run, **kwargs):
        real(self, conn, run, **kwargs)
        reads.append(kwargs.get("member_item_id"))
        if len(reads) == 1:
            now = utc_now()
            insert_qa_run(
                conn,
                qa_requirement_id=requirement,
                performed_by="agent",
                qa_kind="command",
                verdict="pass",
                verdict_reason="peer passed",
                raw_result="{}",
                started_at=now,
                completed_at=now,
                created_at=now,
            )
            conn.commit()

    monkeypatch.setattr(projections.MaterializationProjection, "__init__", read)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=member,
    )
    assert reads == [member]
    before = run_qa_fingerprint(test_db, run_id, member_item_id=member)
    test_db.execute(
        "UPDATE qa_requirements SET instructions='corrected' WHERE id=%s",
        (requirement,),
    )
    assert run_qa_fingerprint(test_db, run_id, member_item_id=member) == before


def test_acceptance_reuse_is_invalidated_by_case_correction(test_db):
    from yoke_core.domain.deployment_qa_dispatch_settled import settled_member_status
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

    run_id = "run-dispatch-acceptance-currency"
    member, _peer = _seed(test_db, run_id, 22201, 2, requirements=1)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=member,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=member,
        actor_id="2",
        session_id="member-proof-walker",
    )
    _complete_case(test_db, execution)
    kwargs = dict(run_id=run_id, stage_name=STAGE, member_item_id=member)
    assert settled_member_status(test_db, **kwargs)["accepted"]
    test_db.execute(
        "UPDATE qa_requirements SET instructions='corrected contract' "
        "WHERE deployment_run_id=%s AND method_id IS NOT NULL",
        (run_id,),
    )
    test_db.commit()
    assert settled_member_status(test_db, **kwargs) is None


def test_worker_can_settle_during_first_materialization(test_db, monkeypatch):
    from yoke_core.domain import deployment_qa_materialization_write as writes
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_runs_lock import lock_run
    from yoke_core.domain.qa_run_verdict_record import insert_qa_run
    from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config
    from yoke_core.domain.db_helpers import utc_now

    run_id = "run-dispatch-concurrent-worker"
    members = _seed(test_db, run_id, 22301, 37, requirements=1)
    test_db.execute("UPDATE items SET status='release' WHERE id=ANY(%s)", (list(members),))
    test_db.commit()
    result, threads = [], []
    real = writes._write_subject

    def settle(requirement, started):
        conn = connect()
        try:
            lock_run(conn, run_id)
            method_config = conn.execute("SELECT method_config FROM qa_requirements WHERE id=%s", (requirement,)).fetchone()[0]
            raw = stamp_executed_method_config("worker passed", method_config, conn=conn, requirement_id=requirement)
            now = utc_now()
            insert_qa_run(conn, qa_requirement_id=requirement, performed_by='agent',
                          qa_kind='command', verdict='pass', verdict_reason='worker passed',
                          raw_result=raw, started_at=now, completed_at=now, created_at=now)
            conn.commit()
            result.append(time.monotonic() - started)
        except Exception as exc:
            result.append(exc)
        finally:
            conn.close()

    def write(conn, read, **kwargs):
        answer = real(conn, read, **kwargs)
        if not threads:
            requirement = answer["created_requirement_ids"][0]
            worker = threading.Thread(
                target=settle, args=(requirement, time.monotonic())
            )
            threads.append(worker)
            worker.start()
        time.sleep(0.08)  # The cohort costs over two seconds, each lock does not.
        return answer

    monkeypatch.setattr(writes, "_write_subject", write)
    materialize_and_gate_deployment_qa_stage(
        test_db, _stage(test_db, run_id), run_id=run_id
    )
    for worker in threads:
        worker.join(timeout=3)
    assert len(result) == 1 and isinstance(result[0], float), result
    assert result[0] < 2, result


def test_rematerialization_invalidates_stored_acceptance(test_db):
    from runtime.api.domain.deployment_qa_stage_execution_test_support import _plan, _seed_run, _stages
    from yoke_core.domain.deployment_qa_dispatch_settled import settled_member_status
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
    from yoke_core.domain.qa_plan_rematerialize_deployment import rematerialize_for_deployment_stage
    from yoke_core.domain.qa_plan_management import replace_plan_cases

    run_id, member = 'run-dispatch-refreshed-acceptance', 22401
    plan = _plan(test_db, 'member-refreshed-proof')
    _seed_run(test_db, run_id=run_id, stages=_stages(plan), members=(member,))
    materialize_deployment_qa_stage(test_db, deployment_run_id=run_id,
                                  deployment_stage=STAGE, deployment_member_item_id=member)
    execution = begin_plan_execution(test_db, deployment_run_id=run_id,
                                    deployment_stage=STAGE, deployment_member_item_id=member,
                                    actor_id='2', session_id='refresh-proof-walker')
    _complete_case(test_db, execution)
    kwargs = dict(run_id=run_id, stage_name=STAGE, member_item_id=member)
    assert settled_member_status(test_db, **kwargs)['accepted']
    replace_plan_cases(test_db, plan_id=plan, cases=[{
        'case_key': 'command-smoke', 'method_id': 'command',
        'instructions': 'run the corrected contract', 'expected_outcome': 'corrected pass',
        'method_config': {'command': 'echo corrected'},
    }, {
        'case_key': 'additional-smoke', 'method_id': 'command',
        'instructions': 'run the added contract', 'expected_outcome': 'additional pass',
        'method_config': {'command': 'true'},
    }])
    refreshed = rematerialize_for_deployment_stage(test_db, deployment_run_id=run_id,
                                                  deployment_stage=STAGE,
                                                  deployment_member_item_id=member)
    assert refreshed['created_requirement_ids']
    assert settled_member_status(test_db, **kwargs) is None
