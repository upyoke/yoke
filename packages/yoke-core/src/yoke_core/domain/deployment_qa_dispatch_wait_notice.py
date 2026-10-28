"""Wake the owner of one waiting deployment QA subject, keeping its QA status."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait,
    notify_run_scoped_qa_wait,
)
from yoke_core.domain.deployment_qa_transaction_recovery import rollback_after_error


def notify_stage_wait(
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


__all__ = ["notify_stage_wait"]
