"""What a membership removal reads before it takes the run row lock.

The removal guard asks the member's item QA answer, and the QA cleanup asks
which shared groups the remaining members still attach. Both scale with the
run, so they are read here, unlocked and as one set per fact; the writer
locks the run and repeats this read only if the run's fingerprint moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.deployment_qa_materialization_projection import (
    MaterializationProjection,
)
from yoke_core.domain.deployment_qa_presentation_facts import run_presentation
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.deployment_run_composition_guard import (
    frozen_mutation_refusal,
    has_frozen_composition,
)
from yoke_core.domain.project_identity import render_item_ref


@dataclass
class RemovalRead:
    """The run's shared groups and the guard's answer, read before the lock."""

    projection: MaterializationProjection
    status: str
    # The guard's named refusal for the first member it refuses, if any.
    refusal: ValueError | None = None


def shared_group_stages(conn: Any, run_id: str) -> list[str]:
    """Stages holding memberless shared-group rows, whose owners a removal asks."""
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "qa_requirements"):
        return []
    return [
        str(row["deployment_stage"])
        for row in conn.execute(
            "SELECT DISTINCT deployment_stage FROM qa_requirements "
            "WHERE deployment_run_id=%s AND deployment_member_item_id IS NULL "
            "AND plan_id IS NOT NULL AND deployment_stage IS NOT NULL",
            (run_id,),
        ).fetchall()
    ]


def read_removal(
    conn: Any, *, run_id: str, item_ids: Iterable[int] = (), guard: bool = True
) -> RemovalRead:
    """Read the guard and shared groups for removing ``item_ids``, unlocked."""
    projection = MaterializationProjection(conn, run_id)
    row = query_one(conn, "SELECT status FROM deployment_runs WHERE id=%s", (run_id,))
    if row is None:
        raise LookupError(f"deployment run '{run_id}' not found")
    read = RemovalRead(projection, str(row["status"]))
    if guard:
        try:
            for item_id in item_ids:
                _require_removable(conn, run_id, int(item_id), read.status)
        except ValueError as exc:
            read.refusal = exc
    _read_groups(conn, run_id=run_id, projection=projection)
    return read


@presentation_operation
@run_presentation
def _read_groups(conn: Any, *, run_id: str, projection: Any) -> None:
    for stage_name in shared_group_stages(conn, run_id):
        projection.stage_groups(stage_name)


@presentation_operation
@run_presentation
def _item_qa_answer(conn: Any, *, run_id: str, **subject: Any) -> Any:
    """The member's item QA answer, its siblings read as one set per fact."""
    from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa

    return current_item_qa(conn, run_id=run_id, **subject)


def _require_removable(conn: Any, run_id: str, item_id: int, status: str) -> None:
    """Keep ordinary composition mutable; narrow frozen edits to owed item QA."""
    if status == "created":
        if has_frozen_composition(conn, run_id):
            raise ValueError(frozen_mutation_refusal(run_id, "membership")[7:])
        return
    if status not in {"executing", "failed"}:
        raise ValueError(
            f"deployment run '{run_id}' is {status}; removal is allowed only while "
            "status='created', executing at item QA, or failed at item-qa-failed. Use a later release."
        )
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages

    row = query_one(
        conn,
        "SELECT current_stage,settling_at FROM deployment_runs WHERE id=%s",
        (run_id,),
    )
    stages = pinned_stages(conn, run_id)
    stage_name = str(row["current_stage"] or "")
    if status == "failed":
        if stage_name != "item-qa-failed":
            raise ValueError(
                f"deployment run '{run_id}' failed at {stage_name!r}; removal is "
                "allowed only at item-qa-failed for a failed run. Repair the failed stage or use a later release."
            )
        stage_name = stage_name.removesuffix("-failed")
    current = next((s for s in stages if s.get("name") == stage_name), {})
    if (
        row["settling_at"]
        or current.get("step_runner") != "qa"
        or current.get("scope") != "item"
    ):
        boundary = (
            "run is at a shared run-level gate; the member is part of the shared result"
            if current.get("scope") == "run"
            and current.get("step_runner") in {"qa", "human-approval"}
            else "frozen membership cannot be removed at this boundary"
        )
        raise ValueError(
            f"run {run_id} is not at an item-scoped QA stage: {boundary}. "
            "Settle the current gate or repair settlement, then deliver the member through a later release."
        )
    if any(
        s.get("step_runner") == "human-approval"
        or (s.get("step_runner") == "qa" and s.get("scope") == "run")
        for s in stages
    ):
        raise ValueError(
            f"run {run_id} has shared run-level QA or approval; the member is part "
            "of the shared result. Settle the shared gates instead of removing it."
        )
    item = query_one(conn, "SELECT status FROM items WHERE id=%s", (item_id,))
    member = query_one(
        conn,
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (run_id, item_id),
    )
    if member is None:
        return  # The shared write reports the public non-member identity.
    if item["status"] in {"done", "cancelled", "stopped"}:
        raise ValueError(
            f"member {render_item_ref(conn, item_id)} is already closed; retain its delivery evidence."
        )
    answer = _item_qa_answer(
        conn,
        run_id=run_id,
        item_id=item_id,
        current_stage=stage_name,
        stages=stages,
    )
    if answer is None or answer.accepted:
        reason = "already settled" if answer is not None else "QA cannot be evaluated"
        raise ValueError(
            f"member {render_item_ref(conn, item_id)}: {reason}; retain its evidence and inspect `yoke deployment-runs get {run_id}`."
        )
