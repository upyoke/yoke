"""Gate scoped QA on its serving connection, then close accepted members.

Local drivers dispatch in-process; HTTPS and self-deploy drivers relay to
that control plane. Timed-out QA calls recover by HTTPS ledger replay.
"""

from __future__ import annotations

from yoke_core.domain.deployment_qa_transaction_recovery import rollback_after_error
from yoke_core.domain.deployment_qa_configuration_refusal import qa_stage_error
from yoke_core.domain.deployment_qa_dispatch_inputs import (
    dispatch_input_operation,
    run_context,
)

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.project_identity import resolve_project_slug
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.deployment_qa_presentation_reads import (
    presentation_operation,
    uncached_presentation,
)
from yoke_core.domain.deployment_qa_presentation_facts import run_presentation
from yoke_core.domain.schema_read_scope import composition_operation
from yoke_core.domain.deployment_run_membership_removals import removed_item_ids
from yoke_core.domain import deployment_run_item_qa_membership as item_qa

from yoke_core.domain.deployment_qa_result_notice import report_stage_result
from yoke_core.domain.deployment_qa_reported_results import reported_stage_results
from yoke_core.domain.deployment_qa_reported_results import sent_stage_waits
from yoke_core.domain.deployment_qa_stage_prerequisites import (
    prior_stage_refusals_once,
)
from yoke_core.domain.deployment_qa_manual_wake import (
    manual_wake_requirements,
    wake_manual_requirement_owners,
)
from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait,
    notify_run_scoped_qa_wait,
)

DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION = "deployment_runs.qa_stage.dispatch"


def _notify_stage_wait(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member: int | None,
    item_scoped: bool,
    project_id: int,
    reasons: str,
    names_cases: bool,
    target_tier: str,
    revision: str,
    target_digest: str,
    label: str,
) -> None:
    """Wake this waiting subject; notification misses preserve its QA status.

    names_cases selects the recovery recipe for existing versus missing cases.
    """
    if item_scoped and member is not None:
        no_recipient = "no live claim holder and no covering project steering seat"
        notify = lambda: notify_item_scoped_qa_wait(  # noqa: E731
            conn,
            run_id=run_id,
            stage_name=stage_name,
            item_id=member,
            project_id=project_id,
            reasons=reasons,
            names_cases=names_cases,
            target_tier=target_tier,
            revision=revision,
            target_digest=target_digest,
        )
    else:
        no_recipient = "no live run driver and no covering project steering seat"
        notify = lambda: notify_run_scoped_qa_wait(  # noqa: E731
            conn,
            run_id=run_id,
            stage_name=stage_name,
            project_id=project_id,
            reasons=reasons,
            names_cases=names_cases,
            target_tier=target_tier,
            revision=revision,
            target_digest=target_digest,
        )
    try:
        delivery = notify()
        conn.commit()
        if not delivery:
            print(
                f"Run {run_id!r} stage {stage_name!r} is waiting "
                f"({label}: {reasons}) with {no_recipient} to wake. Staff it "
                "manually."
            )
    except Exception as exc:  # noqa: BLE001 - degrade, don't abort
        rollback_after_error(conn, exc)
        print(
            f"Warning: could not wake a recipient for run {run_id!r} stage "
            f"{stage_name!r} ({label}): {exc}"
        )


