# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from collections import Counter

from typing import Any

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.fixtures.statement_counter import CountingConnection

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.qa_stage_execution_holders import StageRosterHeld


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
    ensure_groups(conn, run_id, "item-qa")
    conn.commit()


def _seed_stage_wide(conn, run_id, members):
    stages = _stages(_plan(conn, f"stage-wide-{run_id}"))
    stages[1]["scope"] = "run"
    _seed_run(conn, run_id=run_id, stages=stages, members=members)
    conn.commit()
    materialize_deployment_qa_stage(
        conn, deployment_run_id=run_id, deployment_stage="item-qa"
    )


def _stage_wide_begin(conn, run_id, session="begin-lock-window"):
    return begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        actor_id="2",
        session_id=session,
    )
