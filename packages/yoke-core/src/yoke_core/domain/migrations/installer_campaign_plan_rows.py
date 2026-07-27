"""Replace the Markdown installer catalogs with one executable QA plan."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.installer_campaign_cases import (
    EXPECTED_CASE_KEYS,
    INSTALLER_CAMPAIGN_CASES,
    campaign_contract_digest,
)
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.schema_common import _table_exists


MIGRATION_NAME = "installer_campaign_plan_rows"
PLAN_SLUG = "installer-campaign"
CAMPAIGN_CONTRACT_SHA256 = (
    "55068134171d66faf19bf55f3c3c76f8870960604572cd018fad50e6c24b7b08"
)


def _require_bound_contract(error_type: type[Exception]) -> None:
    if campaign_contract_digest() != CAMPAIGN_CONTRACT_SHA256:
        raise error_type("installer campaign contract digest differs")


def apply(conn: Any) -> None:
    """Create or replace yoke's project-owned installer campaign."""
    _require_bound_contract(RuntimeError)
    required = (
        "projects",
        "qa_methods",
        "qa_plans",
        "qa_plan_cases",
    )
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "installer campaign requires deployed QA tables: "
            + ", ".join(missing)
        )
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    project = conn.execute(
        "SELECT id FROM projects WHERE slug='yoke'"
    ).fetchone()
    if project is None:
        raise RuntimeError("installer campaign requires project 'yoke'")
    row = conn.execute(
        f"SELECT id FROM qa_plans WHERE project_id={marker} AND slug={marker}",
        (int(project[0]), PLAN_SLUG),
    ).fetchone()
    if row is None:
        created = create_plan(
            conn,
            project="yoke",
            slug=PLAN_SLUG,
            name="Installer campaign",
            description=(
                "Physical Test Mac proof for installer interaction, Terminal "
                "presentation, and post-install machine state."
            ),
        )
        plan_id = int(created["id"])
    else:
        plan_id = int(row[0])
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[dict(case) for case in INSTALLER_CAMPAIGN_CASES],
    )


def invariants(conn: Any) -> None:
    """Require the complete code-owned scenario catalog in one QA plan."""
    _require_bound_contract(AssertionError)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT c.case_key,c.method_id,c.host_baselines,c.entry_surface,"
        "c.required_completion,c.instructions,c.expected_outcome,"
        "c.method_config "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "JOIN projects pr ON pr.id=p.project_id "
        f"WHERE pr.slug='yoke' AND p.slug={marker} ORDER BY c.position",
        (PLAN_SLUG,),
    ).fetchall()
    keys = tuple(str(row[0]) for row in rows)
    if keys != EXPECTED_CASE_KEYS:
        raise AssertionError(
            f"installer campaign case order differs: {keys!r}"
        )
    methods = [str(row[1]) for row in rows]
    expected_method_counts = {
        method: sum(
            case["method_id"] == method
            for case in INSTALLER_CAMPAIGN_CASES
        )
        for method in (
            "terminal-check",
            "terminal-inspection",
            "machine-state-check",
        )
    }
    actual_method_counts = {
        method: methods.count(method)
        for method in expected_method_counts
    }
    if actual_method_counts != expected_method_counts:
        raise AssertionError(
            "installer campaign method roster differs: "
            f"{actual_method_counts!r}"
        )
    expanded_count = sum(
        max(1, len(json.loads(str(row[2] or "[]"))))
        for row in rows
    )
    expected_expanded_count = sum(
        max(1, len(case["host_baselines"]))
        for case in INSTALLER_CAMPAIGN_CASES
    )
    if expanded_count != expected_expanded_count:
        raise AssertionError(
            "installer campaign baseline expansion differs: "
            f"{expanded_count}, expected {expected_expanded_count}"
        )
    for row, case in zip(rows, INSTALLER_CAMPAIGN_CASES, strict=True):
        if str(row[5]) != case["instructions"]:
            raise AssertionError(
                f"installer campaign instructions differ for {row[0]}"
            )
        if str(row[6]) != case["expected_outcome"]:
            raise AssertionError(
                f"installer campaign expected outcome differs for {row[0]}"
            )
        if json.loads(str(row[7])) != case["method_config"]:
            raise AssertionError(
                f"installer campaign method config differs for {row[0]}"
            )
        if str(row[1]).startswith("terminal-"):
            if not row[3] or not row[4]:
                raise AssertionError(
                    f"Terminal case {row[0]} lacks entry or completion"
                )
            steps = case["method_config"]["steps"]
            if case["method_id"] == "terminal-inspection" and not all(
                step.get("send") for step in steps
            ):
                raise AssertionError(
                    f"interactive Terminal case {row[0]} lacks input"
                )


__all__ = [
    "CAMPAIGN_CONTRACT_SHA256",
    "EXPECTED_CASE_KEYS",
    "INSTALLER_CAMPAIGN_CASES",
    "MIGRATION_NAME",
    "PLAN_SLUG",
    "apply",
    "invariants",
]
