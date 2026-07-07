"""Composition and batch-compatibility validation for deployment runs.

Owns: ``cmd_validate_composition`` (post-creation enrolment check) and
``cmd_check_batch_compatibility`` (pre-creation batch check). Both enforce
project alignment, deployment-flow alignment, item-status floor, and
unsatisfied hard-block dependency detection. SQL bodies preserved verbatim
from the pre-split state-machine — no reordering, no early-return refactor.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.project_identity import resolve_project, resolve_project_slug
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns


def _hard_block_gate_filter(conn, alias: str = "dep") -> str:
    """Return SQL that excludes compatibility-only dependency rows."""
    cols = set(_schema_get_columns(conn, "item_dependencies"))
    if "gate_point" not in cols:
        return ""
    return (
        f"AND COALESCE({alias}.gate_point, 'activation') <> "
        "'coordination_only' "
    )


def cmd_validate_composition(run_id: str, db_path: Optional[str] = None) -> Tuple[bool, str]:
    """Validate run composition. Returns (ok, message).

    Checks:
    1. All items share the run's project
    2. Items have compatible flow
    3. All items at implemented status or later
    4. No unsatisfied hard-block dependencies outside the run
    """
    conn = connect(db_path)
    try:
        run_project_id = query_scalar(
            conn, "SELECT project_id FROM deployment_runs WHERE id=%s", (run_id,)
        )
        if run_project_id is None:
            return False, f"FAIL: Run '{run_id}' not found"
        run_project_id = int(run_project_id)
        run_project = resolve_project_slug(conn, run_project_id)

        run_flow = query_scalar(
            conn, "SELECT flow FROM deployment_runs WHERE id=%s", (run_id,)
        )

        errors: List[str] = []

        # Check 1: All items share the run's project
        wrong_project = query_rows(
            conn,
            "SELECT 'YOK-' || i.id || ' (project=' || p.slug || ')' "
            "FROM deployment_run_items dri "
            "JOIN items i ON dri.item_id = i.id "
            "JOIN projects p ON p.id = i.project_id "
            "WHERE dri.run_id=%s AND i.project_id <> %s",
            (run_id, run_project_id),
        )
        if wrong_project:
            items_str = ", ".join(str(r[0]) for r in wrong_project)
            errors.append(f"Project mismatch (run expects {run_project}): {items_str}")

        # Check 2: Items have compatible flow
        wrong_flow = query_rows(
            conn,
            "SELECT 'YOK-' || i.id || ' (flow=' || i.deployment_flow || ')' "
            "FROM deployment_run_items dri "
            "JOIN items i ON dri.item_id = i.id "
            "WHERE dri.run_id=%s "
            "AND i.deployment_flow IS NOT NULL "
            "AND i.deployment_flow <> '' "
            "AND i.deployment_flow <> %s",
            (run_id, run_flow),
        )
        if wrong_flow:
            items_str = ", ".join(str(r[0]) for r in wrong_flow)
            errors.append(f"Incompatible deployment flow (run expects {run_flow}): {items_str}")

        # Check 3: All items at implemented status or later
        not_passed = query_rows(
            conn,
            "SELECT 'YOK-' || i.id || ' (status=' || i.status || ')' "
            "FROM deployment_run_items dri "
            "JOIN items i ON dri.item_id = i.id "
            "WHERE dri.run_id=%s AND i.status NOT IN ('implemented', 'release', 'done')",
            (run_id,),
        )
        if not_passed:
            items_str = ", ".join(str(r[0]) for r in not_passed)
            errors.append(f"Items not at implemented status or later: {items_str}")

        # Check 4: Unsatisfied hard-block dependencies
        hard_block_filter = _hard_block_gate_filter(conn)
        blocked = query_rows(
            conn,
            "SELECT 'YOK-' || CAST(REPLACE(dep.dependent_item, 'YOK-', '') AS INTEGER) "
            "|| ' (blocked by ' || dep.blocking_item || ')' "
            "FROM item_dependencies dep "
            "JOIN deployment_run_items dri "
            "  ON dri.item_id = CAST(REPLACE(dep.dependent_item, 'YOK-', '') AS INTEGER) "
            "WHERE dri.run_id=%s "
            f"  {hard_block_filter}"
            "  AND NOT EXISTS ( "
            "    SELECT 1 FROM deployment_run_items dri2 "
            "    WHERE dri2.run_id=%s "
            "      AND dri2.item_id = CAST(REPLACE(dep.blocking_item, 'YOK-', '') AS INTEGER) "
            "  ) "
            "  AND NOT EXISTS ( "
            "    SELECT 1 FROM items blocker "
            "    WHERE blocker.id = CAST(REPLACE(dep.blocking_item, 'YOK-', '') AS INTEGER) "
            "      AND ( "
            "        (dep.satisfaction = 'status:done' AND blocker.status = 'done') "
            "        OR (dep.satisfaction = 'status:implemented' AND blocker.status IN ('implemented', 'release', 'done')) "
            "        OR (dep.satisfaction = 'fact:merged' AND ( "
            "          COALESCE(blocker.merged_at, '') <> '' "
            "          OR blocker.status IN ('release', 'done') "
            "        )) "
            "      ) "
            "  )",
            (run_id, run_id),
        )
        if blocked:
            items_str = ", ".join(str(r[0]) for r in blocked)
            errors.append(f"Unsatisfied hard-block dependencies: {items_str}")

        if errors:
            error_text = "\n".join(errors)
            return False, f"FAIL: Composition validation failed:\n{error_text}"

        return True, "OK"
    finally:
        conn.close()


def cmd_check_batch_compatibility(
    project: str,
    flow: str,
    item_ids: Sequence[int],
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Validate proposed items before run creation. Returns (ok, message).

    Same checks as validate-composition but against a proposed batch of items.
    """
    if not item_ids:
        return False, "FAIL: No item IDs provided"

    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project)
        assert ident is not None
        # Build placeholders for IN clause
        placeholders = ",".join("%s" for _ in item_ids)
        errors: List[str] = []

        # Check 1: All items share the target project
        wrong_project = query_rows(
            conn,
            f"SELECT 'YOK-' || i.id || ' (project=' || p.slug || ')' "
            f"FROM items i "
            f"JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id IN ({placeholders}) AND i.project_id <> %s",
            tuple(item_ids) + (ident.id,),
        )
        if wrong_project:
            items_str = ", ".join(str(r[0]) for r in wrong_project)
            errors.append(f"Project mismatch (batch expects {ident.slug}): {items_str}")

        # Check 2: All items have compatible flow
        wrong_flow = query_rows(
            conn,
            f"SELECT 'YOK-' || i.id || ' (flow=' || i.deployment_flow || ')' "
            f"FROM items i "
            f"WHERE i.id IN ({placeholders}) "
            f"AND i.deployment_flow IS NOT NULL "
            f"AND i.deployment_flow <> '' "
            f"AND i.deployment_flow <> %s",
            tuple(item_ids) + (flow,),
        )
        if wrong_flow:
            items_str = ", ".join(str(r[0]) for r in wrong_flow)
            errors.append(f"Incompatible deployment flow (batch expects {flow}): {items_str}")

        # Check 3: All items at implemented or later
        not_passed = query_rows(
            conn,
            f"SELECT 'YOK-' || i.id || ' (status=' || i.status || ')' "
            f"FROM items i "
            f"WHERE i.id IN ({placeholders}) AND i.status NOT IN ('implemented', 'release', 'done')",
            tuple(item_ids),
        )
        if not_passed:
            items_str = ", ".join(str(r[0]) for r in not_passed)
            errors.append(f"Items not at implemented status or later: {items_str}")

        # Check 4: Unsatisfied hard-block deps outside batch
        hard_block_filter = _hard_block_gate_filter(conn)
        blocked = query_rows(
            conn,
            f"SELECT 'YOK-' || CAST(REPLACE(dep.dependent_item, 'YOK-', '') AS INTEGER) "
            f"|| ' (blocked by ' || dep.blocking_item || ')' "
            f"FROM item_dependencies dep "
            f"WHERE CAST(REPLACE(dep.dependent_item, 'YOK-', '') AS INTEGER) IN ({placeholders}) "
            f"  {hard_block_filter}"
            f"  AND CAST(REPLACE(dep.blocking_item, 'YOK-', '') AS INTEGER) NOT IN ({placeholders}) "
            f"  AND NOT EXISTS ( "
            f"    SELECT 1 FROM items blocker "
            f"    WHERE blocker.id = CAST(REPLACE(dep.blocking_item, 'YOK-', '') AS INTEGER) "
            f"      AND ( "
            f"        (dep.satisfaction = 'status:done' AND blocker.status = 'done') "
            f"        OR (dep.satisfaction = 'status:implemented' AND blocker.status IN ('implemented', 'release', 'done')) "
            f"        OR (dep.satisfaction = 'fact:merged' AND ( "
            f"          COALESCE(blocker.merged_at, '') <> '' "
            f"          OR blocker.status IN ('release', 'done') "
            f"        )) "
            f"      ) "
            f"  )",
            tuple(item_ids) + tuple(item_ids),
        )
        if blocked:
            items_str = ", ".join(str(r[0]) for r in blocked)
            errors.append(f"Unsatisfied hard-block dependencies: {items_str}")

        if errors:
            error_text = "\n".join(errors)
            return False, f"FAIL: Batch compatibility check failed:\n{error_text}"

        return True, "OK"
    finally:
        conn.close()
