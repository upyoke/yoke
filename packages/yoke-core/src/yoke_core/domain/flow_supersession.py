"""Safe convergence of code-owned deployment-flow successors."""

from __future__ import annotations

from collections.abc import Mapping
import json

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_flow_seed_data import (
    BUILTIN_FLOW_SUPERSESSIONS,
    SEED_FLOWS,
)
from yoke_core.domain.lifecycle_enums import ItemStatus
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES
from yoke_core.domain.schema_common import _column_exists, _table_exists


_FLOW_DEFINITION_FIELDS = (
    "name",
    "description",
    "stages",
    "on_failure",
    "target_env",
    "done_description",
)
_TERMINAL_ITEM_BINDING_STATUSES = frozenset({
    ItemStatus.DONE.value,
    ItemStatus.CANCELLED.value,
    ItemStatus.FAILED.value,
    ItemStatus.STOPPED.value,
})


def _flow_definition_row(conn, flow_id: str):
    return conn.execute(
        "SELECT project_id, name, description, stages, on_failure, "
        "target_env, done_description, status "
        "FROM deployment_flows WHERE id=%s",
        (flow_id,),
    ).fetchone()


def _normalized_stages(raw: object) -> object:
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return raw


def _row_matches_definition(row, definition: Mapping[str, object]) -> bool:
    if row is None:
        return False
    actual = dict(zip(_FLOW_DEFINITION_FIELDS, tuple(row)[1:7]))
    for field in _FLOW_DEFINITION_FIELDS:
        actual_value = actual[field]
        expected_value = definition.get(field)
        if field == "stages":
            actual_value = _normalized_stages(actual_value)
            expected_value = _normalized_stages(expected_value)
        if actual_value != expected_value:
            return False
    return True


def _row_is_active(row) -> bool:
    return row is not None and str(tuple(row)[-1]) == "active"


def _has_nonterminal_binding(conn, flow_id: str) -> bool:
    if _table_exists(conn, "items") and _column_exists(
        conn, "items", "deployment_flow"
    ):
        item_terminals = sorted(_TERMINAL_ITEM_BINDING_STATUSES)
        placeholders = ", ".join("%s" for _ in item_terminals)
        row = conn.execute(
            "SELECT 1 FROM items WHERE deployment_flow=%s "
            f"AND (status IS NULL OR status NOT IN ({placeholders})) LIMIT 1",
            (flow_id, *item_terminals),
        ).fetchone()
        if row is not None:
            return True
    if _table_exists(conn, "deployment_runs"):
        run_terminals = sorted(TERMINAL_RUN_STATUSES)
        placeholders = ", ".join("%s" for _ in run_terminals)
        row = conn.execute(
            "SELECT 1 FROM deployment_runs WHERE flow=%s "
            f"AND (status IS NULL OR status NOT IN ({placeholders})) LIMIT 1",
            (flow_id, *run_terminals),
        ).fetchone()
        if row is not None:
            return True
    return False


def _repoint_builtin_deploy_default(
    conn, project_id: int, predecessor_id: str, successor_id: str
) -> None:
    if not _table_exists(conn, "project_structure"):
        return
    rows = conn.execute(
        "SELECT id, payload FROM project_structure "
        "WHERE project_id=%s AND family='deploy_defaults'",
        (project_id,),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row[1]))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("deployment_flow") != predecessor_id:
            continue
        updated = dict(payload)
        updated["deployment_flow"] = successor_id
        if _column_exists(conn, "project_structure", "updated_at"):
            conn.execute(
                "UPDATE project_structure SET payload=%s, updated_at=%s "
                "WHERE id=%s",
                (json.dumps(updated, separators=(",", ":")), iso8601_now(), row[0]),
            )
        else:
            conn.execute(
                "UPDATE project_structure SET payload=%s WHERE id=%s",
                (json.dumps(updated, separators=(",", ":")), row[0]),
            )


def converge_builtin_flow_supersessions(conn) -> None:
    """Activate exact code-owned successors without rewriting history."""
    seed_by_id = {str(flow["id"]): flow for flow in SEED_FLOWS}
    for supersession in BUILTIN_FLOW_SUPERSESSIONS:
        predecessor_id = str(supersession["predecessor_id"])
        successor_id = str(supersession["successor_id"])
        successor = seed_by_id.get(successor_id)
        if successor is None:
            continue
        predecessor_row = _flow_definition_row(conn, predecessor_id)
        successor_row = _flow_definition_row(conn, successor_id)
        if predecessor_row is None or successor_row is None:
            continue
        project_id = int(tuple(predecessor_row)[0])
        if project_id != int(tuple(successor_row)[0]):
            continue
        if not _row_is_active(successor_row):
            continue
        if not _row_matches_definition(successor_row, successor):
            continue
        recognized = supersession.get("recognized_definitions") or ()
        if not any(
            _row_matches_definition(predecessor_row, definition)
            for definition in recognized
            if isinstance(definition, Mapping)
        ):
            continue
        _repoint_builtin_deploy_default(
            conn, project_id, predecessor_id, successor_id
        )
        if not _has_nonterminal_binding(conn, predecessor_id):
            conn.execute(
                "UPDATE deployment_flows SET status=%s WHERE id=%s",
                ("disabled", predecessor_id),
            )


__all__ = ["converge_builtin_flow_supersessions"]
