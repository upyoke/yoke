"""Deployment runner dispatch for scoped QA stages."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)


def dispatch_deployment_qa_stage(
    stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Materialize and gate every subject; ``-4`` means durable QA wait."""
    conn = connect()
    try:
        if stage.get("scope") == "item":
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
                waiting.extend(f"{label}: {reason}" for reason in status["reasons"])
        if waiting:
            return -4, "; ".join(waiting)
        return 0, ""
    finally:
        conn.close()


__all__ = ["dispatch_deployment_qa_stage"]
