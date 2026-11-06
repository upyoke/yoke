"""Gate scoped QA on its serving connection, then close accepted members.
Timed-out QA calls recover by HTTPS ledger replay.
"""

from __future__ import annotations

from yoke_core.domain.deployment_qa_transaction_recovery import rollback_after_error
from yoke_core.domain.deployment_qa_configuration_refusal import (
    qa_stage_error,
)
from yoke_core.domain.deployment_qa_dispatch_inputs import (
    dispatch_input_operation,
    run_context,
)

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.schema_read_scope import composition_operation
from yoke_core.domain.deployment_run_membership_removals import removed_item_ids
from yoke_core.domain import deployment_run_item_qa_membership as item_qa
from yoke_core.domain.deployment_qa_stage_prerequisites import prior_stage_refusals_once
from yoke_core.domain.deployment_qa_plan_group_dispatch import plan_group_writer
from yoke_core.domain.deployment_qa_dispatch_gating import gate_members

DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION = "deployment_runs.qa_stage.dispatch"


@composition_operation
@dispatch_input_operation
@prior_stage_refusals_once
def materialize_and_gate_deployment_qa_stage(
    conn: Any, stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Materialize and gate every subject; ``-4`` means durable QA wait."""
    from yoke_core.domain.deployment_qa_dispatch_inputs import prepare_release_inputs

    project_id, target_tier, revision = run_context(conn, run_id)
    if stage.get("scope") == "item":
        rows = conn.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
            (run_id,),
        ).fetchall()
        members = [
            int(row["item_id"] if hasattr(row, "keys") else row[0]) for row in rows
        ]
        if not members and not removed_item_ids(conn, run_id):
            refusal = item_qa.memberless_item_qa_refusal(conn, run_id)
            return (1, refusal) if refusal else (0, item_qa.NO_MEMBER_OWES_TARGET)
    else:
        members = [None]
    if stage.get("scope") == "item":
        from yoke_core.domain.workflow_status_queries import terminal_items_sql

        closed = {
            int(row[0])
            for row in conn.execute(
                "SELECT m.item_id FROM deployment_run_items m JOIN items i ON i.id=m.item_id "
                f"WHERE m.run_id=%s AND {terminal_items_sql(conn)}",
                (run_id,),
            ).fetchall()
        }
        members = [member for member in members if member not in closed]
    from yoke_core.domain.deployment_qa_dispatch_preparation import prepare_members

    try:
        prepare_release_inputs(conn, stage, run_id=run_id)
        errors = prepare_members(
            conn,
            stage,
            run_id=run_id,
            members=members,
            then=plan_group_writer(conn, stage, run_id=run_id),
        )
    except (LookupError, ValueError) as exc:
        rollback_after_error(conn, exc)
        return qa_stage_error(exc, run_id=run_id, stage_name=str(stage.get("name")))
    return gate_members(
        conn,
        stage,
        run_id=run_id,
        members=members,
        errors=errors,
        project_id=project_id,
        target_tier=target_tier,
        revision=revision,
    )


def dispatch_deployment_qa_stage(
    stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Step-runner adapter for one scoped QA stage over the connection-keyed
    transport (local handler when admin-bootstrapped, else relayed). Only the
    stage name crosses the wire; the handler re-derives it from the stored flow.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
    call_dispatcher = get_structured_dispatch().call_dispatcher
    from yoke_core.domain.deploy_pipeline_unknown_outcome import (
        redispatch_after_connection_loss,
    )

    # Lost idempotent dispatches retry, then stop the driver resumably.
    response = redispatch_after_connection_loss(
        lambda request_id: call_dispatcher(
            request_id=request_id,
            function_id=DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
            target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
            payload={"stage_name": str(stage.get("name") or "")},
        ),
        run_id=run_id,
        function_id=DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
    )
    if not response.success:
        message = response.error.message if response.error else "request failed"
        return 1, (
            f"deployment QA stage {stage.get('name')!r} could not be "
            f"dispatched: {message}"
        )
    result = dict(response.result or {})
    from yoke_core.domain.deployment_run_recovery_command import qualify_commands

    code = int(result.get("code", 1))
    message = qualify_commands(str(result.get("message") or ""))
    if code == 0 and message:
        print(f"  Stage {stage.get('name')!r}: {message}")
    from yoke_core.domain.deployment_qa_pending_plans import QaDispatchResult

    if code == -4 and "pending_plans" not in result:
        from yoke_core.domain.deployment_run_recovery_command import yoke_command

        print(
            f"Serving build does not select driver QA plans; inspect the stage notice and {yoke_command()} watch deploy -- {run_id}"
        )
    return QaDispatchResult(code, message, list(result.get("pending_plans") or []))


__all__ = [
    "DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION",
    "dispatch_deployment_qa_stage",
    "materialize_and_gate_deployment_qa_stage",
]
