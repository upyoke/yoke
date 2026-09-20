"""Refuse a case run that cannot credit an item-scoped deployment stage.

A QA stage credits only requirements bound to its own stage name — and an
item-scoped stage, the member too. `yoke qa case run` executes one
requirement by id and records that requirement's verdict; it never creates
the scoped plan execution the stage reads. Exiting zero with a genuine pass
is how a caller reports the gate satisfied while the stage stays empty.

This module does not change what a stage credits. It detects the mismatch
at the case-run entry and names the plan-run invocation that would.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext


def item_scoped_stage_plan_run_command(case: Mapping[str, Any]) -> str | None:
    """Return the plan-run invocation that would credit this case's stage.

    None means the case contract does not name an item-scoped stage with
    every field the command needs, including an older contract that omits
    them: the case run then proceeds as it always has.
    """
    run_id = str(case.get("deployment_run_id") or "").strip()
    stage = str(case.get("deployment_stage") or "").strip()
    member_ref = str(case.get("deployment_member_ref") or "").strip()
    project = str(case.get("project") or "").strip()
    if not run_id or not stage or not member_ref or not project:
        return None
    if case.get("deployment_member_item_id") is None:
        return None
    return (
        f"yoke qa plan run --deployment-run-id {run_id} --stage {stage} "
        f"--member {member_ref} --project {project}"
    )


def item_scoped_stage_credit_refusal(case: Mapping[str, Any]) -> str | None:
    """Return a refusal when a case run would credit nothing toward its stage."""
    command = item_scoped_stage_plan_run_command(case)
    if command is None:
        return None
    stage = str(case["deployment_stage"]).strip()
    member_ref = str(case["deployment_member_ref"]).strip()
    run_id = str(case["deployment_run_id"]).strip()
    return (
        f"STAGE CREDIT REFUSAL: this requirement is bound to item-scoped "
        f"stage {stage!r} for member {member_ref} on {run_id}. A passing "
        "case run does not credit that stage. Run this instead:\n"
        f"  {command}"
    )


def execute_authorized_case(
    requirement_id: int,
    *,
    base_url: str = "",
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    allow_tree_mismatch: bool = False,
    actor: Optional[ActorContext] = None,
) -> dict:
    """Authorize a case, refuse an uncredited item-scoped stage, then run it."""
    from yoke_core.domain import qa_case_execution as cases

    case = cases.fetch_case_execution_context(requirement_id, actor=actor)
    refusal = item_scoped_stage_credit_refusal(case)
    if refusal:
        raise cases.QaCaseExecutionError(refusal)
    return cases.execute_case_context(
        case,
        base_url=base_url,
        expected_branch=expected_branch,
        expected_sha=expected_sha,
        timeout_seconds=timeout_seconds,
        checkout_path=checkout_path,
        allow_tree_mismatch=allow_tree_mismatch,
        actor=actor,
    )


__all__ = [
    "execute_authorized_case",
    "item_scoped_stage_credit_refusal",
    "item_scoped_stage_plan_run_command",
]
