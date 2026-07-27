"""Authoring, attachment, and snapshot materialization for QA plans."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.project_identity import resolve_project


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class QaPlanError(ValueError):
    """A requested plan mutation violates the QA catalog contract."""


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _next_updated_at() -> str:
    """Mint a precise token for compare-and-swap protected plan writes."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _project_id(conn: Any, project: str) -> int:
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise QaPlanError(f"project {project!r} not found")
    return int(identity.id)


def _plan_row(conn: Any, plan_id: int) -> Any:
    marker = _placeholder(conn)
    row = query_one(
        conn,
        f"SELECT * FROM qa_plans WHERE id={marker}",
        (int(plan_id),),
    )
    if row is None:
        raise QaPlanError(f"QA plan {plan_id} not found")
    if row["retired_at"] is not None:
        raise QaPlanError(f"QA plan {plan_id} is retired")
    return row


def create_plan(
    conn: Any,
    *,
    project: str,
    slug: str,
    name: Optional[str] = None,
    description: str = "",
    success_policy_id: str = "all-pass",
    success_policy_params: Optional[dict] = None,
) -> dict:
    """Create one project-scoped plan."""
    if not _SLUG_RE.fullmatch(slug):
        raise QaPlanError(
            "plan slug must contain lowercase words separated by hyphens"
        )
    if success_policy_id != "all-pass":
        raise QaPlanError("v1 supports only the all-pass success policy")
    project_id = _project_id(conn, project)
    marker = _placeholder(conn)
    now = _next_updated_at()
    try:
        row = conn.execute(
            "INSERT INTO qa_plans("
            "project_id, slug, name, description, success_policy_id, "
            "success_policy_params, created_at, updated_at"
            f") VALUES ({', '.join([marker] * 8)}) RETURNING id",
            (
                project_id,
                slug,
                name or slug,
                description,
                success_policy_id,
                _json(success_policy_params or {}),
                now,
                now,
            ),
        ).fetchone()
    except Exception as exc:
        if "qa_plans_project_id_slug" in str(exc) or "unique" in str(exc).lower():
            raise QaPlanError(
                f"QA plan {project}/{slug} already exists"
            ) from exc
        raise
    conn.commit()
    return {
        "id": int(row["id"] if isinstance(row, dict) else row[0]),
        "project_id": project_id,
        "project": project,
        "slug": slug,
        "name": name or slug,
    }


def _validated_cases(cases: list[dict]) -> list[dict]:
    from yoke_core.domain.qa_method_config_validation import (
        QaMethodConfigError,
        validate_method_config,
    )

    if not cases:
        raise QaPlanError("a plan must contain at least one case")
    keys: set[str] = set()
    positions: set[int] = set()
    result = []
    for raw in cases:
        if not isinstance(raw, dict):
            raise QaPlanError("each plan case must be a JSON object")
        key = str(raw.get("case_key") or "")
        position = int(raw.get("position") or 0)
        method_id = str(raw.get("method_id") or "")
        if not _SLUG_RE.fullmatch(key):
            raise QaPlanError(f"invalid case key {key!r}")
        if key in keys:
            raise QaPlanError(f"duplicate case key {key!r}")
        if position < 1 or position in positions:
            raise QaPlanError(f"invalid or duplicate case position {position}")
        if not method_id:
            raise QaPlanError(f"case {key!r} requires method_id")
        instructions = str(raw.get("instructions") or "").strip()
        expected = str(raw.get("expected_outcome") or "").strip()
        if not instructions or not expected:
            raise QaPlanError(
                f"case {key!r} requires instructions and expected_outcome"
            )
        baselines = raw.get("host_baselines") or []
        if (
            not isinstance(baselines, list)
            or any(not isinstance(value, str) or not value for value in baselines)
        ):
            raise QaPlanError(
                f"case {key!r} host_baselines must be non-empty strings"
            )
        policy_id = raw.get("success_policy_id")
        if policy_id not in (None, "all-pass"):
            raise QaPlanError(
                f"case {key!r}: v1 supports only the all-pass success policy"
            )
        policy_params = raw.get("success_policy_params")
        if policy_params is not None and not isinstance(policy_params, dict):
            raise QaPlanError(
                f"case {key!r} success_policy_params must be a JSON object"
            )
        keys.add(key)
        positions.add(position)
        try:
            method_config = validate_method_config(
                method_id, raw.get("method_config"),
            )
        except QaMethodConfigError as exc:
            raise QaPlanError(f"case {key!r}: {exc}") from exc
        result.append({
            **raw,
            "case_key": key,
            "position": position,
            "method_id": method_id,
            "instructions": instructions,
            "expected_outcome": expected,
            "method_config": method_config,
            "success_policy_id": policy_id,
            "success_policy_params": policy_params,
            "host_baselines": list(dict.fromkeys(baselines)),
            "entry_surface": raw.get("entry_surface"),
            "required_completion": raw.get("required_completion"),
        })
    return sorted(result, key=lambda case: case["position"])


