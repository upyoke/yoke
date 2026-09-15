"""Deployment runner dispatch for scoped QA stages."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_wake import notify_item_scoped_qa_wait


def dispatch_deployment_qa_stage(
    stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Materialize and gate every subject; ``-4`` means durable QA wait."""
    conn = connect()
    try:
        project_row = conn.execute(
            "SELECT project_id FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()
        project_id = int(
            project_row["project_id"] if hasattr(project_row, "keys") else project_row[0]
        ) if project_row else None
        item_scoped = stage.get("scope") == "item"
        if item_scoped:
            rows = conn.execute(
                "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
                (run_id,),
            ).fetchall()
            members = [
                int(row["item_id"] if hasattr(row, "keys") else row[0]) for row in rows
            ]
            if not members:
                return 1, "item-scoped QA stage has no attached run members"
        else:
            members = [None]
        waiting: list[str] = []
        for member in members:
            try:
                existing = conn.execute(
                    "SELECT 1 FROM qa_requirements WHERE deployment_run_id=%s "
                    "AND deployment_stage=%s "
                    "AND COALESCE(deployment_member_item_id,0)=%s "
                    "AND method_id IS NOT NULL LIMIT 1",
                    (run_id, str(stage["name"]), member or 0),
                ).fetchone()
                if existing is None:
                    materialize_deployment_qa_stage(
                        conn,
                        deployment_run_id=run_id,
                        deployment_stage=str(stage["name"]),
                        deployment_member_item_id=member,
                    )
                status = deployment_qa_stage_status(
                    conn,
                    run_id=run_id,
                    stage_name=str(stage["name"]),
                    member_item_id=member,
                )
            except (LookupError, ValueError) as exc:
                return 1, str(exc)
            if not status["accepted"]:
                label = f"member {member}" if member is not None else "run"
                reasons = "; ".join(status["reasons"])
                waiting.append(f"{label}: {reasons}")
                if item_scoped and member is not None and project_id is not None:
                    # A wake failure is not a QA-status failure: the stage is
                    # genuinely still waiting either way, so a notification
                    # hiccup degrades to "not woken" rather than aborting the
                    # dispatch and losing the wait result already computed.
                    try:
                        notify_item_scoped_qa_wait(
                            conn,
                            run_id=run_id,
                            stage_name=str(stage["name"]),
                            item_id=member,
                            project_id=project_id,
                            reasons=reasons,
                        )
                        conn.commit()
                    except Exception as exc:  # noqa: BLE001 - degrade, don't abort
                        conn.rollback()
                        print(
                            f"Warning: could not wake item {member}'s claim "
                            f"holder for run {run_id!r} stage "
                            f"{stage['name']!r}: {exc}"
                        )
        if waiting:
            return -4, "; ".join(waiting)
        return 0, ""
    finally:
        conn.close()


__all__ = ["dispatch_deployment_qa_stage"]
