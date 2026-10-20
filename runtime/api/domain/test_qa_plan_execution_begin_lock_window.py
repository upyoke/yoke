"""Beginning a member's shared QA walk holds the run row lock only to write.

Every per-member read happens before ``deployment_runs`` is locked, so the
statements issued while the lock is held stay the same whether the run has
three members or thirty, and a change committed between that read and the
lock is still honoured.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

SMALL = ("run-begin-lock-small", tuple(range(9601, 9604)))
LARGE = ("run-begin-lock-large", tuple(range(9701, 9731)))


class LockWindowRecorder(CountingConnection):
    """Keep statement order, so a test can read what ran under the run lock."""

    def __init__(self, inner: Any) -> None:
        super().__init__(inner)
        self.log: list[str] = []

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        self.log.append(" ".join(str(sql).split()))
        return super().execute(sql, *args, **kwargs)

    def commit(self) -> None:
        self.log.append("COMMIT")
        self._conn.commit()

    def rollback(self) -> None:
        self.log.append("ROLLBACK")
        self._conn.rollback()

    def locked(self) -> list[str]:
        """Statements issued while a ``deployment_runs`` row lock was held."""
        held, inside = [], False
        for statement in self.log:
            if statement in {"COMMIT", "ROLLBACK"}:
                inside = False
                continue
            if inside:
                held.append(statement)
            elif statement.startswith(
                "SELECT status FROM deployment_runs WHERE id=%s FOR UPDATE"
            ) or statement.startswith(
                "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE"
            ):
                inside = True
        return held


def _seed(conn, run_id, members):
    plan_id = _plan(conn, f"shared-{run_id}")
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(conn, run_id=run_id, stages=stages, members=members)
    for member in members:
        conn.execute(
            "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,"
            "qa_phase,attached_at) VALUES (%s,%s,'release','post_deploy',"
            "'2026-10-14T00:00:00Z')",
            (member, plan_id),
        )
    conn.commit()
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=members[0],
    )


def _begin(conn, run_id, member):
    return begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id="begin-lock-window",
    )


def _locked_statements(conn, run_id, members):
    _seed(conn, run_id, members)
    recorder = LockWindowRecorder(conn)
    execution = _begin(recorder, run_id, members[1])
    assert execution["deployment_member_item_id"] is None
    assert execution["requesting_member_item_id"] == members[1]
    return recorder.locked()


def test_statements_under_the_run_lock_do_not_grow_with_members(test_db):
    small = _locked_statements(test_db, *SMALL)
    large = _locked_statements(test_db, *LARGE)
    assert small, "beginning the execution must still lock the run to write"
    grown = Counter(large) - Counter(small)
    assert len(large) == len(small), "\n".join(
        f"{count} more: {statement[:160]}" for statement, count in grown.items()
    )


def test_an_execution_begun_between_read_and_lock_is_honoured(test_db, monkeypatch):
    from runtime.api.fixtures.pg_testdb import connect_test_database
    from yoke_core.domain import qa_plan_execution_begin

    run_id, members = SMALL
    _seed(test_db, run_id, members)
    admit = qa_plan_execution_begin.admit_member
    other = connect_test_database(test_db.info.dbname)
    raced: list[dict] = []

    def begin_elsewhere_then_admit(*args, **kwargs):
        if not raced:
            raced.append({})
            raced[0] = begin_plan_execution(
                other,
                deployment_run_id=run_id,
                deployment_stage="item-qa",
                deployment_member_item_id=members[0],
                actor_id="3",
                session_id="other-session",
            )
        return admit(*args, **kwargs)

    monkeypatch.setattr(
        qa_plan_execution_begin, "admit_member", begin_elsewhere_then_admit
    )
    try:
        result = _begin(test_db, run_id, members[1])
    finally:
        other.close()
    assert raced and raced[0]["session_id"] == "other-session"
    assert result["state"] == "waiting"
    assert result["shared_execution_wait"]["execution_id"] == raced[0]["id"]
    assert result["shared_execution_wait"]["owner_session_id"] == "other-session"
    rows = test_db.execute(
        "SELECT session_id FROM qa_plan_executions WHERE deployment_run_id=%s",
        (run_id,),
    ).fetchall()
    assert [row[0] for row in rows] == ["other-session"]
