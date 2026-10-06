"""Retire the ``advance`` workflow skill in favor of ``implement``.

The ``implement`` stage skill replaces ``advance`` as the skill a workflow
binds across issue implementation. There is no alias: ``advance`` is no longer
a registered workflow skill, a scheduler step, or a lane action. Two kinds of
stored state could still name it.

**Items pinned to a definition that binds ``advance``.** A pinned definition is
immutable history, so such an item would route to a skill that no longer
exists. Nothing re-pins it here. The entry refuses instead, naming every such
item and its recovery, so the universe stays on the build it is running until
an operator finishes or cancels those items there.

**Lane allowlists in ``session-routing`` capability documents.** These name
routable actions by skill id, so ``advance`` becomes ``implement`` in every
allowlist that names it. Once rewritten, a build that predates ``implement``
cannot route those lanes, hence the serving floor.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE

RETIRED_SKILL_ID = "advance"
REPLACEMENT_SKILL_ID = "implement"
#: Engine-owned terminal stages every definition shares in addition to its own.
_ENGINE_TERMINAL_STAGE_IDS = frozenset({"cancelled", "stopped"})
_LANE_PATHS_KEY = "lane_paths"
_LANE_PATHS_PREFIX = "lane_paths_"


def _marker(conn: Any) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


#: Binding containers and their skill key across stored definition schemas;
#: older generations named the bound skill an executor.
_BINDING_SHAPES = (("skill_bindings", "skill_id"), ("executor_bindings", "executor_id"))


def _binds_retired_skill(definition: Any) -> bool:
    if not isinstance(definition, dict):
        return False
    return any(
        isinstance(binding, dict) and binding.get(key) == RETIRED_SKILL_ID
        for container, key in _BINDING_SHAPES
        for binding in definition.get(container) or ()
    )


def _terminal_stage_ids(definition: dict) -> frozenset[str]:
    declared = definition.get("terminal_stage_ids") or ()
    return frozenset(str(stage) for stage in declared) | _ENGINE_TERMINAL_STAGE_IDS


def _item_label(row: Any) -> str:
    prefix, sequence, item_id = row[3], row[4], row[0]
    if prefix and sequence is not None:
        return f"{prefix}-{sequence}"
    return f"item {item_id}"


def _pinned_items(conn: Any) -> list[str]:
    """Non-terminal items whose pinned definition binds the retired skill."""
    if not (
        _table_exists(conn, "items")
        and _table_exists(conn, "workflow_versions")
        and _column_exists(conn, "items", "workflow_version_id")
    ):
        return []
    has_prefix = _table_exists(conn, "projects") and _column_exists(
        conn, "projects", "public_item_prefix"
    )
    has_sequence = _column_exists(conn, "items", "project_sequence")
    prefix = "p.public_item_prefix" if has_prefix else "NULL"
    sequence = "i.project_sequence" if has_sequence else "NULL"
    join = "LEFT JOIN projects p ON p.id = i.project_id " if has_prefix else ""
    rows = conn.execute(
        f"SELECT i.id, i.status, wv.definition_json, {prefix}, {sequence}, "
        "wv.workflow_id, wv.version FROM items i "
        "JOIN workflow_versions wv ON wv.id = i.workflow_version_id "
        f"{join}ORDER BY i.id"
    ).fetchall()
    pinned = []
    for row in rows:
        definition = json.loads(str(row[2] or "{}"))
        if not _binds_retired_skill(definition):
            continue
        if str(row[1]) in _terminal_stage_ids(definition):
            continue
        pinned.append(f"{_item_label(row)} ({row[5]}@{row[6]}, {row[1]})")
    return pinned


def _refuse_pinned_items(conn: Any) -> None:
    pinned = _pinned_items(conn)
    if pinned:
        raise RuntimeError(
            "retired_advance_skill_pinned: these non-terminal items are pinned "
            "to a workflow definition that binds the retired `advance` skill: "
            + "; ".join(pinned)
            + ". This build has no `advance` skill and does not re-pin items. "
            "Recovery: on the build this universe is running now, finish each "
            "item to its terminal stage or cancel it (`yoke items cancel "
            "ITEM --reason TEXT`), then retry the "
            "release or boot."
        )


def _renamed_actions(actions: Any) -> Any:
    if isinstance(actions, str):
        parts = [part.strip() for part in actions.split(",") if part.strip()]
        return ",".join(_renamed_actions(parts))
    if not isinstance(actions, list):
        return actions
    renamed: list[Any] = []
    for action in actions:
        value = REPLACEMENT_SKILL_ID if action == RETIRED_SKILL_ID else action
        if value not in renamed:
            renamed.append(value)
    return renamed


def _converged_routing(settings: dict) -> dict:
    converged = dict(settings)
    grouped = converged.get(_LANE_PATHS_KEY)
    if isinstance(grouped, dict):
        converged[_LANE_PATHS_KEY] = {
            lane: _renamed_actions(actions) for lane, actions in grouped.items()
        }
    for key, value in settings.items():
        if key.startswith(_LANE_PATHS_PREFIX):
            converged[key] = _renamed_actions(value)
    return converged


def _routing_rows(conn: Any) -> list[Any]:
    if not _table_exists(conn, "project_capabilities"):
        return []
    return conn.execute(
        "SELECT id, settings FROM project_capabilities "
        f"WHERE type = {_marker(conn)} ORDER BY id",
        ("session-routing",),
    ).fetchall()


def _names_retired_action(settings: dict) -> bool:
    return _converged_routing(settings) != settings


def apply(conn: Any) -> None:
    _refuse_pinned_items(conn)
    marker = _marker(conn)
    updates = []
    for row in _routing_rows(conn):
        settings = json.loads(str(row[1] or "{}"))
        if isinstance(settings, dict) and _names_retired_action(settings):
            encoded = json.dumps(
                _converged_routing(settings), separators=(",", ":"), sort_keys=True
            )
            updates.append((encoded, int(row[0])))
    for settings, row_id in updates:
        conn.execute(
            f"UPDATE project_capabilities SET settings = {marker} WHERE id = {marker}",
            (settings, row_id),
        )


def invariants(conn: Any) -> None:
    _refuse_pinned_items(conn)
    for row in _routing_rows(conn):
        settings = json.loads(str(row[1] or "{}"))
        if isinstance(settings, dict) and _names_retired_action(settings):
            raise AssertionError(
                "retired_advance_lane_action_remains: session-routing "
                f"capability {row[0]} still names `advance`; rehearse the "
                "retire-advance migration"
            )
