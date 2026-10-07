"""Re-pin open items off published definitions that bind ``advance``.

``0053_retire_advance_skill`` refuses while any non-terminal item is pinned to
a definition binding the retired ``advance`` skill, and its recovery -- finish
or cancel those items on the build the universe is running -- is impossible
for a universe that runs current source and so cannot boot until that entry
passes. This entry therefore runs before it (``PRECEDES``) and removes the
refusal's cause wherever the answer is not a judgment call.

An item pinned to a generation Yoke published -- recognized by digest against
the built-in canon, whatever version number the universe stored it under -- is
re-pinned to the published generation that replaced it: ``issue`` generations
1-7 move to generation 8, and ``task`` generation 1 moves to generation 2.
Each pair has identical stages and terminal stages and differs only in binding
``implement`` (or, for ``task``, ``dash``) where it bound ``advance``, so the
item's status stays valid. A replacement the universe does not hold yet is
inserted, since built-in convergence runs after the history.

An item pinned to a definition the canon does not recognize is a local
customization, so no replacement is correct automatically. Apply then refuses,
naming each such item and a recovery an operator can perform, and the whole
apply rolls back.

Correct in either order relative to 0053: a universe that already applied 0053
holds no such items, so this entry is a no-op there.
"""

from __future__ import annotations

import importlib
import json
from typing import Any, Mapping

from yoke_core.domain.builtin_workflow_canon import canon_generations, recognize
from yoke_core.domain.builtin_workflow_version_convergence import (
    _ensure_current_version,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_definition_codec import definition_digest
from yoke_core.domain.workflow_registry import _insert_version

MINIMUM_SERVING_VERSION = NEXT_RELEASE
PRECEDES = ("0053_retire_advance_skill",)

#: Published generations that bind ``advance``, keyed by workflow, mapped to the
#: published generation that replaced them. Literal on purpose: this entry is
#: permanent history and must not follow later canon generations.
REPLACEMENT_GENERATIONS: Mapping[str, tuple[frozenset[int], int]] = {
    "issue": (frozenset(range(1, 8)), 8),
    "task": (frozenset({1}), 2),
}

_RETIRE_ADVANCE = importlib.import_module(
    "yoke_core.domain.migrations.0053_retire_advance_skill"
)


def _marker(conn: Any) -> str:
    return _RETIRE_ADVANCE._marker(conn)


def _replacement_generation(workflow_id: str, definition: Any) -> Any:
    """The canon generation replacing *definition*, or None if not published."""
    mapping = REPLACEMENT_GENERATIONS.get(workflow_id)
    if mapping is None or not isinstance(definition, dict):
        return None
    sources, target_version = mapping
    recognized = recognize(workflow_id, definition_digest(definition))
    if recognized is None or recognized.canon_version not in sources:
        return None
    for generation in canon_generations(workflow_id):
        if generation.canon_version == target_version:
            return generation
    raise RuntimeError(
        f"repin_advance_canon_missing: canon generation "
        f"{workflow_id}.{target_version:02d} is absent from this build's "
        "built-in canon; the canon is append-only, so restore the missing "
        "builtin_workflow_canon JSON file"
    )


def _open_advance_pins(conn: Any) -> list[tuple[int, str, dict]]:
    """(item id, workflow id, definition) for every live advance-bound pin."""
    if not (
        _table_exists(conn, "items")
        and _table_exists(conn, "workflow_versions")
        and _column_exists(conn, "items", "workflow_version_id")
    ):
        return []
    rows = conn.execute(
        "SELECT i.id, i.status, wv.workflow_id, wv.definition_json FROM items i "
        "JOIN workflow_versions wv ON wv.id = i.workflow_version_id ORDER BY i.id"
    ).fetchall()
    pins = []
    for item_id, status, workflow_id, definition_json in rows:
        definition = json.loads(str(definition_json or "{}"))
        if not _RETIRE_ADVANCE._binds_retired_skill(definition):
            continue
        if str(status) in _RETIRE_ADVANCE._terminal_stage_ids(definition):
            continue
        pins.append((int(item_id), str(workflow_id), definition))
    return pins


def _refuse_unrecognized_pins(conn: Any) -> None:
    remaining = _RETIRE_ADVANCE._pinned_items(conn)
    if remaining:
        raise RuntimeError(
            "repin_advance_customized_definition: these non-terminal items are "
            "pinned to a workflow definition that binds the retired `advance` "
            "skill and that Yoke did not publish, so no replacement is chosen "
            "for them: "
            + "; ".join(remaining)
            + ". Nothing was changed. Recovery: on a Yoke build older than "
            "this one (one that still serves this universe), publish a version "
            "of that workflow binding `implement` instead of `advance` and move "
            "each item onto it with `yoke workflows item migrate ITEM --version "
            "N`, or cancel the item with `yoke items cancel ITEM --reason "
            "TEXT`; then upgrade again."
        )


def apply(conn: Any) -> None:
    marker = _marker(conn)
    for item_id, workflow_id, definition in _open_advance_pins(conn):
        generation = _replacement_generation(workflow_id, definition)
        if generation is None:
            continue
        target = _ensure_current_version(
            conn,
            {"workflow": {"id": workflow_id}, "definition": generation.definition},
            _insert_version,
        )
        conn.execute(
            f"UPDATE items SET workflow_version_id = {marker} WHERE id = {marker}",
            (int(target["id"]), item_id),
        )
    _refuse_unrecognized_pins(conn)


def invariants(conn: Any) -> None:
    _refuse_unrecognized_pins(conn)
