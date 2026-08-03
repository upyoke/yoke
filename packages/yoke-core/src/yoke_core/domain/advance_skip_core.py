"""Shared primitives for advance skip flows."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence, TextIO

from yoke_core.domain.workflow_runtime import WorkflowRuntime


BYPASS_SKIP_POLISH = "skip-polish"
BYPASS_SKIP_REFINE = "skip-refine"


@dataclass(frozen=True)
class _SkipRoute:
    """One definition-owned executor segment to fast-forward."""

    to_stage: str
    skipped_phase: str
    hops: tuple[str, ...]

    @property
    def allowed_hops(self) -> frozenset[str]:
        return frozenset(self.hops)


def _executor_skip_route(
    workflow: WorkflowRuntime,
    current_stage: str,
    *,
    executor_id: str,
    require_entry: bool = False,
) -> _SkipRoute:
    """Build a skip route from the pinned definition's executor binding."""
    position = workflow.stage_index(current_stage)
    if position is None:
        raise ValueError(
            f"Current stage {current_stage!r} is not declared by "
            f"{workflow.workflow_id}@{workflow.version}."
        )

    entry_stages: list[str] = []
    selected: tuple[int, int] | None = None
    for binding in workflow.executor_bindings:
        if str(binding["executor_id"]) != executor_id:
            continue
        start = workflow.stage_index(str(binding["from_stage_id"]))
        stop = workflow.stage_index(str(binding["through_stage_id"]))
        if start is None or stop is None:
            continue
        entry_stages.append(workflow.stage_ids[start])
        if start <= position < stop:
            selected = (start, stop)
            break

    if selected is None:
        raise ValueError(
            f"--skip-{executor_id} requires a stage owned by the pinned "
            f"{executor_id!r} executor; valid entry stages are "
            f"{sorted(entry_stages)!r}, got {current_stage!r}."
        )

    start, stop = selected
    if require_entry and position != start:
        raise ValueError(
            f"--skip-{executor_id} requires current status "
            f"{workflow.stage_ids[start]!r}, got {current_stage!r}."
        )

    route_stages = workflow.stage_ids[position : stop + 1]
    declared_transitions = {
        (str(edge["from_stage_id"]), str(edge["to_stage_id"]))
        for edge in workflow.definition["transitions"]
    }
    undeclared = [
        pair
        for pair in zip(route_stages, route_stages[1:])
        if pair not in declared_transitions
    ]
    if undeclared:
        raise ValueError(
            f"Pinned {workflow.workflow_id}@{workflow.version} does not declare "
            f"the skip route transitions {undeclared!r}."
        )

    hops = route_stages[1:]
    if not hops:
        raise ValueError(
            f"Pinned {workflow.workflow_id}@{workflow.version} has no stages "
            f"to skip for executor {executor_id!r} from {current_stage!r}."
        )
    skipped_phase = hops[0] if position == start else current_stage
    return _SkipRoute(
        to_stage=route_stages[-1],
        skipped_phase=skipped_phase,
        hops=hops,
    )


def _lookup_item(item_id: int) -> tuple[str, WorkflowRuntime]:
    """Return the current stage and pinned workflow for *item_id*."""
    from yoke_core.domain.backlog_queries import _resolve_write_db_path
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect

    db_path = _resolve_write_db_path()
    conn = connect(db_path)
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {p}", (item_id,)
        ).fetchone()
        if row is not None:
            from yoke_core.domain.workflow_runtime import (
                load_item_workflow_runtime,
            )

            workflow = load_item_workflow_runtime(conn, item_id)
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"Item YOK-{item_id} not found")
    return row["status"], workflow


def _do_execute_update(
    item_id: int,
    status: str,
    out: TextIO,
    *,
    rebuild_board: bool = True,
) -> dict:
    """Run ``backlog.execute_update`` for a single status hop."""
    from yoke_core.domain.backlog import execute_update

    return execute_update(
        item_id=item_id,
        field="status",
        value=status,
        rebuild_board=rebuild_board,
        out=out,
    )


def _walk_hops(
    item_id: int,
    hops: Sequence[str],
    *,
    bypass_reason: str,
    allowlist: frozenset[str],
    out: TextIO,
) -> list[str]:
    """Walk *hops* with scoped YOKE_CLAIM_BYPASS and YOKE_STATUS_SOURCE."""
    for status in hops:
        if status not in allowlist:
            raise ValueError(
                f"Skip hop to {status!r} is not in allowlist for reason "
                f"{bypass_reason!r} - refusing to bypass claim verification."
            )

    prev_bypass = os.environ.get("YOKE_CLAIM_BYPASS")
    prev_source = os.environ.get("YOKE_STATUS_SOURCE")

    os.environ["YOKE_CLAIM_BYPASS"] = bypass_reason
    os.environ["YOKE_STATUS_SOURCE"] = bypass_reason

    written: list[str] = []
    try:
        for idx, status in enumerate(hops):
            result = _do_execute_update(
                item_id,
                status,
                out,
                rebuild_board=(idx == len(hops) - 1),
            )
            if not result.get("success"):
                error = result.get("error", "unknown error")
                raise RuntimeError(f"Skip hop to {status!r} failed: {error}")
            written.append(status)
    finally:
        if prev_bypass is None:
            os.environ.pop("YOKE_CLAIM_BYPASS", None)
        else:
            os.environ["YOKE_CLAIM_BYPASS"] = prev_bypass
        if prev_source is None:
            os.environ.pop("YOKE_STATUS_SOURCE", None)
        else:
            os.environ["YOKE_STATUS_SOURCE"] = prev_source

    return written
