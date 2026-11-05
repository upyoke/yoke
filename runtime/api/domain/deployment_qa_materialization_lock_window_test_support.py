# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _original_requirement,
)

from runtime.api.domain.deployment_qa_run_sharing_test_support import (_attach)

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _seed_run,
    _stages,
)

from yoke_core.domain.deployment_qa_materialization_write import (
    write_under_run_lock,
)

from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)

STAGE = "item-qa"


class LockWindowRecorder:
    """Record statements in order, marking where the run row lock is held."""

    def __init__(self, inner):
        self._conn = inner
        self.statements: list[tuple[bool, str]] = []
        self._locked = False

    def execute(self, sql, *args, **kwargs):
        text = " ".join(str(sql).split())
        if "deployment_runs WHERE id=%s" in text and text.endswith("FOR UPDATE"):
            self._locked = True
        self.statements.append((self._locked, text))
        return self._conn.execute(sql, *args, **kwargs)

    def commit(self):
        self._locked = False
        return self._conn.commit()

    def rollback(self):
        self._locked = False
        return self._conn.rollback()

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def counts(self) -> tuple[int, int]:
        """All statements, and those issued while the run row was locked."""
        return len(self.statements), sum(locked for locked, _ in self.statements)


def _seed(conn, run_id, first_member, members, requirements=10):
    """Two plans every member attaches, plus admitted item cases each."""
    plans = [_plan(conn, f"{run_id}-shared-{n}") for n in range(2)]
    stages = _stages(plans[0])
    stages[1].pop("cases")
    member_ids = tuple(range(first_member, first_member + members))
    _seed_run(conn, run_id=run_id, stages=stages, members=member_ids)
    for member in member_ids:
        ids = tuple(
            _original_requirement(conn, item_id=member, method_id="command")
            for _ in range(requirements)
        )
        snapshot = snapshot_member_requirements(
            conn,
            run_id=run_id,
            item_id=member,
            selection_json=requirement_selection(requirement_ids=ids),
        )
        conn.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=%s "
            "WHERE run_id=%s AND item_id=%s",
            (snapshot, run_id, member),
        )
        for plan in plans:
            _attach(conn, member, plan)
    conn.commit()
    return member_ids
