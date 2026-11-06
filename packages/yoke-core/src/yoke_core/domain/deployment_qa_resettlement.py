"""Credit durable QA completion when its caller retries settlement."""

from typing import Any, Mapping

from psycopg.errors import LockNotAvailable, QueryCanceled

from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.deployment_runs_lock import DeploymentRunBusy


class QaSettlementPending(QaPlanExecutionStateError):
    """Completion is durable; bounded settlement must be retried."""

    code = "qa_settlement_pending"


def completed_replay(request: Any, execution: Mapping[str, Any]) -> bool:
    return execution.get("state") == "completed" and request.function in {
        "qa.plan_execution.complete",
        "qa.plan_review.submit",
    }


def terminal_replay_allowed(conn: Any, request: Any) -> bool:
    """Only the same owner may retry a completed terminal item's credit."""
    from yoke_core.domain.item_terminal_resources import item_is_terminal
    from yoke_core.domain.qa_execution_request_identity import resolve_execution_request
    from yoke_core.domain.qa_plan_execution_store import (
        select_plan_execution,
        same_owner,
    )

    if request.function not in {"qa.plan_execution.complete", "qa.plan_review.submit"}:
        return False
    execution = select_plan_execution(
        conn, str(request.payload.get("execution_id") or ""), lock=False
    )
    if not completed_replay(request, execution) or not same_owner(
        execution, actor_id=request.actor.actor_id, session_id=request.actor.session_id
    ):
        return False
    resolve_execution_request(conn, request, execution)
    item = execution.get("deployment_member_item_id") or execution.get("item_id")
    return item is not None and item_is_terminal(conn, int(item)) is True


def resettle_execution(conn: Any, execution: Mapping[str, Any]) -> dict | None:
    """Retry the existing post-commit settlement with its existing lock order."""
    from yoke_core.domain.deployment_qa_stage_settlement import settle_execution

    try:
        return settle_execution(conn, execution)
    except (ValueError, LockNotAvailable, QueryCanceled, DeploymentRunBusy) as exc:
        if not isinstance(
            exc, (LockNotAvailable, QueryCanceled, DeploymentRunBusy)
        ) and not str(exc).startswith(
            ("qa_ownership_busy:", "qa_execution_owner_changed:")
        ):
            raise
        conn.rollback()  # Completion was committed before this attempt began.
        raise QaSettlementPending(
            "qa_settlement_pending: the QA completion is saved; release credit "
            "is pending because bounded settlement was busy. Rerun the same "
            "command with the same execution ID to credit it; no steering "
            "re-drive is needed"
        ) from None


def resettle_stage(
    conn: Any, *, run_id: str, stage: str, member: int | None = None
) -> None:
    """Retry completed evidence before a nothing-owed or close-out response.

    Call only at a command boundary, before acquiring write locks. Settlement
    owns its post-commit transaction; read-only acceptance readers stay pure.
    """
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    rows = conn.execute(
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND state IN ('completed','aborted','error') "
        "AND (%s::bigint IS NULL OR deployment_member_item_id=%s OR deployment_member_item_id IS NULL) "
        "ORDER BY created_at DESC,id",
        (run_id, stage, member, member),
    ).fetchall()
    conn.commit()  # End unlocked reads before membership/run/execution lock order.
    for row in rows:
        execution = select_plan_execution(conn, str(row[0]), lock=False)
        resettle_execution(conn, execution)
        conn.commit()


def resettle_item(conn: Any, *, run_id: str, item_id: int) -> None:
    from yoke_core.domain.deployment_qa_run_acceptance import (
        pinned_stages,
        _is_qa_stage,
    )

    if conn.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (run_id, item_id),
    ).fetchone() is None:
        return
    for stage in pinned_stages(conn, run_id):
        if _is_qa_stage(stage):
            resettle_stage(
                conn, run_id=run_id, stage=str(stage["name"]), member=item_id
            )
