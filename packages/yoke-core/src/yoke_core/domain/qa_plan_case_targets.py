"""Environment fan-out and validation for QA plan cases."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_core.domain.qa_plan_management import QaPlanError


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
            "--deployment-run-id RUN --stage STAGE --member ITEM."
        )
