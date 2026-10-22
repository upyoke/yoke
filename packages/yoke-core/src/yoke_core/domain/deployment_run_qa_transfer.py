"""Move existing QA ownership without changing execution or evidence state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.qa_execution_environment_target import canonical_target


def transfer_qa_on(
    conn: Any,
    *,
    old_id: str,
    new_id: str,
    moving: set[int],
    projection: Any,
) -> None:
    """Transfer private, attached shared, and run QA on the caller's transaction.

    The caller holds both runs and their membership stable. Captures, reviews,
    leases and queue positions reference the unchanged requirement/execution IDs.
    Historical dispositions and hashed snapshots are deliberately untouched.
    """
    remaining = {int(row["item_id"]) for row in projection.members()} - moving
    shared_moves: dict[tuple[str, str], bool] = {}

    def moves(row: Mapping) -> bool:
        member = row["deployment_member_item_id"]
        if member is not None:
            return int(member) in moving
        raw = row["execution_target_json"]
        target = dict(raw) if isinstance(raw, Mapping) else json.loads(str(raw or "{}"))
        shared = (target.get("deployment") or {}).get("shared_plan")
        if not shared:
            return True
        key = (str(row["deployment_stage"]), canonical_target(target))
        if key not in shared_moves:
            shared_moves[key] = projection.attached(
                key[0], int(shared["plan_id"]), without=remaining, target=target
            )
        return shared_moves[key]

    with savepoint(conn, "transfer_deployment_qa", owns=False):
        # Execution first matches result/review writes, which lock their cursor
        # before their requirements. One set read/write per table, not per case.
        for table in ("qa_plan_executions", "qa_requirements"):
            rows = query_rows(
                conn,
                f"SELECT id,deployment_stage,deployment_member_item_id,"
                f"execution_target_json FROM {table} "
                "WHERE deployment_run_id=%s ORDER BY id FOR UPDATE",
                (old_id,),
            )
            ids = [row["id"] for row in rows if moves(row)]
            if ids:
                conn.execute(
                    f"UPDATE {table} SET deployment_run_id=%s "
                    "WHERE deployment_run_id=%s AND id=ANY(%s)",
                    (new_id, old_id, ids),
                )
