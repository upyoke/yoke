"""Gate local project selection and settle multi-key terminal input."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.installer_campaign_cases import (
    EXPECTED_CASE_KEYS,
    EXPECTED_METHOD_COUNTS,
    EXPECTED_REQUIREMENT_COUNT,
)
from yoke_core.domain.installer_campaign_key_settle_cases import (
    KEY_SETTLED_INSTALLER_CAMPAIGN_CASES,
    key_settled_campaign_digest,
)
from yoke_core.domain.migrations.installer_campaign_screen_ready_plan import (
    _plan_id,
    _require_executable_contract,
)
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.schema_common import _table_exists


MIGRATION_NAME = "installer_campaign_key_settle_plan"
PLAN_SLUG = "installer-campaign"
CAMPAIGN_CONTRACT_SHA256 = (
    "55d4dadc1c893fa57e6f5f9c9242fdcf9bf7a9815a722e6fc7234cd2f368b1ea"
)


def _require_bound_contract(error_type: type[Exception]) -> None:
    if key_settled_campaign_digest() != CAMPAIGN_CONTRACT_SHA256:
        raise error_type("key-settled installer campaign digest differs")


def apply(conn: Any) -> None:
    """Replace only the future installer case specification."""
    _require_bound_contract(RuntimeError)
    required = ("projects", "qa_methods", "qa_plans", "qa_plan_cases")
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "key-settled installer campaign requires deployed QA tables: "
            + ", ".join(missing)
        )
    replace_plan_cases(
        conn,
        plan_id=_plan_id(conn),
        cases=[dict(case) for case in KEY_SETTLED_INSTALLER_CAMPAIGN_CASES],
    )


def invariants(conn: Any) -> None:
    """Require the exact current key-settled campaign contract."""
    _require_bound_contract(AssertionError)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT c.case_key,c.position,c.method_id,c.host_baselines,"
        "c.entry_surface,c.required_completion,c.instructions,"
        "c.expected_outcome,c.method_config "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "JOIN projects pr ON pr.id=p.project_id "
        f"WHERE pr.slug='yoke' AND p.slug={marker} ORDER BY c.position",
        (PLAN_SLUG,),
    ).fetchall()
    keys = tuple(str(row[0]) for row in rows)
    if keys != EXPECTED_CASE_KEYS:
        raise AssertionError(f"installer campaign case order differs: {keys!r}")
    methods = Counter(str(row[2]) for row in rows)
    if dict(methods) != EXPECTED_METHOD_COUNTS:
        raise AssertionError(f"installer campaign method roster differs: {methods!r}")
    expanded = sum(max(1, len(json.loads(str(row[3] or "[]")))) for row in rows)
    if expanded != EXPECTED_REQUIREMENT_COUNT:
        raise AssertionError(f"installer campaign expands to {expanded} requirements")
    for row, case in zip(
        rows,
        KEY_SETTLED_INSTALLER_CAMPAIGN_CASES,
        strict=True,
    ):
        stored = {
            "case_key": str(row[0]),
            "position": int(row[1]),
            "method_id": str(row[2]),
            "host_baselines": json.loads(str(row[3] or "[]")),
            "entry_surface": row[4],
            "required_completion": row[5],
            "instructions": str(row[6]),
            "expected_outcome": str(row[7]),
            "method_config": json.loads(str(row[8])),
        }
        expected = {key: case[key] for key in stored}
        if stored != expected:
            raise AssertionError(f"installer campaign contract differs for {row[0]}")
        _require_executable_contract(case)


__all__ = [
    "CAMPAIGN_CONTRACT_SHA256",
    "MIGRATION_NAME",
    "PLAN_SLUG",
    "apply",
    "invariants",
]
