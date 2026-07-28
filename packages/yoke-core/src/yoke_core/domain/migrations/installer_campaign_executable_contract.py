"""Converge the installer campaign to its executable Machine QA contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.installer_campaign_cases import (
    EXPECTED_CASE_KEYS,
    EXPECTED_METHOD_COUNTS,
    EXPECTED_REQUIREMENT_COUNT,
    INSTALLER_CAMPAIGN_CASES,
    campaign_contract_digest,
)
from yoke_core.domain.machine_qa_method_contracts import (
    MachineQaExecutionError,
    validate_machine_method_config,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.schema_common import _table_exists


MIGRATION_NAME = "installer_campaign_executable_contract"
PLAN_SLUG = "installer-campaign"
PLAN_NAME = "Installer campaign"
PLAN_DESCRIPTION = (
    "Physical Test Mac proof for the public installer, onboarding "
    "Terminal frames, and resulting machine state."
)
CAMPAIGN_CONTRACT_SHA256 = (
    "984de4964319ce3c8d588fdfac1202c8e9ce207f47ac05b77fdac7268bd5417a"
)


def _require_bound_contract(error_type: type[Exception]) -> None:
    if campaign_contract_digest() != CAMPAIGN_CONTRACT_SHA256:
        raise error_type("installer campaign contract digest differs")


def _project_and_plan(conn: Any) -> tuple[int, int | None]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    project = conn.execute("SELECT id FROM projects WHERE slug='yoke'").fetchone()
    if project is None:
        raise RuntimeError("installer campaign requires project 'yoke'")
    project_id = int(project[0])
    row = conn.execute(
        f"SELECT id FROM qa_plans WHERE project_id={marker} AND slug={marker}",
        (project_id, PLAN_SLUG),
    ).fetchone()
    return project_id, None if row is None else int(row[0])


def _converge_metadata(conn: Any, *, project_id: int) -> None:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE qa_plans SET name={marker}, description={marker} "
        f"WHERE project_id={marker} AND slug={marker} "
        f"AND (COALESCE(name, '') <> {marker} "
        f"OR COALESCE(description, '') <> {marker})",
        (
            PLAN_NAME,
            PLAN_DESCRIPTION,
            project_id,
            PLAN_SLUG,
            PLAN_NAME,
            PLAN_DESCRIPTION,
        ),
    )


def apply(conn: Any) -> None:
    """Replace any earlier catalog rows with the executable campaign."""
    _require_bound_contract(RuntimeError)
    required = ("projects", "qa_methods", "qa_plans", "qa_plan_cases")
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "installer campaign requires deployed QA tables: " + ", ".join(missing)
        )
    project_id, plan_id = _project_and_plan(conn)
    if plan_id is None:
        created = create_plan(
            conn,
            project="yoke",
            slug=PLAN_SLUG,
            name=PLAN_NAME,
            description=PLAN_DESCRIPTION,
        )
        plan_id = int(created["id"])
    else:
        _converge_metadata(conn, project_id=project_id)
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[dict(case) for case in INSTALLER_CAMPAIGN_CASES],
    )


def _contains_execution_blocker(value: Any) -> bool:
    if isinstance(value, Mapping):
        return "execution_blocker" in value or any(
            _contains_execution_blocker(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_execution_blocker(child) for child in value)
    return False


def _require_executable_contract(case: Mapping[str, Any]) -> None:
    case_key = str(case["case_key"])
    config = case["method_config"]
    if not isinstance(config, Mapping):
        raise AssertionError(f"{case_key} method config is not an object")
    if _contains_execution_blocker(config):
        raise AssertionError(f"{case_key} contains an execution blocker")
    try:
        validate_machine_method_config(
            str(case["method_id"]),
            config,
            entry_surface=case["entry_surface"],
            required_completion=case["required_completion"],
        )
        for baseline in case["host_baselines"]:
            validate_machine_method_config(
                str(case["method_id"]),
                config,
                entry_surface=case["entry_surface"],
                required_completion=case["required_completion"],
                host_baseline=str(baseline),
            )
    except MachineQaExecutionError as exc:
        raise AssertionError(f"{case_key} is not executable: {exc}") from exc
    if str(case["method_id"]).startswith("terminal-"):
        if (
            not str(case["entry_surface"] or "").strip()
            or len(str(case["entry_surface"])) > 2000
            or not str(case["required_completion"] or "").strip()
        ):
            raise AssertionError(
                f"Terminal case {case_key} lacks bounded entry or completion"
            )
    elif case["entry_surface"] is not None or case["required_completion"] is not None:
        raise AssertionError(f"Machine state case {case_key} has Terminal fields")


def invariants(conn: Any) -> None:
    """Require the exact executable campaign after convergence."""
    _require_bound_contract(AssertionError)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT p.name,p.description,c.case_key,c.position,c.method_id,"
        "c.host_baselines,c.entry_surface,c.required_completion,"
        "c.instructions,c.expected_outcome,c.method_config "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "JOIN projects pr ON pr.id=p.project_id "
        f"WHERE pr.slug='yoke' AND p.slug={marker} ORDER BY c.position",
        (PLAN_SLUG,),
    ).fetchall()
    keys = tuple(str(row[2]) for row in rows)
    if keys != EXPECTED_CASE_KEYS:
        raise AssertionError(f"installer campaign case order differs: {keys!r}")
    if any((str(row[0]), str(row[1])) != (PLAN_NAME, PLAN_DESCRIPTION) for row in rows):
        raise AssertionError("installer campaign metadata differs")
    methods = [str(row[4]) for row in rows]
    actual_method_counts = {
        method: methods.count(method) for method in EXPECTED_METHOD_COUNTS
    }
    if actual_method_counts != EXPECTED_METHOD_COUNTS:
        raise AssertionError(
            f"installer campaign method roster differs: {actual_method_counts!r}"
        )
    expanded_count = sum(max(1, len(json.loads(str(row[5] or "[]")))) for row in rows)
    if expanded_count != EXPECTED_REQUIREMENT_COUNT:
        raise AssertionError(
            "installer campaign baseline expansion differs: "
            f"{expanded_count}, expected {EXPECTED_REQUIREMENT_COUNT}"
        )
    baseline_cases = {
        str(row[2]): json.loads(str(row[5]))
        for row in rows
        if json.loads(str(row[5] or "[]"))
    }
    if baseline_cases != {
        "cold-start-hosted": ["fresh-host", "shell-preconfigured"],
        "path-on-shell": ["fresh-host", "shell-preconfigured"],
    }:
        raise AssertionError(
            f"installer campaign baseline roster differs: {baseline_cases!r}"
        )
    for expected_position, (row, case) in enumerate(
        zip(rows, INSTALLER_CAMPAIGN_CASES, strict=True),
        start=1,
    ):
        if int(row[3]) != expected_position:
            raise AssertionError(f"installer campaign position differs for {row[2]}")
        if str(row[4]) != case["method_id"]:
            raise AssertionError(f"installer campaign method differs for {row[2]}")
        if json.loads(str(row[5] or "[]")) != case["host_baselines"]:
            raise AssertionError(f"installer campaign baselines differ for {row[2]}")
        if row[6] != case["entry_surface"] or row[7] != case["required_completion"]:
            raise AssertionError(
                f"installer campaign Terminal contract differs for {row[2]}"
            )
        if str(row[8]) != case["instructions"]:
            raise AssertionError(f"installer campaign instructions differ for {row[2]}")
        if str(row[9]) != case["expected_outcome"]:
            raise AssertionError(
                f"installer campaign expected outcome differs for {row[2]}"
            )
        if json.loads(str(row[10])) != case["method_config"]:
            raise AssertionError(
                f"installer campaign method config differs for {row[2]}"
            )
        _require_executable_contract(case)


__all__ = [
    "CAMPAIGN_CONTRACT_SHA256",
    "MIGRATION_NAME",
    "PLAN_DESCRIPTION",
    "PLAN_NAME",
    "PLAN_SLUG",
    "apply",
    "invariants",
]
