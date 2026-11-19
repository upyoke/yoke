"""A plan execution waits in host lines before its owning run opens its stage.

A takeover moves a ``waiting`` deployment-stage execution to the successor
run, which may still be before that QA stage. Its resume would refuse
``qa_item_stage_not_open``, so serving it a host only wakes it to release the
turn. Such a wait keeps its place in every line but is passed over
(``qa_host_idle_waiters.serving_line``), and a released reservation held for
it returns it to ``waiting`` instead of aborting it
(``qa_host_turn_release``). When the stage opens, the stage-wait notice sends
its owner to ``yoke qa plan run``, which re-freezes the same execution and
re-serves each host at its original place.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import marker as _p


def execution_stage_unopened(conn: Any, execution_id: str | None) -> bool:
    """True while *execution_id*'s owning run has not opened its QA stage."""
    from yoke_core.domain.deployment_qa_stage_contract import stage_not_opened

    if not execution_id:
        return False
    row = query_one(
        conn,
        "SELECT e.deployment_stage,r.status,r.current_stage,r.composition_frozen_at "
        "FROM qa_plan_executions e JOIN deployment_runs r ON r.id=e.deployment_run_id "
        f"WHERE e.id={_p(conn)} AND e.deployment_stage IS NOT NULL",
        (str(execution_id),),
    )
    return row is not None and stage_not_opened(dict(row), str(row["deployment_stage"]))


__all__ = ["execution_stage_unopened"]
