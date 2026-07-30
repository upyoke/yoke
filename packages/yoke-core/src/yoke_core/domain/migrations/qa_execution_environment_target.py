"""Bind QA plans and new executions to one environment identity."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.qa_execution_environment_target import (
    resolve_plan_execution_target,
    select_backfill_environment,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


MIGRATION_NAME = "qa_execution_environment_target"
_PLAN_COLUMN = "target_environment_id"
_SNAPSHOT_COLUMNS = ("execution_target_json", "execution_target_digest")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _add_columns(conn: Any) -> None:
    if not _column_exists(conn, "qa_plans", _PLAN_COLUMN):
        conn.execute(
            "ALTER TABLE qa_plans ADD COLUMN target_environment_id "
            "TEXT REFERENCES environments(id)"
        )
    for column in _SNAPSHOT_COLUMNS:
        if not _column_exists(conn, "qa_requirements", column):
            conn.execute(f"ALTER TABLE qa_requirements ADD COLUMN {column} TEXT")
        if not _column_exists(conn, "qa_plan_executions", column):
            conn.execute(f"ALTER TABLE qa_plan_executions ADD COLUMN {column} TEXT")


def _plan_rows(conn: Any) -> list[dict[str, Any]]:
    cursor = conn.execute(
        "SELECT id,project_id,slug,target_environment_id "
        "FROM qa_plans WHERE retired_at IS NULL ORDER BY id"
    )
    columns = [str(column[0]) for column in cursor.description]
    return [
        (
            {str(key): row[key] for key in row.keys()}
            if hasattr(row, "keys")
            else dict(zip(columns, row))
        )
        for row in cursor.fetchall()
    ]


def _bind_missing_plan_targets(conn: Any) -> None:
    marker = _p(conn)
    for plan in _plan_rows(conn):
        if plan["target_environment_id"]:
            continue
        environment_id = select_backfill_environment(
            conn,
            project_id=int(plan["project_id"]),
        )
        conn.execute(
            f"UPDATE qa_plans SET target_environment_id={marker} WHERE id={marker}",
            (environment_id, int(plan["id"])),
        )


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _normalized_case_rows(rows: list[Any]) -> list[tuple[Any, ...]]:
    result = []
    for row in rows:
        values = (
            tuple(row[key] for key in row.keys())
            if hasattr(row, "keys")
            else tuple(row)
        )
        mutable = list(values)
        for index, fallback in ((5, {}), (7, None), (8, [])):
            mutable[index] = (
                json.loads(str(mutable[index]))
                if mutable[index] is not None
                else fallback
            )
        result.append(tuple(mutable))
    return result


def _expected_case_rows(cases: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            case["case_key"],
            case["position"],
            case["method_id"],
            case["instructions"],
            case["expected_outcome"],
            case["method_config"],
            case.get("success_policy_id"),
            case.get("success_policy_params"),
            case["host_baselines"],
            case.get("entry_surface"),
            case.get("required_completion"),
        )
        for case in cases
    ]


def _replace_installer_cases(
    conn: Any,
    *,
    plan_id: int,
    target: dict[str, Any],
) -> None:
    marker = _p(conn)
    rows = conn.execute(
        "SELECT id,name,executor_id,required_capability_kind,verdict_path "
        "FROM qa_methods"
    ).fetchall()
    methods = {
        str(row[0] if not hasattr(row, "keys") else row["id"]): row
        for row in rows
    }
    cases = installer_campaign_cases_for_target(target)
    missing = sorted({case["method_id"] for case in cases} - set(methods))
    if missing:
        raise RuntimeError(
            "installer campaign target migration lacks methods: "
            + ", ".join(missing)
        )
    current = conn.execute(
        "SELECT case_key,position,method_id,instructions,expected_outcome,"
        "method_config,success_policy_id,success_policy_params,host_baselines,"
        f"entry_surface,required_completion FROM qa_plan_cases WHERE plan_id={marker} "
        "ORDER BY position",
        (plan_id,),
    ).fetchall()

    if _normalized_case_rows(list(current)) == _expected_case_rows(cases):
        return
    conn.execute(f"DELETE FROM qa_plan_cases WHERE plan_id={marker}", (plan_id,))
    now = conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
    for case in cases:
        method = methods[str(case["method_id"])]

        def value(key: str, index: int) -> Any:
            return method[key] if hasattr(method, "keys") else method[index]

        # Force method lookup here so a malformed Pack row fails before insert.
        if not str(value("name", 1) or "") or not str(value("executor_id", 2) or ""):
            raise RuntimeError(f"QA method {case['method_id']!r} is incomplete")
        conn.execute(
            "INSERT INTO qa_plan_cases("
            "plan_id,case_key,position,method_id,instructions,expected_outcome,"
            "method_config,success_policy_id,success_policy_params,"
            "host_baselines,entry_surface,required_completion,created_at,updated_at"
            f") VALUES ({', '.join([marker] * 14)})",
            (
                plan_id,
                case["case_key"],
                case["position"],
                case["method_id"],
                case["instructions"],
                case["expected_outcome"],
                _json(case["method_config"]),
                case.get("success_policy_id"),
                (
                    _json(case["success_policy_params"])
                    if case.get("success_policy_params") is not None
                    else None
                ),
                _json(case["host_baselines"]),
                case.get("entry_surface"),
                case.get("required_completion"),
                str(now),
                str(now),
            ),
        )


def _converge_targeted_plans(conn: Any) -> None:
    for plan in _plan_rows(conn):
        target = resolve_plan_execution_target(
            conn,
            plan_id=int(plan["id"]),
            require_runtime_match=True,
        )
        if str(plan["slug"]) == "installer-campaign":
            _replace_installer_cases(
                conn,
                plan_id=int(plan["id"]),
                target=target,
            )


def apply(conn: Any) -> None:
    """Add target snapshots and bind every active plan to this runtime."""
    required = (
        "organizations",
        "projects",
        "sites",
        "environments",
        "qa_plans",
        "qa_plan_cases",
        "qa_requirements",
        "qa_plan_executions",
    )
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "QA execution target migration requires deployed tables: "
            + ", ".join(missing)
        )
    _add_columns(conn)
    _bind_missing_plan_targets(conn)
    _converge_targeted_plans(conn)


def invariants(conn: Any) -> None:
    """Require all active plans to resolve one runtime-compatible target."""
    for table, columns in (
        ("qa_plans", (_PLAN_COLUMN,)),
        ("qa_requirements", _SNAPSHOT_COLUMNS),
        ("qa_plan_executions", _SNAPSHOT_COLUMNS),
    ):
        missing = [
            column for column in columns if not _column_exists(conn, table, column)
        ]
        if missing:
            raise AssertionError(f"{table} lacks target columns: {missing}")
    unbound = conn.execute(
        "SELECT id FROM qa_plans "
        "WHERE retired_at IS NULL AND target_environment_id IS NULL LIMIT 1"
    ).fetchone()
    if unbound is not None:
        raise AssertionError("an active QA plan has no execution environment target")
    for plan in _plan_rows(conn):
        target = resolve_plan_execution_target(
            conn,
            plan_id=int(plan["id"]),
            require_runtime_match=True,
        )
        if str(plan["slug"]) == "installer-campaign":
            expected = installer_campaign_cases_for_target(target)
            actual = conn.execute(
                "SELECT case_key,position,method_id,instructions,expected_outcome,"
                "method_config,success_policy_id,success_policy_params,"
                "host_baselines,entry_surface,required_completion "
                "FROM qa_plan_cases "
                f"WHERE plan_id={_p(conn)} ORDER BY position",
                (int(plan["id"]),),
            ).fetchall()
            if _normalized_case_rows(list(actual)) != _expected_case_rows(expected):
                raise AssertionError(
                    "installer campaign cases do not match their execution target"
                )


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
