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
from yoke_core.domain.item_ref_columns import column_item_id_sql
from yoke_core.domain.project_identity import (
    render_item_ref,
    resolve_project,
    resolve_project_slug,
)
from yoke_core.domain.schema_common import (
    _get_columns as _schema_get_columns,
    _table_exists,
)
from yoke_core.domain.workflow_delivery_binding_validation import (
    delivery_ready_for_stage,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

_LEGACY_DELIVERY_READY_STAGES = frozenset({"implemented", "release", "done"})


def _hard_block_gate_filter(conn, alias: str = "dep") -> str:
    """Return SQL that excludes compatibility-only dependency rows."""
    cols = set(_schema_get_columns(conn, "item_dependencies"))
    if "gate_point" not in cols:
        return ""
    return (
        f"AND COALESCE({alias}.gate_point, 'activation') <> "
        "'coordination_only' "
    )


def _item_label(conn, item_id: int, detail: str) -> str:
    public_ref = render_item_ref(conn, int(item_id), required=True)
    return f"{public_ref} ({detail})"


def _not_delivery_ready(conn, rows) -> list[str]:
    refused: list[str] = []
    item_columns = set(_schema_get_columns(conn, "items"))
    has_workflow_pins = _table_exists(conn, "workflow_versions") and {
        "workflow_id",
        "workflow_version_id",
    } <= item_columns
    for item_id, status in rows:
        if has_workflow_pins:
            runtime = load_item_workflow_runtime(conn, int(item_id))
            ready = delivery_ready_for_stage(runtime, str(status))
        else:
            ready = str(status) in _LEGACY_DELIVERY_READY_STAGES
        if not ready:
            refused.append(_item_label(conn, item_id, f"status={status}"))
    return refused


def cmd_validate_composition(run_id: str, db_path: Optional[str] = None) -> Tuple[bool, str]:
    """Validate run composition. Returns (ok, message).

    Checks:
    1. All items share the run's project
    2. Items have compatible flow
    3. Every item is delivery-ready under its pinned workflow policy
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
            "SELECT i.id, p.slug "
            "FROM deployment_run_items dri "
            "JOIN items i ON dri.item_id = i.id "
            "JOIN projects p ON p.id = i.project_id "
            "WHERE dri.run_id=%s AND i.project_id <> %s",
            (run_id, run_project_id),
        )
        if wrong_project:
            items_str = ", ".join(
                _item_label(conn, row[0], f"project={row[1]}")
                for row in wrong_project
            )
            errors.append(f"Project mismatch (run expects {run_project}): {items_str}")

        # Check 2: Items have compatible flow
        wrong_flow = query_rows(
            conn,
            "SELECT i.id, i.deployment_flow "
            "FROM deployment_run_items dri "
            "JOIN items i ON dri.item_id = i.id "
            "WHERE dri.run_id=%s "
            "AND i.deployment_flow IS NOT NULL "
            "AND i.deployment_flow <> '' "
            "AND i.deployment_flow <> %s",
            (run_id, run_flow),
        )
        if wrong_flow:
            items_str = ", ".join(
                _item_label(conn, row[0], f"flow={row[1]}")
                for row in wrong_flow
            )
            errors.append(f"Incompatible deployment flow (run expects {run_flow}): {items_str}")

        # Check 3: Every item is delivery-ready for its pinned workflow.
        delivery_candidates = query_rows(
            conn,
            "SELECT i.id, i.status "
            "FROM deployment_run_items dri "
            "JOIN items i ON dri.item_id = i.id "
            "WHERE dri.run_id=%s",
            (run_id,),
        )
        not_passed = _not_delivery_ready(conn, delivery_candidates)
        if not_passed:
            errors.append(
                "Items not delivery-ready for their pinned workflow: "
                + ", ".join(not_passed)
            )

        # Check 4: Unsatisfied hard-block dependencies
        hard_block_filter = _hard_block_gate_filter(conn)
        dependent_item_id = column_item_id_sql(conn, "dep.dependent_item")
        blocking_item_id = column_item_id_sql(conn, "dep.blocking_item")
        blocked = query_rows(
            conn,
            "SELECT dep.dependent_item || ' (blocked by ' || dep.blocking_item || ')' "
            "FROM item_dependencies dep "
            "JOIN deployment_run_items dri "
            f"  ON dri.item_id = {dependent_item_id} "
            "WHERE dri.run_id=%s "
            f"  {hard_block_filter}"
            "  AND NOT EXISTS ( "
            "    SELECT 1 FROM deployment_run_items dri2 "
            "    WHERE dri2.run_id=%s "
            f"      AND dri2.item_id = {blocking_item_id} "
            "  ) "
            "  AND NOT EXISTS ( "
            "    SELECT 1 FROM items blocker "
            f"    WHERE blocker.id = {blocking_item_id} "
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
            f"SELECT i.id, p.slug "
            f"FROM items i "
            f"JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id IN ({placeholders}) AND i.project_id <> %s",
            tuple(item_ids) + (ident.id,),
        )
        if wrong_project:
            items_str = ", ".join(
                _item_label(conn, row[0], f"project={row[1]}")
                for row in wrong_project
            )
            errors.append(f"Project mismatch (batch expects {ident.slug}): {items_str}")

        # Check 2: All items have compatible flow
        wrong_flow = query_rows(
            conn,
            f"SELECT i.id, i.deployment_flow "
            f"FROM items i "
            f"WHERE i.id IN ({placeholders}) "
            f"AND i.deployment_flow IS NOT NULL "
            f"AND i.deployment_flow <> '' "
            f"AND i.deployment_flow <> %s",
            tuple(item_ids) + (flow,),
        )
        if wrong_flow:
            items_str = ", ".join(
                _item_label(conn, row[0], f"flow={row[1]}")
                for row in wrong_flow
            )
            errors.append(f"Incompatible deployment flow (batch expects {flow}): {items_str}")

        # Check 3: Every item is delivery-ready for its pinned workflow.
        delivery_candidates = query_rows(
            conn,
            f"SELECT i.id, i.status "
            f"FROM items i "
            f"WHERE i.id IN ({placeholders})",
            tuple(item_ids),
        )
        not_passed = _not_delivery_ready(conn, delivery_candidates)
        if not_passed:
            errors.append(
                "Items not delivery-ready for their pinned workflow: "
                + ", ".join(not_passed)
            )

        # Check 4: Unsatisfied hard-block deps outside batch
        hard_block_filter = _hard_block_gate_filter(conn)
        dependent_item_id = column_item_id_sql(conn, "dep.dependent_item")
        blocking_item_id = column_item_id_sql(conn, "dep.blocking_item")
        blocked = query_rows(
            conn,
            f"SELECT dep.dependent_item || ' (blocked by ' || dep.blocking_item || ')' "
            f"FROM item_dependencies dep "
            f"WHERE {dependent_item_id} IN ({placeholders}) "
            f"  {hard_block_filter}"
            f"  AND {blocking_item_id} NOT IN ({placeholders}) "
            f"  AND NOT EXISTS ( "
            f"    SELECT 1 FROM items blocker "
            f"    WHERE blocker.id = {blocking_item_id} "
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
