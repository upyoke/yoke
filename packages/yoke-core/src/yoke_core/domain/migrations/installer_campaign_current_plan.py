"""Converge the installer campaign wherever the Yoke project exists."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.installer_campaign_current_text_cases import (
    CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
    current_text_campaign_digest,
)
from yoke_core.domain.machine_qa_method_contracts import (
    MachineQaExecutionError,
    validate_machine_method_config,
)
from yoke_core.domain.machine_qa_pack import (
    MACHINE_QA_PACK,
    load_machine_qa_methods,
    sync_machine_qa_pack_methods,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_requirement_snapshot_convergence import SNAPSHOT_COLUMNS
from yoke_core.domain.schema_common import _column_exists, _table_exists


MIGRATION_NAME = "installer_campaign_current_plan"
PLAN_SLUG = "installer-campaign"
PLAN_NAME = "Installer campaign"
PLAN_DESCRIPTION = (
    "Physical Test Mac proof for the public installer, onboarding "
    "Terminal frames, and resulting machine state."
)
CAMPAIGN_CONTRACT_SHA256 = (
    "b59d5ff1a183193107d94d78115e2ee46e56295fb989adf45d394060b98701dd"
)
_IMMUTABLE_HISTORY_COLUMNS = (
    "plan_case_key",
    "method_id",
    "instructions",
    "expected_outcome",
    "method_config",
    "host_baseline",
    *SNAPSHOT_COLUMNS,
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _require_bound_contract(error_type: type[Exception]) -> None:
    if current_text_campaign_digest() != CAMPAIGN_CONTRACT_SHA256:
        raise error_type("current installer campaign digest differs")


def _project_id(conn: Any) -> int | None:
    if not _table_exists(conn, "projects"):
        raise RuntimeError("current installer campaign requires the projects table")
    row = conn.execute("SELECT id FROM projects WHERE slug='yoke'").fetchone()
    return None if row is None else int(row[0])


def _plan_id(conn: Any, *, project_id: int) -> int | None:
    marker = _marker(conn)
    row = conn.execute(
        f"SELECT id FROM qa_plans WHERE project_id={marker} AND slug={marker}",
        (project_id, PLAN_SLUG),
    ).fetchone()
    return None if row is None else int(row[0])


def _converge_plan(
    conn: Any,
    *,
    project_id: int,
    plan_id: int | None,
) -> int:
    if plan_id is None:
        created = create_plan(
            conn,
            project="yoke",
            slug=PLAN_SLUG,
            name=PLAN_NAME,
            description=PLAN_DESCRIPTION,
        )
        return int(created["id"])
    marker = _marker(conn)
    conn.execute(
        f"UPDATE qa_plans SET name={marker}, description={marker} "
        f"WHERE id={marker}",
        (PLAN_NAME, PLAN_DESCRIPTION, plan_id),
    )
    return plan_id


def _require_immutable_history(conn: Any, *, plan_id: int) -> None:
    missing = [
        column
        for column in _IMMUTABLE_HISTORY_COLUMNS
        if not _column_exists(conn, "qa_requirements", column)
    ]
    if missing:
        raise RuntimeError(
            "installer campaign requirement snapshots are unavailable: "
            + ", ".join(missing)
        )
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT id,plan_case_key,case_position,baseline_position,"
        "method_id,method_name,executor_id,required_capability_kind,verdict_path,"
        "instructions,expected_outcome,method_config,host_baseline,"
        "entry_surface,required_completion FROM qa_requirements "
        f"WHERE plan_id={marker} ORDER BY id",
        (plan_id,),
    ).fetchall()
    incomplete = [
        int(row[0])
        for row in rows
        if not _history_snapshot_complete(row)
    ]
    if incomplete:
        raise RuntimeError(
            f"{len(incomplete)} installer campaign requirement snapshots "
            f"are incomplete: {incomplete}"
        )


def _history_snapshot_complete(row: Any) -> bool:
    text_values = (*row[1:2], *row[4:11])
    if any(not str(value or "").strip() for value in text_values):
        return False
    try:
        if int(row[2]) < 1 or int(row[3]) < 1:
            return False
        config = _json_value(row[11], None)
        if not isinstance(config, Mapping):
            return False
        host_baseline = None if row[12] is None else str(row[12])
        variants = config.get("baseline_configs")
        if variants is not None and (
            not isinstance(variants, Mapping)
            or not host_baseline
            or host_baseline not in variants
            or not isinstance(variants[host_baseline], Mapping)
        ):
            return False
        if str(row[4]).startswith("terminal-") and (
            not str(row[13] or "").strip()
            or not str(row[14] or "").strip()
        ):
            return False
    except (TypeError, ValueError):
        return False
    return not _contains_execution_blocker(config)


def _contains_execution_blocker(value: Any) -> bool:
    if isinstance(value, Mapping):
        return "execution_blocker" in value or any(
            _contains_execution_blocker(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_execution_blocker(child) for child in value)
    return False


def _require_executable_cases(error_type: type[Exception]) -> None:
    for case in CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES:
        method_id = str(case["method_id"])
        config = case["method_config"]
        if _contains_execution_blocker(config):
            raise error_type(
                f"installer campaign case {case['case_key']} has an execution blocker"
            )
        try:
            validate_machine_method_config(
                method_id,
                config,
                entry_surface=case["entry_surface"],
                required_completion=case["required_completion"],
            )
            for baseline in case["host_baselines"]:
                validate_machine_method_config(
                    method_id,
                    config,
                    entry_surface=case["entry_surface"],
                    required_completion=case["required_completion"],
                    host_baseline=str(baseline),
                )
        except MachineQaExecutionError as exc:
            raise error_type(
                f"installer campaign case {case['case_key']} is not executable: {exc}"
            ) from exc


def apply(conn: Any) -> None:
    """Replace the future plan contract, or no-op outside Yoke tenants."""
    _require_bound_contract(RuntimeError)
    project_id = _project_id(conn)
    if project_id is None:
        return
    _require_executable_cases(RuntimeError)
    required = ("qa_methods", "qa_plans", "qa_plan_cases", "qa_requirements")
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "current installer campaign requires deployed QA tables: "
            + ", ".join(missing)
        )
    plan_id = _plan_id(conn, project_id=project_id)
    if plan_id is not None:
        _require_immutable_history(conn, plan_id=plan_id)
    sync_machine_qa_pack_methods(conn)
    replace_plan_cases(
        conn,
        plan_id=_converge_plan(
            conn,
            project_id=project_id,
            plan_id=plan_id,
        ),
        cases=[dict(case) for case in CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES],
    )


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def invariants(conn: Any) -> None:
    """Require the final plan only when this tenant owns the Yoke project."""
    _require_bound_contract(AssertionError)
    project_id = _project_id(conn)
    if project_id is None:
        return
    _require_executable_cases(AssertionError)
    _, expected_methods = load_machine_qa_methods()
    method_ids = [str(method["id"]) for method in expected_methods]
    marker = _marker(conn)
    method_rows = conn.execute(
        "SELECT id,name,description,source_kind,source_ref,project_id,"
        "executor_id,required_capability_kind,verdict_path,verdict_contract,"
        "evidence_contract,success_policy_id,success_policy_params,"
        "concurrency_mode FROM qa_methods WHERE id IN ("
        + ", ".join([marker] * len(method_ids))
        + ") ORDER BY id",
        tuple(method_ids),
    ).fetchall()
    actual_methods = [tuple(row) for row in method_rows]
    expected_method_rows = sorted(
        (
            method["id"],
            method["name"],
            method["description"],
            "pack",
            MACHINE_QA_PACK,
            None,
            method["executor_id"],
            method["required_capability_kind"],
            method["verdict_path"],
            method["verdict_contract"],
            method["evidence_contract"],
            "all-pass",
            "{}",
            method["concurrency_mode"],
        )
        for method in expected_methods
    )
    rows = conn.execute(
        "SELECT p.name,p.description,c.case_key,c.position,c.method_id,"
        "c.instructions,c.expected_outcome,c.method_config,"
        "c.success_policy_id,c.success_policy_params,c.host_baselines,"
        "c.entry_surface,c.required_completion "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        f"WHERE p.project_id={marker} AND p.slug={marker} ORDER BY c.position",
        (project_id, PLAN_SLUG),
    ).fetchall()
    actual = [
        {
            "case_key": str(row[2]),
            "position": int(row[3]),
            "method_id": str(row[4]),
            "instructions": str(row[5]),
            "expected_outcome": str(row[6]),
            "method_config": _json_value(row[7], {}),
            "success_policy_id": row[8],
            "success_policy_params": _json_value(row[9], None),
            "host_baselines": _json_value(row[10], []),
            "entry_surface": row[11],
            "required_completion": row[12],
        }
        for row in rows
    ]
    expected = [
        {
            **dict(case),
            "success_policy_id": case.get("success_policy_id"),
            "success_policy_params": case.get("success_policy_params"),
        }
        for case in CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES
    ]
    metadata = {(str(row[0]), str(row[1])) for row in rows}
    if (
        actual != expected
        or metadata != {(PLAN_NAME, PLAN_DESCRIPTION)}
        or actual_methods != expected_method_rows
    ):
        raise AssertionError("current installer campaign plan contract differs")


__all__ = [
    "CAMPAIGN_CONTRACT_SHA256",
    "MIGRATION_NAME",
    "apply",
    "invariants",
]
