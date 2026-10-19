"""Match a standing obligation to its frozen deployment copy."""

from __future__ import annotations
from typing import Any


def is_run_proof(source: dict[str, Any], answer: dict[str, Any]) -> bool:
    return bool(
        source.get("item_id")
        and not source.get("deployment_run_id")
        and answer.get("deployment_run_id")
    )


def run_proof_mismatches(source: dict[str, Any], answer: dict[str, Any]) -> list[str]:
    from yoke_core.domain.deployment_qa_admission_materialization import (
        admitted_source_requirement_id,
    )
    from yoke_core.domain.qa_deployment_case_content_refresh import base_case_key
    from yoke_core.domain.qa_requirement_source_retirement import (
        source_retirement_scope,
    )

    errors = []
    if source.get("item_id") != answer.get("deployment_member_item_id"):
        errors.append("deployment member does not own the standing requirement")
    if source.get("plan_id"):
        if (
            source.get("plan_id") != answer.get("plan_id")
            or not source.get("plan_case_key")
            or base_case_key(str(source.get("plan_case_key")))
            != base_case_key(str(answer.get("plan_case_key") or ""))
        ):
            errors.append("plan case does not match the standing obligation")
    elif admitted_source_requirement_id(answer.get("plan_case_key")) != source.get(
        "id"
    ):
        errors.append("run case was not admitted from this standing requirement")
    for key in ("qa_phase", "host_baseline", "method_id"):
        if str(source.get(key) or "") != str(answer.get(key) or ""):
            errors.append(f"{key} differs")
    left, right = map(source_retirement_scope, (source, answer))
    if not left.get("target_env") or left["target_env"] != right.get("target_env"):
        errors.append("resolved target environment differs or is missing")
    # A frozen source target is binding; an unbound source names its environment.
    if source.get("execution_target_digest") and source[
        "execution_target_digest"
    ] != answer.get("execution_target_digest"):
        errors.append("execution target differs")
    return errors
