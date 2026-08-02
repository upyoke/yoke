"""Low-level File Budget/path-claim parity comparison."""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.domain import db_backend
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
        issues.append(issue_type(
            code="FILE_BUDGET_NOT_IN_CLAIM",
            message=(
                f"File Budget names {path} but the path-claim does not declare it"
            ),
            remediation=(
                f"widen the claim to include {path} (or remove from File Budget "
                "if the file is context, not an edit target)"
            ),
            context={"path": path},
        ))
    for path in sorted(claims - budget):
        issues.append(issue_type(
            code="CLAIM_NOT_IN_FILE_BUDGET",
            message=(
                f"path-claim declares {path} but the File Budget does not name it"
            ),
            remediation=(
                f"add {path} to the File Budget (or narrow the claim if the "
                "file is no longer touched)"
            ),
            context={"path": path},
        ))
    return issues


__all__ = ["verify_claim_consistency"]
