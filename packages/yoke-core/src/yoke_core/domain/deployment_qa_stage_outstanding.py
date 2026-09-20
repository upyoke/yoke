"""Read which QA-stage subjects a drive would still wait on.

A run sitting at a scoped QA stage is not waiting on unsettled
``qa_requirements`` rows. The driver asks
:func:`materialize_and_gate_deployment_qa_stage`, which waits on
:class:`QaCasesNotSelectedError` or on
:func:`deployment_qa_stage_status`. This module is that walk without
materializing, settling, or waking anyone, so a report and a drive cannot
disagree about whether anything is outstanding.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA
from yoke_core.domain.deployment_qa_admission_materialization import (
    member_requirements,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    STAGE_NOT_RUN,
    stage_acceptance,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_stage_gate import ACCEPTANCE_QA_KIND
from yoke_core.domain.deployment_qa_stage_named_cases import stage_names_cases
from yoke_core.domain.post_deploy_verification_answer import (
    cases_not_selected_refusal,
    member_post_deploy_answer,
)
from yoke_core.domain.qa_deployment_member_attached_plans import (
    attached_member_plans,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.steering_fleet_report_detectors import marker


@dataclass(frozen=True)
class QaStageOutstanding:
    """One current QA stage's subjects, and the wait lines a drive would print."""

    lines: tuple[str, ...]
    subjects: int
    waiting: int


def qa_stage_outstanding(
    conn: Any, *, run_id: str, stage_name: str
) -> Optional[QaStageOutstanding]:
    """Outstanding waits for *stage_name* when that stage is scoped QA.

    ``None`` means the report should keep the completion-boundary readers:
    this is not a QA stage, or the frozen subject cannot be evaluated.
    """
    stage = _qa_stage(conn, run_id=run_id, stage_name=stage_name)
    if stage is None:
        return None
    try:
        return _evaluate(conn, run_id=run_id, stage=stage)
    except (LookupError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _qa_stage(conn: Any, *, run_id: str, stage_name: str) -> Optional[dict[str, Any]]:
    if not (
        _table_exists(conn, "deployment_runs")
        and _table_exists(conn, "deployment_flows")
    ):
        return None
    p = marker(conn)
    row = conn.execute(
        f"""SELECT df.stages FROM deployment_runs dr
              JOIN deployment_flows df ON df.id = dr.flow
             WHERE dr.id = {p}""",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    raw = row["stages"] if hasattr(row, "keys") else row[0]
    try:
        stages = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return None
    if not isinstance(stages, list):
        return None
    matches = [
        dict(stage)
        for stage in stages
        if isinstance(stage, Mapping) and str(stage.get("name") or "") == stage_name
    ]
    if len(matches) != 1:
        return None
    stage = matches[0]
    if (
        stage.get("stage_kind") != STAGE_KIND_QA
        or stage.get("step_runner") != QA_STEP_RUNNER
    ):
        return None
    return stage


def _subjects(conn: Any, run_id: str, stage: Mapping[str, Any]) -> list[int | None]:
    if stage.get("scope") == "item":
        rows = conn.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
            (run_id,),
        ).fetchall()
        return [
            int(row["item_id"] if hasattr(row, "keys") else row[0]) for row in rows
        ]
    return [None]


def _has_method_id(
    conn: Any, *, run_id: str, stage_name: str, member: int | None
) -> bool:
    if not _table_exists(conn, "qa_requirements"):
        return False
    row = conn.execute(
        "SELECT 1 FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s "
        "AND method_id IS NOT NULL LIMIT 1",
        (run_id, stage_name, member or 0),
    ).fetchone()
    return row is not None


def _frozen_plans(
    conn: Any, subject: Mapping[str, Any], *, target: Mapping[str, Any]
) -> list[dict[str, Any]]:
    stage = str(subject["stage"]["name"])
    frozen = [
        dict(selection)
        for selection in subject["flow_snapshot"].get("selections") or []
        if isinstance(selection, Mapping) and str(selection.get("stage") or "") == stage
    ]
    snapshot = subject.get("member_snapshot")
    environment = target.get("environment")
    environment_id = (
        environment.get("id") if isinstance(environment, Mapping) else None
    )
    if isinstance(snapshot, Mapping):
        for value in snapshot.get("plans") or []:
            if not isinstance(value, Mapping):
                continue
            attachment = value.get("attachment")
            plan = value.get("plan")
            if not isinstance(attachment, Mapping) or not isinstance(plan, Mapping):
                continue
            if str(attachment.get("qa_phase") or "") != "post_deploy":
                continue
            plan_environment = plan.get("target_environment_id")
            if plan_environment is not None and int(plan_environment) != int(
                environment_id or 0
            ):
                continue
            frozen.append(dict(value))
    if not frozen:
        frozen = attached_member_plans(conn, subject, target=target)
    return frozen


def _unselected_reason(
    conn: Any, subject: Mapping[str, Any], *, target: Mapping[str, Any]
) -> str | None:
    admitted = member_requirements(subject, target=target)
    frozen = _frozen_plans(conn, subject, target=target)
    if stage_names_cases(
        conn, subject, frozen_plans=frozen, admitted=admitted
    ):
        return None
    if member_post_deploy_answer(conn, subject).discharges_without_cases:
        return None
    return cases_not_selected_refusal()


def _member_lines(
    conn: Any, *, run_id: str, stage: Mapping[str, Any], member: int | None
) -> list[str]:
    """Driver-shaped wait lines for one subject, without writes."""
    label = f"member {member}" if member is not None else "run"
    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=str(stage["name"]),
        member_item_id=member,
        require_active=False,
    )
    target = deployment_qa_execution_target(conn, subject)
    if not _has_method_id(
        conn, run_id=run_id, stage_name=str(stage["name"]), member=member
    ):
        unselected = _unselected_reason(conn, subject, target=target)
        if unselected:
            return [f"{label}: {unselected}"]
    acceptance = stage_acceptance(
        conn,
        subject=subject,
        target=target,
        acceptance_qa_kind=ACCEPTANCE_QA_KIND,
    )
    if acceptance.accepted:
        return []
    if (
        acceptance.state == STAGE_NOT_RUN
        and member_post_deploy_answer(conn, subject).discharges_without_cases
    ):
        return []
    return [f"{label}: {reason}" for reason in acceptance.blockers]


def _evaluate(
    conn: Any, *, run_id: str, stage: Mapping[str, Any]
) -> QaStageOutstanding:
    members = _subjects(conn, run_id, stage)
    if stage.get("scope") == "item" and not members:
        return QaStageOutstanding(
            lines=("item-scoped QA stage has no attached run members",),
            subjects=1,
            waiting=1,
        )
    lines: list[str] = []
    waiting = 0
    for member in members:
        member_lines = _member_lines(
            conn, run_id=run_id, stage=stage, member=member
        )
        if member_lines:
            waiting += 1
            lines.extend(member_lines)
    return QaStageOutstanding(
        lines=tuple(lines),
        subjects=len(members),
        waiting=waiting,
    )


__all__ = ["QaStageOutstanding", "qa_stage_outstanding"]
