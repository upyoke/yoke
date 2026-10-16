"""Low-level File Budget/path-claim parity comparison."""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.domain import db_backend
from yoke_core.domain.idea_readiness_results import Issue
from yoke_core.domain.idea_readiness_local_inputs import read_spec
from yoke_core.domain.file_budget_paths import extract_file_budget_paths_set


def _claim_declared_paths(conn: Any, item_id: int) -> set[str]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        rows = conn.execute(
            "SELECT pt.path_string FROM path_claim_targets pct "
            "JOIN path_claims pc ON pc.id = pct.claim_id "
            "JOIN path_targets pt ON pt.id = pct.target_id "
            f"WHERE pc.owner_kind = 'item' AND pc.owner_item_id = {marker} "
            "AND pc.state IN "
            "('planned', 'blocked', 'active') AND pt.kind = 'file'",
            (item_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return set()
    return {str(row[0]) for row in rows}


def verify_claim_consistency(
    conn: Any,
    item_id: int,
    *,
    spec_text: str,
    issue_type: Callable[..., Any],
) -> list[Any]:
    """Compare declared paths without applying workflow policy opt-outs."""
    if not spec_text:
        return []
    budget = extract_file_budget_paths_set(spec_text)
    claims = _claim_declared_paths(conn, item_id)
    issues = []
    for path in sorted(budget - claims):
        issues.append(
            issue_type(
                code="FILE_BUDGET_NOT_IN_CLAIM",
                message=(
                    f"File Budget names {path} but the path-claim does not declare it"
                ),
                remediation=(
                    f"widen the claim to include {path} (or remove from File Budget "
                    "if the file is context, not an edit target)"
                ),
                context={"path": path},
            )
        )
    for path in sorted(claims - budget):
        issues.append(
            issue_type(
                code="CLAIM_NOT_IN_FILE_BUDGET",
                message=(
                    f"path-claim declares {path} but the File Budget does not name it"
                ),
                remediation=(
                    f"add {path} to the File Budget (or narrow the claim if the "
                    "file is no longer touched)"
                ),
                context={"path": path},
            )
        )
    return issues


def verify_task_claim_consistency(
    conn: Any,
    item_id: int,
    *,
    issue_type: Callable[..., Any],
) -> list[Any]:
    """Use the gates' shared task coverage, deferring until tasks exist."""
    from yoke_core.domain.path_claim_task_coverage import evaluate_task_coverage

    coverage = evaluate_task_coverage(conn, item_id)
    return [
        issue_type(
            code="FILE_BUDGET_NOT_IN_CLAIM",
            message=f"task File Budget names {path} without bound claim coverage",
            remediation=(
                "register or widen the owning task's claim to include "
                f"{path} with yoke claims path register --item "
                "<item-ref> --task-num <task-num> --paths <task-budget-paths> "
                "[--allow-planned]; rerun readiness"
            ),
            context={"path": path},
        )
        for path in coverage.uncovered_paths
    ]


def verify_file_budget_claim_consistency(
    conn: Any,
    item_id: int,
) -> list[Issue]:
    """Confirm File Budget paths and path-claim targets agree."""
    return verify_claim_consistency(
        conn,
        item_id,
        spec_text=read_spec(conn, item_id),
        issue_type=Issue,
    )


def verify_effective_file_budget_claim_consistency(
    conn: Any,
    item_id: int,
) -> list[Issue]:
    """Apply parity only when both effective workflow axes require it."""
    from yoke_core.domain.workflow_effective_policies import (
        load_item_effective_workflow_policies,
    )

    effective = load_item_effective_workflow_policies(conn, item_id)
    if not effective.requires_budget_claim_parity:
        return []
    if effective.path_claims == "required_per_task":
        return verify_task_claim_consistency(conn, item_id, issue_type=Issue)
    return verify_file_budget_claim_consistency(conn, item_id)


__all__ = [
    "verify_claim_consistency",
    "verify_task_claim_consistency",
    "verify_file_budget_claim_consistency",
    "verify_effective_file_budget_claim_consistency",
]
