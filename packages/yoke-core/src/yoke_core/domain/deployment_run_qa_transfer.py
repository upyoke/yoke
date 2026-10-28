"""Move existing QA ownership without changing execution or evidence state."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.db_savepoint import savepoint


@contextmanager
def qa_ownership_write(conn):
    """Bound ownership locks without rolling back a caller's earlier writes."""
    from yoke_core.domain.db_backend import connection_is_postgres
    from yoke_core.domain.deployment_runs_lock import RUN_ROW_LOCK_TIMEOUT_MS
    import psycopg

    try:
        with savepoint(conn, "qa_ownership_write", owns=False):
            postgres = connection_is_postgres(conn)
            if postgres:
                previous = conn.execute(
                    "SELECT current_setting('lock_timeout')"
                ).fetchone()[0]
                conn.execute(
                    "SELECT set_config('lock_timeout', %s, true)",
                    (f"{RUN_ROW_LOCK_TIMEOUT_MS}ms",),
                )
            yield
            if postgres:
                conn.execute(
                    "SELECT set_config('lock_timeout', %s, true)", (str(previous),)
                )
    except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
        raise ValueError(
            "qa_ownership_busy: another writer held a QA ownership lock past its bound; "
            "this attempt was rolled back. Retry the same creation or completion request "
            "after the current writer finishes"
        ) from None


def transfer_qa_on(
    conn: Any,
    *,
    old_id: str,
    new_id: str,
    moving: set[int],
) -> None:
    """Transfer moving members' QA, open plan groups and run QA on the caller's transaction.

    The caller holds both runs and their membership stable. An open plan group
    moves whole, with its results and any running execution; a closed group
    stays in the run where it passed, which is what its credit names.
    Captures, reviews, leases and queue positions reference the unchanged
    requirement/execution IDs. Historical dispositions and hashed snapshots
    are deliberately untouched.
    """
    from yoke_core.domain.deployment_qa_plan_groups import group_marker, run_groups

    open_groups = {group.group_id for group in run_groups(conn, old_id) if group.open}

    def moves(row: Mapping) -> bool:
        member = row["deployment_member_item_id"]
        if member is not None:
            return int(member) in moving
        marker = group_marker(row["execution_target_json"])
        return marker is None or str(marker["group_id"]) in open_groups

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
