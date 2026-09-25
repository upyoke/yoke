"""Decide whether a run-bound member case is settled at item completion."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import qa_execution_environment_target as target_authority
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    latest_verdict,
    stage_acceptance_blockers,
)
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)


def superseded_run_bound_row_satisfied(
    conn: Any, *, requirement_id: int, item_id: int, completion: dict[str, Any] | None
) -> bool:
    """Require the corrected case and its exact completion stage to be accepted.

    A stored supersession link alone cannot discharge a row: older or forced
    links may name a failing case or a case outside this member's target.
    """
    if completion is None:
        return False
    if completion["status"] != "succeeded":
        from yoke_core.domain.deployment_member_independent_close_out import (
            independent_member_delivery_ready,
        )

        if not independent_member_delivery_ready(
            conn, item_id=int(item_id), run_id=str(completion["id"])
        ):
            return False
    broken = query_one(
        conn,
        "SELECT deployment_run_id,deployment_stage,deployment_member_item_id,"
        "execution_target_digest,superseded_by_requirement_id "
        "FROM qa_requirements WHERE id=%s",
        (int(requirement_id),),
    )
    if broken is None or not broken["superseded_by_requirement_id"]:
        return False
    run_id = str(broken["deployment_run_id"] or "")
    stage = str(broken["deployment_stage"] or "")
    if (
        run_id != completion["id"]
        or not stage
        or broken["deployment_member_item_id"] != int(item_id)
    ):
        return False
    corrected_id = int(broken["superseded_by_requirement_id"])
    corrected = query_one(
        conn,
        "SELECT deployment_run_id,deployment_stage,deployment_member_item_id,"
        "execution_target_digest,blocking_mode,waived_at,"
        "superseded_by_requirement_id FROM qa_requirements WHERE id=%s",
        (corrected_id,),
    )
    if corrected is None or any(
        str(broken[column] or "") != str(corrected[column] or "")
        for column in (
            "deployment_run_id",
            "deployment_stage",
            "deployment_member_item_id",
            "execution_target_digest",
        )
    ):
        return False
    if (
        corrected["blocking_mode"] != "blocking"
        or corrected["waived_at"]
        or corrected["superseded_by_requirement_id"]
        or latest_verdict(conn, corrected_id) != "pass"
    ):
        return False
    try:
        subject = deployment_qa_stage_subject(
            conn,
            run_id=run_id,
            stage_name=stage,
            member_item_id=int(item_id),
            require_active=False,
        )
        target = deployment_qa_execution_target(conn, subject)
        if broken["execution_target_digest"] != target_authority.target_digest(target):
            return False
        return not stage_acceptance_blockers(
            conn,
            subject=subject,
            target=target,
            acceptance_qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
        )
    except (LookupError, TypeError, ValueError):
        return False
