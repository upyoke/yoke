"""Compare-and-swap editing for project-scoped QA plans."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    _json,
    _next_updated_at,
    _placeholder,
    _project_id,
    _validate_target_environment,
    _validated_plan_cases,
)


class QaPlanConflictError(RuntimeError):
    """The plan changed after the caller read its authoring document."""


def _decode(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def _case_document(row: Any) -> dict[str, Any]:
    return {
        "case_key": str(row["case_key"]),
        "position": int(row["position"]),
        "method_id": str(row["method_id"]),
        "instructions": str(row["instructions"]),
        "expected_outcome": str(row["expected_outcome"]),
        "method_config": _decode(row["method_config"], {}),
        "success_policy_id": row["success_policy_id"],
        "success_policy_params": _decode(
            row["success_policy_params"],
            None,
        ),
        "host_baselines": _decode(row["host_baselines"], []),
        "entry_surface": row["entry_surface"],
        "required_completion": row["required_completion"],
    }


def _current_cases(conn: Any, plan_id: int) -> list[dict[str, Any]]:
    marker = _placeholder(conn)
    return [
        _case_document(row)
        for row in query_rows(
            conn,
            "SELECT case_key, position, method_id, instructions, "
            "expected_outcome, method_config, success_policy_id, "
            "success_policy_params, host_baselines, entry_surface, "
            f"required_completion FROM qa_plan_cases WHERE plan_id={marker} "
            "ORDER BY position",
            (plan_id,),
        )
    ]


def _insert_cases(
    conn: Any,
    *,
    marker: str,
    plan_id: int,
    cases: list[dict[str, Any]],
    stamp: str,
) -> None:
    conn.execute(
        f"DELETE FROM qa_plan_cases WHERE plan_id={marker}",
        (plan_id,),
    )
    for case in cases:
        conn.execute(
            "INSERT INTO qa_plan_cases("
            "plan_id, case_key, position, method_id, instructions, "
            "expected_outcome, method_config, success_policy_id, "
            "success_policy_params, host_baselines, entry_surface, "
            "required_completion, created_at, updated_at"
            f") VALUES ({', '.join([marker] * 14)})",
            (
                plan_id,
                case["case_key"],
                case["position"],
                case["method_id"],
                case["instructions"],
                case["expected_outcome"],
                _json(case["method_config"]),
                case["success_policy_id"],
                (
                    _json(case["success_policy_params"])
                    if case["success_policy_params"] is not None
                    else None
                ),
                _json(case["host_baselines"]),
                case.get("entry_surface"),
                case.get("required_completion"),
                stamp,
                stamp,
            ),
        )


def edit_plan(
    conn: Any,
    *,
    project: str,
    slug: str,
    base_updated_at: str,
    name: str,
    description: str,
    success_policy_id: str,
    success_policy_params: dict[str, Any],
    target_environment_id: str | None = None,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace one authoring document with CAS and true no-op semantics."""
    if not str(base_updated_at).strip():
        raise QaPlanError("base_updated_at is required for plan editing")
    if not str(name).strip():
        raise QaPlanError("plan name must not be empty")
    if success_policy_id != "all-pass":
        raise QaPlanError("v1 supports only the all-pass success policy")
    if not isinstance(success_policy_params, dict):
        raise QaPlanError("success_policy_params must be a JSON object")

    project_id = _project_id(conn, project)
    marker = _placeholder(conn)
    plan = query_one(
        conn,
        "SELECT p.*, pr.slug AS project FROM qa_plans p "
        "JOIN projects pr ON pr.id=p.project_id "
        f"WHERE p.project_id={marker} AND p.slug={marker}",
        (project_id, slug),
    )
    if plan is None:
        raise QaPlanError(f"QA plan {project}/{slug} not found")
    if plan["retired_at"] is not None:
        raise QaPlanError(f"QA plan {project}/{slug} is retired")
    target_environment_id = str(
        target_environment_id or plan["target_environment_id"] or ""
    )
    if target_environment_id:
        _validate_target_environment(
            conn,
            project_id=project_id,
            environment_id=target_environment_id,
        )

    normalized_cases = _validated_plan_cases(
        conn,
        plan=plan,
        cases=cases,
    )
    current_updated_at = str(plan["updated_at"])
    desired_plan = {
        "name": str(name),
        "description": str(description),
        "success_policy_id": success_policy_id,
        "success_policy_params": dict(success_policy_params),
        "target_environment_id": str(target_environment_id),
    }
    current_plan = {
        "name": str(plan["name"]),
        "description": str(plan["description"]),
        "success_policy_id": str(plan["success_policy_id"]),
        "success_policy_params": _decode(
            plan["success_policy_params"],
            {},
        ),
        "target_environment_id": str(plan["target_environment_id"] or ""),
    }
    current_cases = _current_cases(conn, int(plan["id"]))
    if str(base_updated_at) != current_updated_at:
        raise QaPlanConflictError(
            f"QA plan {slug!r} changed after it was read; reopen the editor "
            "from the latest plan before writing again"
        )
    if desired_plan == current_plan and normalized_cases == current_cases:
        try:
            live_token = conn.execute(
                "UPDATE qa_plans SET updated_at=updated_at "
                f"WHERE id={marker} AND updated_at={marker} "
                "RETURNING updated_at",
                (int(plan["id"]), str(base_updated_at)),
            ).fetchone()
            if live_token is None:
                raise QaPlanConflictError(
                    f"QA plan {slug!r} changed while the edit was being "
                    "saved; reopen the editor from the latest plan"
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return {
            "plan_id": int(plan["id"]),
            "project_id": project_id,
            "project": str(plan["project"]),
            "slug": str(plan["slug"]),
            "case_count": len(normalized_cases),
            "updated_at": current_updated_at,
            "unchanged": True,
        }

    stamp = _next_updated_at()
    try:
        cursor = conn.execute(
            "UPDATE qa_plans SET name={m}, description={m}, "
            "success_policy_id={m}, success_policy_params={m}, "
            "target_environment_id={m}, updated_at={m} "
            "WHERE id={m} AND updated_at={m}".format(
                m=marker,
            ),
            (
                desired_plan["name"],
                desired_plan["description"],
                desired_plan["success_policy_id"],
                _json(desired_plan["success_policy_params"]),
                desired_plan["target_environment_id"],
                stamp,
                int(plan["id"]),
                str(base_updated_at),
            ),
        )
        if cursor.rowcount == 0:
            raise QaPlanConflictError(
                f"QA plan {slug!r} changed while the edit was being saved; "
                "reopen the editor from the latest plan"
            )
        _insert_cases(
            conn,
            marker=marker,
            plan_id=int(plan["id"]),
            cases=normalized_cases,
            stamp=stamp,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "plan_id": int(plan["id"]),
        "project_id": project_id,
        "project": str(plan["project"]),
        "slug": str(plan["slug"]),
        "case_count": len(normalized_cases),
        "updated_at": stamp,
        "unchanged": False,
    }


__all__ = [
    "QaPlanConflictError",
    "edit_plan",
]
