"""Environment fan-out and validation for QA plan cases."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_core.domain.qa_plan_management import QaPlanError

STAGE_REASONS = ("creates_or_destroys_data", "changes_infrastructure")


def validated_target_envs(raw: Any, *, case_key: str) -> list[str]:
    if (
        not isinstance(raw, list)
        or any(
            not isinstance(value, str) or not value.strip() or value != value.strip()
            for value in raw
        )
        or len(raw) != len(set(raw))
    ):
        raise QaPlanError(
            f"case {case_key!r}: target_envs_invalid; target_envs must be a JSON "
            "list of unique non-empty registered environment names. "
            "Use [] to keep the plan's default target."
        )
    return list(raw)


def case_target_envs(case: Mapping[str, Any]) -> list[str]:
    raw = dict(case).get("target_envs", [])
    if isinstance(raw, str):
        raw = json.loads(raw)
    return validated_target_envs(raw, case_key=str(case["case_key"]))


def case_applies_to_target(case: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    names = case_target_envs(case)
    return (
        not names or str((target.get("environment") or {}).get("name") or "") in names
    )


def resolve_case_targets(
    conn: Any, *, plan: Any, case: Any, resolve_default: bool = True
) -> list[tuple[str | None, dict]]:
    from yoke_core.domain.qa_execution_environment_target import (
        resolve_plan_execution_target,
    )
    from yoke_core.domain.qa_environment_execution_target import (
        resolve_named_environment_execution_target,
    )

    names = case_target_envs(case)
    if not names:
        return (
            [
                (
                    None,
                    resolve_plan_execution_target(
                        conn, plan_id=int(plan["id"]), require_runtime_match=False
                    ),
                )
            ]
            if resolve_default
            else []
        )
    targets = []
    for name in names:
        try:
            target = resolve_named_environment_execution_target(
                conn,
                project_id=int(plan["project_id"]),
                environment_name=name,
                require_runtime_match=False,
            )
        except ValueError as exc:
            raise QaPlanError(
                f"case {case['case_key']!r}: target_env_unavailable: {exc}. "
                "Register the environment and its reviewable URL on this project, "
                "then replace the case target_envs."
            ) from exc
        targets.append((name, target))
    return targets


def validate_case_targets(conn: Any, *, plan: Any, case: Mapping[str, Any]) -> None:
    """Validate reason metadata, and each target's endpoints against the case.

    A case runs against every environment it names, or the plan's bound
    environment when it names none. Any endpoint or environment the case
    pins must belong to that target, so a wrong-target case is refused when
    it is written or attached rather than after a deployment reaches it. A
    plan without a bound environment has no default endpoints to check;
    project targets keep their own command-only contract.
    """
    from yoke_core.domain.qa_execution_environment_target import (
        require_case_target,
    )
    from yoke_core.domain.qa_plan_case_definition import case_target_subject

    key = str(case["case_key"])
    reason = case.get("stage_reason")
    if reason is not None and reason not in STAGE_REASONS:
        raise QaPlanError(
            f"case {key!r}: stage_reason_invalid: {reason!r} is not a stage reason. "
            f"Use one of {', '.join(STAGE_REASONS)}, or remove stage_reason."
        )
    resolve_default = bool(dict(plan).get("target_environment_id"))
    try:
        targets = resolve_case_targets(
            conn, plan=plan, case=case, resolve_default=resolve_default
        )
    except ValueError as exc:
        if isinstance(exc, QaPlanError):
            raise
        raise QaPlanError(
            f"case {key!r}: target_unavailable: {exc}. Bind QA plan "
            f"{plan['id']} to a registered environment with its reviewable URL, "
            "then retry."
        ) from exc
    for name, target in targets:
        environment = name or (target.get("environment") or {}).get("name")
        try:
            require_case_target(case_target_subject(case, case), target)
        except ValueError as exc:
            raise QaPlanError(
                f"case {key!r} of QA plan {plan['id']}: case_target_mismatch: "
                f"{exc}; this case runs against {environment!r}. Name only that "
                "environment's endpoints, or list the environment the endpoint "
                "belongs to in target_envs, then set the plan's cases again with "
                "`yoke qa plan cases`."
            ) from exc


def validate_plan_case_targets(conn: Any, *, plan: Any) -> None:
    """Check every stored case of a plan before the plan is attached."""
    from yoke_core.domain.qa_plan_case_definition import plan_cases

    for case in plan_cases(conn, int(plan["id"])):
        validate_case_targets(conn, plan=plan, case=case)


def case_variants(conn: Any, *, plan: Any, cases: list[Any]):
    """Resolve every variant before the caller starts writing snapshots."""
    return [
        (case, name, target)
        for case in cases
        for name, target in resolve_case_targets(conn, plan=plan, case=case)
    ]


def require_single_execution_target(
    cases: list[Any], target: Mapping[str, Any]
) -> None:
    """A standalone execution cannot silently drop another target's proof."""
    name = str((target.get("environment") or {}).get("name") or "")
    missing = sorted(
        {env for case in cases for env in case_target_envs(case) if env != name}
    )
    if missing:
        raise QaPlanError(
            f"qa_plan_requires_environment_scopes: this execution targets {name!r}, "
            f"but cases also require {', '.join(missing)}. Materialize the attached "
            "item plan and execute each requirement with yoke qa case run, or "
            "execute each matching deployment QA stage with yoke qa plan run "
            "--item ITEM --stage STAGE."
        )


def require_materialized_case_target(
    conn: Any,
    *,
    case: Any,
    definition: Mapping[str, Any],
    target: Mapping[str, Any],
    owner: Mapping[str, Any],
) -> None:
    """The materialization target check, naming the plan case and its owners."""
    from yoke_core.domain.item_ref_render import render_item_refs
    from yoke_core.domain.qa_execution_environment_target import (
        QaExecutionTargetError,
        require_case_target,
    )
    from yoke_core.domain.qa_plan_case_definition import case_target_subject

    try:
        require_case_target(case_target_subject(case, definition), target)
    except QaExecutionTargetError as exc:
        if owner.get("requirement_id") is not None:
            from yoke_core.domain.db_helpers import query_one
            from yoke_core.domain.qa_plan_management import _placeholder

            row = query_one(
                conn,
                "SELECT item_id, deployment_member_item_id, deployment_run_id "
                f"FROM qa_requirements WHERE id={_placeholder(conn)}",
                (int(owner["requirement_id"]),),
            )
            owner = {**dict(row or {}), **owner}
        item_id = owner.get("item_id") or owner.get("deployment_member_item_id")
        names = [f"QA plan {definition['plan_id']} case {case['case_key']!r}"]
        if owner.get("requirement_id") is not None:
            names.append(f"requirement {owner['requirement_id']}")
        if item_id is not None:
            names.append(f"item {render_item_refs(conn, [item_id]).get(item_id)}")
        if owner.get("deployment_run_id"):
            names.append(f"deployment run {owner['deployment_run_id']}")
        raise QaExecutionTargetError(
            f"{', '.join(names)}: {exc}. Name only this target's endpoints in "
            "the plan case, set them with `yoke qa plan cases`, then "
            "rematerialize."
        ) from exc
