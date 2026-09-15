"""Deployment runner dispatch for scoped QA stages."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_result_notice import (
    REPORTABLE_OUTCOMES,
    notify_qa_stage_result,
)
from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait,
    notify_run_scoped_qa_wait,
)


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


def dispatch_deployment_qa_stage(
    stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Materialize and gate every subject; ``-4`` means durable QA wait."""
    conn = connect()
    try:
        project_id, target_tier, revision = _run_context(conn, run_id)
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
                label = f"member {member}" if member is not None else "run"
                reasons = "; ".join(status["reasons"])
                waiting.append(f"{label}: {reasons}")
                if project_id is None:
                    continue
                _notify_stage_wait(
                    conn,
                    run_id=run_id,
                    stage_name=str(stage["name"]),
                    member=member,
                    item_scoped=item_scoped,
                    project_id=project_id,
                    reasons=reasons,
                    target_tier=target_tier,
                    revision=revision,
                    target_digest=str(status.get("target_digest") or ""),
                    label=label,
                )
        if waiting:
            return -4, "; ".join(waiting)
        return 0, ""
    finally:
        conn.close()


__all__ = ["dispatch_deployment_qa_stage"]
