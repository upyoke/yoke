"""Recover the deployment QA subject an execution or requirement answers.

A plan group's rows carry ``deployment.shared_plan`` in their target and no
member; :mod:`deployment_qa_plan_groups` owns reading and writing them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows


def execution_subject(
    conn: Any, execution: Mapping, *, require_active: bool = True
) -> dict:
    """Recover a private or shared subject from its immutable execution target."""
    import json

    from yoke_core.domain.qa_request_subjects import execution_subject_once
    from yoke_core.domain.deployment_qa_takeover_identity import read_execution_subject

    target = (
        execution.get("execution_target")
        or execution.get("execution_target_json")
        or {}
    )
    if not isinstance(target, Mapping):
        target = json.loads(str(target))
    return execution_subject_once(
        execution,
        target,
        require_active=require_active,
        read=lambda active: read_execution_subject(
            conn, execution, target, require_active=active
        ),
    )


def requirement_subject(
    conn: Any, requirement_id: int, *, require_active: bool = True
) -> dict:
    """Resolve stage policy and target authority from a stored requirement."""
    rows = query_rows(
        conn,
        "SELECT deployment_run_id,deployment_stage,deployment_member_item_id,execution_target_json "
        "FROM qa_requirements WHERE id=%s",
        (int(requirement_id),),
    )
    if not rows:
        raise ValueError(
            "shared_plan_requirement_missing: inspect the requirement id before retrying"
        )
    return execution_subject(conn, rows[0], require_active=require_active)


def shared_target_identity(raw: Any) -> Mapping | None:
    """Recognize only explicit shared groups when reading run-wide history."""
    import json

    try:
        target = raw if isinstance(raw, Mapping) else json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return None
    if not isinstance(target, Mapping):
        return None
    return (target.get("deployment") or {}).get("shared_plan")
