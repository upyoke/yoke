"""Send the item-QA wait notices a deployment run's exited driver never sent.

The driver sends each waiting member's stage-wait notice from its dispatch
loop, so a driver that exits at its QA wait (``yoke watch deploy`` returns 5)
leaves every member it had not reached unwoken. Control-plane upkeep calls
:func:`wake_driverless_qa_waits` once per pass: for each live run waiting at
an item-scoped QA stage with no live driver, it sends the driver's own
notice, under the driver's own idempotency key and target digest, to each
waiting member with no wake of any kind yet and an addressable owner.

It reads status only: it materializes, settles and closes nothing, so the
driver's next pass still owns every transition. The stored notice is the
record, so a later upkeep pass or driver finds it and sends nothing twice.
A member whose open QA walk still has a live owner is skipped, exactly as
the driver skips it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.deployment_qa_stage_acceptance import STAGE_NOT_RUN
from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding
from yoke_core.domain.deployment_qa_stage_wake import notify_item_scoped_qa_wait
from yoke_core.domain.deployment_qa_stage_wake_state import driverless_wake_owed
from yoke_core.domain.post_deploy_verification_answer import (
    cases_not_selected_refusal,
)
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.steering_fleet_report_deployment_run_facts import (
    live_deployment_runs,
    live_driver_phase,
)

_LOG = logging.getLogger(__name__)


def wake_driverless_qa_waits(
    conn: Any, *, now: datetime | None = None
) -> dict[str, Any]:
    """Wake every unsent, addressable member of every driverless item-QA wait.

    One run failing is logged and rolled back; the others still run, and the
    next upkeep pass re-derives the failed one from the same rows.
    """
    from yoke_core.domain.project_retirement import active_projects_where

    current = utc_now() if now is None else now
    rows = conn.execute(
        "SELECT id FROM projects" + active_projects_where(conn) + " ORDER BY id"
    ).fetchall()
    conn.commit()
    sent: list[str] = []
    errors: list[str] = []
    for project_id in (int(row_value(row, "id", 0)) for row in rows):
        runs = live_deployment_runs(conn, project_id=project_id)
        conn.commit()
        for run in runs:
            if not str(run.get("current_stage") or "") or live_driver_phase(
                run, now=current
            ):
                continue
            try:
                sent.extend(_wake_run(conn, run, project_id=project_id))
            except Exception as exc:  # noqa: BLE001 - the next pass retries it
                conn.rollback()
                errors.append(f"run {run['id']}: {exc}")
                _LOG.warning(
                    "driverless QA wake for run %s failed", run["id"], exc_info=True
                )
    return {"sent": sent, "errors": errors}


def _wake_run(conn: Any, run: dict[str, Any], *, project_id: int) -> list[str]:
    from yoke_core.domain.deployment_qa_dispatch_inputs import run_context
    from yoke_core.domain.deployment_qa_plan_ownership import open_walk_members

    run_id = str(run["id"])
    stage_name = str(run["current_stage"])
    qa = qa_stage_outstanding(conn, run_id=run_id, stage_name=stage_name)
    blockers = {
        member: entry
        for member, entry in (qa.member_blockers() if qa is not None else {}).items()
        if member is not None and member not in _closed_members(conn, run_id)
    }
    owed = driverless_wake_owed(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        item_ids=sorted(blockers),
        project_id=project_id,
    ) if blockers else []
    walking = open_walk_members(conn, run_id, owed, stage=stage_name) if owed else set()
    _, target_tier, revision = run_context(conn, run_id)
    conn.commit()
    woken: list[str] = []
    for member in owed:
        if member in walking:
            continue
        state, lines = blockers[member]
        held = state == STAGE_NOT_RUN and any(
            line.endswith(cases_not_selected_refusal()) for line in lines
        )
        digest = "" if held else _target_digest(conn, run_id, stage_name, member)
        delivery = notify_item_scoped_qa_wait(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            item_id=member,
            project_id=project_id,
            reasons="; ".join(line.split(": ", 1)[-1] for line in lines),
            names_cases=not held,
            target_tier=target_tier,
            revision=revision,
            target_digest=digest,
        )
        conn.commit()
        if delivery:
            woken.append(f"{run_id}:{stage_name}:{member}")
        else:
            _LOG.warning(
                "run %s stage %s member %s is waiting with nobody addressable "
                "to wake; staff it",
                run_id,
                stage_name,
                member,
            )
    return woken


def _closed_members(conn: Any, run_id: str) -> set[int]:
    """Terminal members, which the driver no longer gates or wakes."""
    from yoke_core.domain.workflow_status_queries import terminal_items_sql

    return {
        int(row_value(row, "item_id", 0))
        for row in conn.execute(
            "SELECT m.item_id FROM deployment_run_items m JOIN items i ON i.id=m.item_id "
            f"WHERE m.run_id=%s AND {terminal_items_sql(conn)}",
            (run_id,),
        ).fetchall()
    }


def _target_digest(conn: Any, run_id: str, stage_name: str, member: int) -> str:
    """The stage status's own target digest, read without settling anything."""
    from yoke_core.domain import qa_execution_environment_target as target_authority
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_target_continuity import settlement_target

    subject = deployment_qa_stage_subject(
        conn, run_id=run_id, stage_name=stage_name, member_item_id=member
    )
    target = deployment_qa_execution_target(conn, subject)
    return target_authority.target_digest(settlement_target(conn, subject, target))


__all__ = ["wake_driverless_qa_waits"]
