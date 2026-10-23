"""Name a QA host a test machine inside frozen release QA snapshots.

``0090_qa_test_machine_keys`` folded the live plan cases, requirements, runs
and rosters, but not the ``requirement_snapshot`` a deployment run and each
of its members froze when the run started. Materializing a stage derives a
frozen case through the current method validator, which refuses the retired
``machine`` key, so a same-plan retry on a run frozen before 0090 stopped
with ``agent_mission_executor_invalid``.

This entry applies the same ``method_config`` folds (``machine`` /
``machines`` to ``test_machine`` / ``test_machines``) to every frozen
requirement and plan case, and changes nothing else. A changed snapshot is
stored in the sorted compact form its writers produce, so every other byte
stays as it was. No stored value digests a snapshot; run projection digests
are derived on read. Builds from 0090 on already read only the current keys.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migrations._qa_test_machine_documents import (
    compact,
    fold_method_config,
    parsed,
)
from yoke_core.domain.schema_common import _column_exists

#: Each table holding a frozen snapshot, with its row key columns.
SNAPSHOT_TABLES = (
    ("deployment_runs", ("id",)),
    ("deployment_run_items", ("run_id", "item_id")),
)
COLUMN = "requirement_snapshot"
#: Narrows the scan to snapshots that can hold a retired key.
_RETIRED_KEY_PATTERN = '%"machine%'


def _marker(conn: Any) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


def _fold_entries(entries: Any) -> Any:
    """Fold each entry's ``method_config``; other entries pass unchanged."""
    if not isinstance(entries, list):
        return entries
    return [
        {**entry, "method_config": fold_method_config(entry["method_config"])}
        if isinstance(entry, dict) and "method_config" in entry
        else entry
        for entry in entries
    ]


def _fold_plans(plans: Any) -> Any:
    """Fold the frozen cases of each plan or flow-stage selection."""
    if not isinstance(plans, list):
        return plans
    return [
        {**plan, "cases": _fold_entries(plan["cases"])}
        if isinstance(plan, dict) and "cases" in plan
        else plan
        for plan in plans
    ]


def fold_snapshot(snapshot: Any) -> Any:
    """Fold a member snapshot (``requirements``, ``plans``) or a flow one
    (``selections``)."""
    if not isinstance(snapshot, dict):
        return snapshot
    folded = dict(snapshot)
    if "requirements" in folded:
        folded["requirements"] = _fold_entries(folded["requirements"])
    for field in ("plans", "selections"):
        if field in folded:
            folded[field] = _fold_plans(folded[field])
    return folded


def _changed_rows(conn: Any, table: str, keys: tuple[str, ...]) -> list[tuple]:
    """Each row whose snapshot the fold changes: (encoded, *key values)."""
    if not _column_exists(conn, table, COLUMN):
        return []
    rows = conn.execute(
        f"SELECT {COLUMN}, {', '.join(keys)} FROM {table} "
        f"WHERE {COLUMN} LIKE {_marker(conn)} ORDER BY {', '.join(keys)}",
        (_RETIRED_KEY_PATTERN,),
    ).fetchall()
    changed = []
    for raw, *key_values in rows:
        snapshot = parsed(raw)
        folded = fold_snapshot(snapshot)
        if folded != snapshot:
            changed.append((compact(folded), *key_values))
    return changed


def apply(conn: Any) -> None:
    p = _marker(conn)
    for table, keys in SNAPSHOT_TABLES:
        where = " AND ".join(f"{key}={p}" for key in keys)
        for values in _changed_rows(conn, table, keys):
            conn.execute(f"UPDATE {table} SET {COLUMN}={p} WHERE {where}", values)


def invariants(conn: Any) -> None:
    """Prove no frozen snapshot still names a QA host ``machine``."""
    for table, keys in SNAPSHOT_TABLES:
        remaining = len(_changed_rows(conn, table, keys))
        assert remaining == 0, (
            f"{table}.{COLUMN} still holds {remaining} snapshot(s) with a "
            "retired machine key; rerun this entry's rehearsal"
        )


__all__ = ["COLUMN", "SNAPSHOT_TABLES", "apply", "fold_snapshot", "invariants"]
