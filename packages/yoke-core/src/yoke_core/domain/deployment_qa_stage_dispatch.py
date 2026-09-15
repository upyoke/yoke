"""Deployment runner dispatch for scoped QA stages.

Materializing and gating a scoped QA stage reads/writes qa_requirements and
qa_runs through the registered function-call dispatcher, the same
connection-keyed path ``deploy_pipeline_control_plane`` uses for every other
execution-owned write: an explicitly selected local database authority (an
admin-bootstrapped driver) dispatches in-process through the registered
handler, while an ordinary HTTPS-connected driver relays to whatever build
is actively serving that connection. There is no fallback for an old
serving build that has not registered this function id — the caller reads
that refusal like any other unsupported operation.
``materialize_and_gate_deployment_qa_stage`` is the server-side
implementation the relayed handler calls; it takes a live connection the
caller already holds.

Both notices a settled subject owes are sent from that server-side
function rather than from the client adapter, for the same reason the
gating is: the connection that can address recipients and write their
envelopes is the one serving this control plane, not the one the release
driver happens to hold.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_qa_result_notice import (
    REPORTABLE_OUTCOMES,
    notify_qa_stage_result,
)
from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait,
    notify_run_scoped_qa_wait,
)

DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION = "deployment_runs.qa_stage.dispatch"


def _run_context(conn: Any, run_id: str) -> tuple[int | None, str, str]:
    """This run's project, configured target tier, and revision."""
    row = conn.execute(
        "SELECT project_id, target_tier, release_lineage "
        "FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        return None, "", ""
    get = (lambda key, i: row[key]) if hasattr(row, "keys") else (lambda key, i: row[i])
    project_id = get("project_id", 0)
    return (
        int(project_id) if project_id is not None else None,
        str(get("target_tier", 1) or ""),
        str(get("release_lineage", 2) or ""),
    )


def _notify_stage_wait(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member: int | None,
    item_scoped: bool,
    project_id: int,
    reasons: str,
    target_tier: str,
    revision: str,
    target_digest: str,
    label: str,
) -> None:
    """Wake the right recipient for one waiting subject, and log the miss.

    A wake failure is not a QA-status failure: the stage is genuinely
    still waiting either way, so a notification hiccup degrades to "not
    woken" rather than aborting the dispatch and losing the wait result
    already computed.
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
            target_tier=target_tier,
            revision=revision,
            target_digest=target_digest,
        )
    else:
        no_recipient = "no deploy-lock driver and no covering project steering seat"
        notify = lambda: notify_run_scoped_qa_wait(  # noqa: E731
            conn,
            run_id=run_id,
            stage_name=stage_name,
            project_id=project_id,
            reasons=reasons,
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
        conn.rollback()
        print(
            f"Warning: could not wake a recipient for run {run_id!r} stage "
            f"{stage_name!r} ({label}): {exc}"
        )


def _report_stage_result(
    conn: Any,
    *,
    stage: Mapping[str, Any],
    run_id: str,
    member: int | None,
    project_id: int,
    outcome: str,
    target_tier: str,
    revision: str,
    target_digest: str,
) -> None:
    """Report a settled result to the audience the stage configured.

    Distinct from the wait wake above in recipient and in purpose: that
    one asks an agent to act, this one tells people what was decided. A
    failure to report is not a QA-status failure, so it degrades to a
    printed note the same way.
    """
    if outcome not in REPORTABLE_OUTCOMES:
        return
    from yoke_core.domain.project_identity import render_item_ref

    subject = (
        render_item_ref(conn, member)
        if member is not None
        else "the whole release batch"
    )
    try:
        result = notify_qa_stage_result(
            conn,
            notification=stage.get("notification"),
            run_id=run_id,
            stage_name=str(stage["name"]),
            member_item_id=member,
            project_id=project_id,
            outcome=outcome,
            subject=subject,
            target_tier=target_tier,
            revision=revision,
            target_digest=target_digest,
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - degrade, don't abort
        conn.rollback()
        print(
            f"Warning: could not report run {run_id!r} stage "
            f"{str(stage['name'])!r} result to its notification audience: {exc}"
        )
        return
    if result["notified"]:
        print(
            f"Reported run {run_id!r} stage {str(stage['name'])!r} {outcome} "
            f"for {subject} to {len(result['notified'])} configured "
            "recipient(s)."
        )

def materialize_and_gate_deployment_qa_stage(
    conn: Any, stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Materialize and gate every subject; ``-4`` means durable QA wait.

    Server-side implementation: the caller already holds a connection to
    the database that serves this control plane.
    """
    from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
    from yoke_core.domain.deployment_qa_stage_materialization import (
        QaCasesNotSelectedError,
        materialize_deployment_qa_stage,
    )

    project_id, target_tier, revision = _run_context(conn, run_id)
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
        except QaCasesNotSelectedError as exc:
            # The default story, not a failure: this stage names no cases
            # and nobody has selected any yet. It is a durable wait, and
            # the agent responsible for the subject is the one who can end
            # it — so wake them instead of failing the stage out from
            # under them.
            label = f"member {member}" if member is not None else "run"
            waiting.append(f"{label}: {exc}")
            if project_id is not None:
                _notify_stage_wait(
                    conn,
                    run_id=run_id,
                    stage_name=str(stage["name"]),
                    member=member,
                    item_scoped=stage.get("scope") == "item",
                    project_id=project_id,
                    reasons=str(exc),
                    target_tier=target_tier,
                    revision=revision,
                    target_digest="",
                    label=label,
                )
            continue
        except (LookupError, ValueError) as exc:
            # Every other refusal is a real stage failure: an invalid
            # pinned plan, an unresolvable target identity, a permission
            # denial. None of those becomes truer by waiting.
            return 1, str(exc)
        label = f"member {member}" if member is not None else "run"
        if project_id is not None:
            _report_stage_result(
                conn,
                stage=stage,
                run_id=run_id,
                member=member,
                project_id=project_id,
                outcome=str(status.get("outcome") or ""),
                target_tier=target_tier,
                revision=revision,
                target_digest=str(status.get("target_digest") or ""),
            )
        if not status["accepted"]:
            waiting.extend(f"{label}: {reason}" for reason in status["reasons"])
            if project_id is not None:
                _notify_stage_wait(
                    conn,
                    run_id=run_id,
                    stage_name=str(stage["name"]),
                    member=member,
                    item_scoped=stage.get("scope") == "item",
                    project_id=project_id,
                    reasons="; ".join(status["reasons"]),
                    target_tier=target_tier,
                    revision=revision,
                    target_digest=str(status.get("target_digest") or ""),
                    label=label,
                )
    if waiting:
        return -4, "; ".join(waiting)
    return 0, ""


def dispatch_deployment_qa_stage(
    stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Deployment step-runner adapter for one scoped QA stage.

    Dispatches through the connection-keyed function-call transport: an
    admin-bootstrapped driver executes the registered handler locally, an
    ordinary HTTPS-connected driver relays to whatever build is actively
    serving that connection. Only the stage name crosses the wire — the
    handler re-derives the stage's full scope/config from the run's own
    stored flow rather than trusting this caller's copy of it.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    response = call_dispatcher(
        function_id=DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={"stage_name": str(stage.get("name") or "")},
    )
    if not response.success:
        message = response.error.message if response.error else "request failed"
        return 1, (
            f"deployment QA stage {stage.get('name')!r} could not be "
            f"dispatched: {message}"
        )
    result = dict(response.result or {})
    return int(result.get("code", 1)), str(result.get("message") or "")


__all__ = [
    "DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION",
    "dispatch_deployment_qa_stage",
    "materialize_and_gate_deployment_qa_stage",
]
