"""A deliberate host release cancels its execution in the same transaction."""

from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.schema_common import _table_exists


def release_host_claim(
    conn: Any, claim_id: int, reason: str, *, commit: bool = True, **kwargs: Any
) -> Any:
    """Manual release is custody loss, never a successful QA completion.

    This is the holder/steering recovery boundary. Internal case handoffs and
    teardown use ordinary release and keep their own execution lifecycle.
    """
    from yoke_core.domain.coordination_claims import get_claim, release
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
    from yoke_core.domain.qa_plan_host_leases import (
        HOST_SET_REASON,
        execution_host_leases,
        release_execution_hosts,
    )

    with savepoint(conn, "_yoke_manual_host_release", owns=commit):
        claim = get_claim(conn, claim_id)
        executions = []
        if claim.target.machine_id and _table_exists(conn, "qa_plan_executions"):
            companion = (
                str(claim.reason)[len(HOST_SET_REASON) :]
                if str(claim.reason or "").startswith(HOST_SET_REASON)
                else ""
            )
            rows = query_rows(
                conn,
                "SELECT id FROM qa_plan_executions "
                f"WHERE state IN ({LIVE_PLAN_EXECUTION_SQL}) "
                "AND (machine_lease_id=%s OR CAST(id AS TEXT)=%s) ORDER BY id",
                (claim_id, companion),
            )
            executions = [lock_plan_execution(conn, str(row["id"])) for row in rows]
        from yoke_core.domain.machine_reset_debt import record_execution_reset_debt

        for execution in executions:
            leases = {
                lease.id: lease for lease in execution_host_leases(conn, execution)
            }
            primary = execution.get("machine_lease_id")
            if primary is not None:
                leases[primary] = get_claim(conn, int(primary))
            record_execution_reset_debt(conn, execution, leases.values())
        released = release(conn, claim_id, reason, commit=False, **kwargs)
        for execution in executions:
            release_execution_hosts(conn, execution, reason=reason)
            primary = execution.get("machine_lease_id")
            if primary is not None:
                release(conn, int(primary), reason, commit=False)
            # A deliberate release has already ended custody, so there is no
            # host left for cooperative abort's restoration gate to retain.
            execution["machine_lease_id"] = None
            finish_plan_execution(
                conn, execution, state="aborted", reason=reason, commit=False
            )
        if commit:
            conn.commit()
        return released