@composition_operation
@dispatch_input_operation
@prior_stage_refusals_once
def materialize_and_gate_deployment_qa_stage(
    conn: Any, stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Materialize and gate every subject; ``-4`` means durable QA wait.

    Server-side implementation: the caller already holds a connection to
    the database that serves this control plane. Schema facts and prior-stage
    refusals are read once for the whole walk; each member's reads are
    batched across the run, and a result already reported is not re-sent.
    """
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
    from yoke_core.domain.deployment_qa_dispatch_preparation import prepare_members

    try:
        prepare_release_inputs(conn, stage, run_id=run_id)
    except (LookupError, ValueError) as exc:
        rollback_after_error(conn, exc)
        return qa_stage_error(exc, run_id=run_id, stage_name=str(stage.get("name")))
    errors = prepare_members(conn, stage, run_id=run_id, members=members)
    return _gate_members(
        conn,
        stage,
        run_id=run_id,
        members=members,
        errors=errors,
        project_id=project_id,
        target_tier=target_tier,
        revision=revision,
    )


@presentation_operation
@run_presentation
def _gate_members(
    conn, stage, *, run_id, members, errors, project_id, target_tier, revision
):
    from yoke_core.domain.deployment_qa_member_acceptance_notice import (
        notify_items_qa_accepted,
    )
    from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
    from yoke_core.domain.deployment_qa_stage_materialization import (
        QaCasesNotSelectedError,
    )

    item_refs = render_item_ref_lookup(conn, (m for m in members if m is not None))
    project_slug = (
        resolve_project_slug(conn, project_id) if project_id is not None else ""
    )
    reported = reported_stage_results(conn, run_id=run_id, stage=stage)
    woken = sent_stage_waits(conn, run_id=run_id, stage=stage)
    waiting: list[str] = []
    accepted: list[int] = []
    failure: tuple[int, str] | None = None
    for member in members:
        try:
            if member in errors:
                raise errors[member]
            status = deployment_qa_stage_status(
                conn,
                run_id=run_id,
                stage_name=str(stage["name"]),
                member_item_id=member,
                notify_acceptance=False,
            )
        except QaCasesNotSelectedError as exc:
            label = f"member {item_refs(member)}" if member is not None else "run"
            waiting.append(f"{label}: {exc}")
            if project_id is not None and not woken(member, ""):
                _notify_stage_wait(
                    conn,
                    run_id=run_id,
                    stage_name=str(stage["name"]),
                    member=member,
                    item_scoped=stage.get("scope") == "item",
                    project_id=project_id,
                    reasons=str(exc),
                    names_cases=False,
                    target_tier=target_tier,
                    revision=revision,
                    target_digest="",
                    label=label,
                )
            continue
        except (LookupError, ValueError) as exc:
            # Removal can commit after the stage loaded its member snapshot.
            # Only an audited, still-absent member is excused from this run.
            if member is not None and member in removed_item_ids(conn, run_id):
                attached = conn.execute(
                    "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
                    (run_id, member),
                ).fetchone()
                if attached is None:
                    continue
            failure = qa_stage_error(exc, run_id=run_id, stage_name=str(stage["name"]))
            rollback_after_error(conn, exc)
            break
        label = f"member {item_refs(member)}" if member is not None else "run"
        outcome = str(status.get("outcome") or "")
        digest = str(status.get("target_digest") or "")
        if project_id is not None and not reported(member, outcome, digest):
            report_stage_result(
                conn,
                stage=stage,
                run_id=run_id,
                member=member,
                project_id=project_id,
                outcome=outcome,
                subject=item_refs(member)
                if member is not None
                else "the whole release batch",
                target_tier=target_tier,
                revision=revision,
                target_digest=digest,
            )
        if status["accepted"]:
            for reason in status["reasons"]:
                print(f"Run {run_id!r} stage {stage['name']!r} {label}: {reason}")
            if member is not None:
                # Wake every waiting owner before closing accepted members.
                conn.commit()
                accepted.append(member)
        if not status["accepted"]:
            if project_id is not None:
                if member is not None and status.get("outcome") == "blocked":
                    from yoke_core.domain.deployment_qa_failure_handoff import (
                        notify_member_qa_failure,
                    )

                    handoff = notify_member_qa_failure(
                        conn,
                        run_id=run_id,
                        stage=str(stage["name"]),
                        item_id=member,
                        status=status,
                    )
                    if handoff.startswith("released:"):
                        continue
                    if handoff.startswith(("failed:", "unaddressed:")):
                        print(f"Run {run_id} stage {stage['name']!r}: {handoff}")
                elif member is not None and (
                    manual := manual_wake_requirements(
                        conn,
                        run_id=run_id,
                        stage_name=str(stage["name"]),
                        item_ids=(member,),
                        project_slug=project_slug,
                    )
                ):
                    for miss in wake_manual_requirement_owners(
                        conn, manual, project_id=project_id
                    ):
                        print(f"Run {run_id} stage {stage['name']!r} {label}: {miss}")
                elif not woken(member, digest):
                    _notify_stage_wait(
                        conn,
                        run_id=run_id,
                        stage_name=str(stage["name"]),
                        member=member,
                        item_scoped=stage.get("scope") == "item",
                        project_id=project_id,
                        reasons="; ".join(status["reasons"]),
                        names_cases=True,
                        target_tier=target_tier,
                        revision=revision,
                        target_digest=digest,
                        label=label,
                    )
            waiting.extend(f"{label}: {reason}" for reason in status["reasons"])
    with uncached_presentation():
        pending_close_out = notify_items_qa_accepted(
            conn, run_id=run_id, item_ids=tuple(accepted)
        )
    if pending_close_out:
        waiting.append("qa_member_close_out_pending: re-dispatch this QA stage to continue close-outs")
    if failure:
        return failure
    if waiting:
        return -4, "; ".join(waiting)
    return 0, ""


def dispatch_deployment_qa_stage(
    stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Step-runner adapter for one scoped QA stage over the connection-keyed
    transport (local handler when admin-bootstrapped, else relayed). Only the
    stage name crosses the wire; the handler re-derives it from the stored flow.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
    from yoke_core.domain.deploy_pipeline_unknown_outcome import (
        redispatch_after_connection_loss,
    )

    # Lost idempotent dispatches retry, then stop the driver resumably.
    response = redispatch_after_connection_loss(
        lambda: call_dispatcher(
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
    code, message = int(result.get("code", 1)), str(result.get("message") or "")
    if code == 0 and message:
        print(f"  Stage {stage.get('name')!r}: {message}")
    return code, message


__all__ = [
    "DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION",
    "dispatch_deployment_qa_stage",
    "materialize_and_gate_deployment_qa_stage",
]
