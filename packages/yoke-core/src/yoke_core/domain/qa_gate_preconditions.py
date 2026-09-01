"""Fail-closed prerequisites shared by lifecycle QA gates."""

from __future__ import annotations

import os
import sys
from typing import Optional

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.qa_constants import browser_requirement_predicate
from yoke_core.domain.qa_gate_definitions import GateResult, GateTarget
from yoke_core.domain.schema_common import _table_exists


QA_BYPASS_ENV = "YOKE_QA_GATE_BYPASS"
QA_BYPASS_FORBIDDEN = "GATE_QA_BYPASS_FORBIDDEN"
QA_SCHEMA_MISSING = "GATE_QA_SCHEMA_MISSING"
QA_BROWSER_GIT_ROOT_REQUIRED = "GATE_QA_BROWSER_GIT_ROOT_REQUIRED"

QA_CORE_TABLES = ("qa_requirements", "qa_runs")
QA_LIFECYCLE_GATE_TABLES = (
    "qa_requirements",
    "qa_runs",
    "qa_artifacts",
    "qa_plan_review_bundles",
    "qa_plan_review_verdicts",
)


def _running_under_test() -> bool:
    """Return whether this process is pytest or a child spawned by pytest."""
    return bool(str(os.environ.get("PYTEST_CURRENT_TEST") or "").strip()) or (
        "pytest" in sys.modules
    )


def qa_bypass_result(*, requested: Optional[bool] = None) -> Optional[GateResult]:
    """Return the explicit bypass verdict, or ``None`` when not requested."""
    enabled = (
        os.environ.get(QA_BYPASS_ENV) == "1" if requested is None else bool(requested)
    )
    if not enabled:
        return None
    if _running_under_test():
        return GateResult(passed=True)
    return GateResult(
        passed=False,
        errors=[
            f"{QA_BYPASS_FORBIDDEN}: {QA_BYPASS_ENV}=1 is test-only; "
            "production QA obligations cannot be bypassed.",
            f"  Recovery: unset {QA_BYPASS_ENV}, satisfy or explicitly waive "
            "each declared requirement, then retry the transition.",
        ],
    )


def qa_schema_result(
    db_path: str,
    *,
    required_tables: tuple[str, ...] = QA_LIFECYCLE_GATE_TABLES,
) -> Optional[GateResult]:
    """Refuse when the tables a lifecycle QA gate reads are unavailable."""
    conn = connect(db_path)
    try:
        missing = [table for table in required_tables if not _table_exists(conn, table)]
    finally:
        conn.close()
    if not missing:
        return None
    return GateResult(
        passed=False,
        errors=[
            f"{QA_SCHEMA_MISSING}: QA verification cannot run because required "
            f"table(s) are missing: {', '.join(missing)}.",
            "  Recovery: run this Yoke build's normal schema convergence "
            "against the target control-plane database, then retry.",
        ],
    )


def qa_gate_precondition_result(
    db_path: str,
    *,
    required_tables: tuple[str, ...] = QA_LIFECYCLE_GATE_TABLES,
) -> Optional[GateResult]:
    """Apply test-only bypass semantics, then require the full gate schema."""
    bypass = qa_bypass_result()
    if bypass is not None:
        return bypass
    return qa_schema_result(db_path, required_tables=required_tables)


def requirement_set_result(
    conn,
    *,
    target: GateTarget,
    where: str,
    params: tuple,
    name: str,
    transition_name: str,
    qa_phase: Optional[str],
) -> Optional[GateResult]:
    """Refuse a QA gate whose applicable requirement set is empty."""
    phase_sql = " AND qa_phase = 'verification'" if qa_phase else ""
    count = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM qa_requirements WHERE {where}{phase_sql}",
        params,
    )
    if count:
        return None
    from yoke_core.domain.qa_gate_requirement_teaching import (
        missing_verification_requirement_errors,
    )
    from yoke_core.domain.qa_workflow_binding_validation import (
        item_transition_for_gate,
    )
    from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION

    transition_id = item_transition_for_gate(
        conn,
        item_id=(
            int(target.item_id) if target.item_id is not None else int(target.epic_id)
        ),
        gate_id=GATE_QA_VERIFICATION,
    )
    return GateResult(
        passed=False,
        errors=missing_verification_requirement_errors(
            target=target,
            target_name=name,
            transition_id=transition_id,
            target_transition=transition_name,
        ),
    )


def browser_git_root_result(
    conn,
    *,
    where: str,
    params: tuple,
    name: str,
    transition_name: str,
    repo_root: Optional[str],
    qa_phase: Optional[str],
) -> Optional[GateResult]:
    """Refuse Browser-method gates that cannot verify checkout-local proof."""
    if repo_root:
        return None
    phase_sql = " AND r.qa_phase = 'verification'" if qa_phase else ""
    rows = query_rows(
        conn,
        f"""
        SELECT r.id, r.method_id FROM qa_requirements r
        WHERE {where}{phase_sql}
          AND r.waived_at IS NULL
          AND {browser_requirement_predicate("r")}
        ORDER BY r.id
        """,
        params,
    )
    if not rows:
        return None
    errors = [
        f"{QA_BROWSER_GIT_ROOT_REQUIRED}: Cannot transition {name} to "
        f"'{transition_name}' because Browser QA exists but no git root is "
        "available for artifact and freshness checks.",
        "  Recovery: run the transition from the project's git checkout so "
        "`git rev-parse --show-toplevel` succeeds, then rerun Browser QA.",
    ]
    errors.extend(
        f"  - Requirement #{row['id']} ({row['method_id']}): Browser method "
        "requires a git-root-bound check"
        for row in rows
    )
    return GateResult(passed=False, errors=errors)


def target_gate_precondition_result(
    db_path: str,
    *,
    target: GateTarget,
    transition_name: str,
    qa_phase: Optional[str],
    repo_root: Optional[str] = None,
    check_browser_git_root: bool = False,
) -> Optional[GateResult]:
    """Apply schema, requirement-set, and optional Browser-root checks."""
    gate_result = qa_gate_precondition_result(db_path)
    if gate_result is not None:
        return gate_result
    where, params = target.where_clause()
    name = target.display_name()
    conn = connect(db_path)
    try:
        gate_result = requirement_set_result(
            conn,
            target=target,
            where=where,
            params=params,
            name=name,
            transition_name=transition_name,
            qa_phase=qa_phase,
        )
        if gate_result is not None or not check_browser_git_root:
            return gate_result
        return browser_git_root_result(
            conn,
            where=where,
            params=params,
            name=name,
            transition_name=transition_name,
            repo_root=repo_root,
            qa_phase=qa_phase,
        )
    finally:
        conn.close()


__all__ = [
    "QA_BROWSER_GIT_ROOT_REQUIRED",
    "QA_BYPASS_ENV",
    "QA_BYPASS_FORBIDDEN",
    "QA_CORE_TABLES",
    "QA_LIFECYCLE_GATE_TABLES",
    "QA_SCHEMA_MISSING",
    "browser_git_root_result",
    "qa_bypass_result",
    "qa_gate_precondition_result",
    "qa_schema_result",
    "requirement_set_result",
    "target_gate_precondition_result",
]