def _validated_plan_cases(
    conn: Any,
    *,
    plan: Any,
    cases: list[dict],
) -> list[dict]:
    """Validate case content and method availability for one plan project."""
    cases = _validated_cases(cases)
    marker = _placeholder(conn)
    method_ids = list(dict.fromkeys(case["method_id"] for case in cases))
    method_rows = query_rows(
        conn,
        "SELECT id, executor_id, verdict_path, project_id "
        "FROM qa_methods WHERE id IN ("
        + ", ".join([marker] * len(method_ids))
        + ")",
        tuple(method_ids),
    )
    contracts = {
        str(row["id"]): row
        for row in method_rows
        if row["project_id"] is None
        or int(row["project_id"]) == int(plan["project_id"])
    }
    missing = [
        method_id for method_id in method_ids if method_id not in contracts
    ]
    if missing:
        raise QaPlanError(
            "QA methods are unknown or unavailable to this project: "
            + ", ".join(missing)
        )
    from yoke_core.domain.qa_method_config_validation import (
        QaMethodConfigError,
        validate_method_config,
    )

    for case in cases:
        contract = contracts[case["method_id"]]
        config_method = case["method_id"]
        if config_method not in {
            "command", "browser-check", "browser-inspection",
        }:
            if contract["executor_id"] == "worktree_run":
                config_method = "command"
            elif contract["executor_id"] == "browser_substrate":
                config_method = (
                    "browser-inspection"
                    if contract["verdict_path"] == "agent"
                    else "browser-check"
                )
        try:
            case["method_config"] = validate_method_config(
                config_method, case["method_config"],
            )
        except QaMethodConfigError as exc:
            raise QaPlanError(
                f"case {case['case_key']!r}: {exc}"
            ) from exc
    return cases


def replace_plan_cases(
    conn: Any, *, plan_id: int, cases: list[dict],
) -> dict:
    """Replace the future case specification; materialized rows stay intact."""
    plan = _plan_row(conn, plan_id)
    cases = _validated_plan_cases(conn, plan=plan, cases=cases)
    marker = _placeholder(conn)
    now = _next_updated_at()
    conn.execute(
        f"UPDATE qa_plans SET updated_at={marker} WHERE id={marker}",
        (now, plan_id),
    )
    conn.execute(f"DELETE FROM qa_plan_cases WHERE plan_id={marker}", (plan_id,))
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
                _json(case.get("method_config") or {}),
                case.get("success_policy_id"),
                _json(case.get("success_policy_params"))
                if case.get("success_policy_params") is not None else None,
                _json(case["host_baselines"]),
                case.get("entry_surface"),
                case.get("required_completion"),
                now,
                now,
            ),
        )
    conn.commit()
    return {"plan_id": int(plan_id), "case_count": len(cases)}


__all__ = [
    "QaPlanError",
    "create_plan",
    "replace_plan_cases",
]
