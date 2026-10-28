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
        "yoke_core.domain.deployment_qa_stage_dispatch.notify_stage_wait",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_dispatch_wait_notice.notify_item_scoped_qa_wait",
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


def test_wait_fingerprint_tracks_execution_completion_and_new_attempts(test_db):
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
    from runtime.api.domain.test_steering_fleet_report_deployment_run_facts import (
        _record_verdict,
    )

    _record_verdict(test_db, requirement_id=requirement, verdict="fail")
    assert run_qa_fingerprint(test_db, "run-progress", include_progress=True) != after


def test_member_closeout_reads_the_acceptance_just_written(test_db, monkeypatch):
    from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_active

    stage = _seed(test_db, "run-closeout-current", (9201,))
    execution = begin_plan_execution(
        test_db,
        deployment_run_id="run-closeout-current",
        deployment_stage="item-qa",
        deployment_member_item_id=9201,
        actor_id="2",
        session_id="closeout-test",
    )
    _complete_case(test_db, execution)
    closed = []

    def close(conn, **kwargs):
        assert not presentation_active()
        closed.extend(kwargs["item_ids"])

    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_member_acceptance_notice.notify_items_qa_accepted",
        close,
    )
    assert (
        materialize_and_gate_deployment_qa_stage(
            test_db, stage, run_id="run-closeout-current"
        )[0]
        == 0
    )
    assert closed == [9201]


class _FetchedBytes(CountingConnection):
    """Count statements and the bytes each one returns."""

    def __init__(self, inner):
        super().__init__(inner)
        self.fetched = 0

    def execute(self, sql, *args, **kwargs):
        cursor = super().execute(sql, *args, **kwargs)
        owner = self

        class Cursor:
            def fetchall(self):
                rows = cursor.fetchall()
                owner.fetched += sum(len(repr(tuple(row))) for row in rows)
                return rows

            def fetchone(self):
                row = cursor.fetchone()
                owner.fetched += len(repr(tuple(row))) if row is not None else 0
                return row

            def __iter__(self):
                return iter(self.fetchall())

            def __getattr__(self, name):
                return getattr(cursor, name)

        return Cursor()


def _accept(conn, run_id, members):
    from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

    for member in members:
        execution = begin_plan_execution(
            conn,
            deployment_run_id=run_id,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
            actor_id="2",
            session_id="per-member-bound",
        )
        _complete_case(conn, execution)


def test_dispatch_cost_per_member_does_not_grow_with_the_run(test_db):
    """Production-sized frozen snapshots once moved N times per member."""
    per_member = []
    for run_id, members in [
        ("run-bound-small", tuple(range(9301, 9303))),
        ("run-bound-large", tuple(range(9401, 9411))),
    ]:
        stage = _seed(test_db, run_id, members, materialized=False)
        test_db.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=jsonb_set("
            "requirement_snapshot::jsonb,'{pad}',to_jsonb(repeat('x',20000)))::text "
            "WHERE run_id=%s",
            (run_id,),
        )
        test_db.commit()
        costs = []
        for step in ("first", "repeat", "accepted"):
            if step == "accepted":
                _accept(test_db, run_id, members[: len(members) // 2])
            conn = _FetchedBytes(test_db)
            materialize_and_gate_deployment_qa_stage(conn, stage, run_id=run_id)
            costs.append((conn.count / len(members), conn.fetched / len(members)))
        per_member.append(costs)
    for (small_count, small_bytes), (large_count, large_bytes) in zip(*per_member):
        assert large_count <= small_count * 1.25, per_member
        assert large_bytes <= small_bytes * 1.25, per_member
