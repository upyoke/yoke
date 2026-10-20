"""A dispatch shares run-wide gate reads across all its members."""

import pytest

from runtime.api.fixtures.statement_counter import CountingConnection
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.handlers.deployment_run_execution import _member_rows


def _seed(conn, run_id, members, *, materialized=True):
    stages = _stages(_plan(conn, run_id))
    _seed_run(conn, run_id=run_id, stages=stages, members=members)
    for member in members if materialized else ():
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=run_id,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
    return stages[1]


@pytest.mark.parametrize("materialized", [False, True])
def test_dispatch_run_wide_read_counts_stay_constant(
    test_db, monkeypatch, materialized
):
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_dispatch._notify_stage_wait",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_dispatch.notify_item_scoped_qa_wait",
        lambda *a, **k: None,
    )
    counts = []
    for run_id, members in [
        ("run-small", (8801, 8802)),
        ("run-large", tuple(range(8901, 8911))),
    ]:
        stage = _seed(test_db, run_id, members, materialized=materialized)
        conn = CountingConnection(test_db)
        code, _ = materialize_and_gate_deployment_qa_stage(conn, stage, run_id=run_id)
        assert code == -4
        wide = {
            sql: n
            for sql, n in conn.statements.items()
            if any(
                fragment in sql
                for fragment in (
                    "FROM qa_plan_executions WHERE deployment_run_id IN",
                    "FROM deployment_runs dr JOIN deployment_flows",
                    "FROM qa_requirements WHERE deployment_run_id IN",
                    "FROM qa_plan_item_attachments a LEFT JOIN",
                )
            )
        }
        assert wide
        assert all(n <= 2 for n in wide.values()), wide
        counts.append(len(wide))
    assert counts[0] == counts[1]


def test_execution_context_member_reads_are_batched(test_db):
    _seed(test_db, "run-context-many", tuple(range(9001, 9011)))
    conn = CountingConnection(test_db)
    members = _member_rows("run-context-many", connection=conn)
    assert len(members) == 10
    assert conn.count <= 4, conn.statements
    assert all(member["public_ref"].startswith("YOK-") for member in members)


def test_wait_fingerprint_tracks_execution_completion_and_verdict_updates(test_db):
    from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
    from yoke_core.domain.deployment_run_qa_fingerprint import run_qa_fingerprint

    _seed(test_db, "run-progress", (9101,))
    execution = begin_plan_execution(
        test_db,
        deployment_run_id="run-progress",
        deployment_stage="item-qa",
        deployment_member_item_id=9101,
        actor_id="2",
        session_id="fingerprint-test",
    )
    before = run_qa_fingerprint(test_db, "run-progress", include_progress=True)
    requirement = _complete_case(test_db, execution)
    after = run_qa_fingerprint(test_db, "run-progress", include_progress=True)
    assert before != after
    test_db.execute(
        "UPDATE qa_runs SET verdict='fail' WHERE qa_requirement_id=%s", (requirement,)
    )
    assert run_qa_fingerprint(test_db, "run-progress", include_progress=True) != after
