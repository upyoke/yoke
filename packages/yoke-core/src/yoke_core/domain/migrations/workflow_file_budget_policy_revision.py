"""Select the File Budget-aware built-in workflow revisions."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definitions,
    builtin_workflow_version_history,
)
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    select_current_builtin_workflow_versions,
)

MIGRATION_NAME = "workflow_file_budget_policy_revision"


def _expected_definition_pairs(fixtures: list[dict]) -> dict[str, set[tuple[str, str]]]:
    expected: dict[str, set[tuple[str, str]]] = {}
    for fixture in fixtures:
        workflow_id = str(fixture["workflow"]["id"])
        definition = fixture["definition"]
        expected.setdefault(workflow_id, set()).add((
            canonical_definition_json(definition),
            definition_digest(definition),
        ))
    return expected


def _selected_definition_pairs(conn: Any) -> dict[str, tuple[str, str]]:
    rows = conn.execute(
        "SELECT w.id, v.definition_json, v.definition_digest "
        "FROM workflows w JOIN workflow_versions v "
        "ON v.id = w.current_version_id WHERE w.source = 'built_in'"
    ).fetchall()
    return {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in rows
    }


def _item_pins(conn: Any) -> tuple[tuple[int, str, int], ...]:
    return tuple(
        (int(row[0]), str(row[1]), int(row[2]))
        for row in conn.execute(
            "SELECT id, workflow_id, workflow_version_id "
            "FROM items ORDER BY id"
        ).fetchall()
    )


def _assert_known_currents(conn: Any) -> None:
    expected = _expected_definition_pairs(
        builtin_workflow_version_history() + builtin_workflow_definitions()
    )
    selected = _selected_definition_pairs(conn)
    if set(selected) != set(expected):
        raise AssertionError("built-in workflow roster is incomplete")
    unknown = [
        workflow_id
        for workflow_id, pair in selected.items()
        if pair not in expected[workflow_id]
    ]
    if unknown:
        raise AssertionError(
            "built-in workflow current is not an exact code-owned definition: "
            + ", ".join(sorted(unknown))
        )


def _assert_current_revisions(conn: Any) -> None:
    expected = _expected_definition_pairs(builtin_workflow_definitions())
    selected = _selected_definition_pairs(conn)
    if (
        set(selected) != set(expected)
        or any(pair not in expected[key] for key, pair in selected.items())
    ):
        raise AssertionError(
            "built-in workflows do not select File Budget-aware revisions"
        )


def apply(conn: Any) -> None:
    """Select exact code-owned v3 definitions without repinning any item."""
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError("workflow policy revision requires PostgreSQL")
    before = _item_pins(conn)
    _assert_known_currents(conn)
    converge_builtin_workflows(conn)
    select_current_builtin_workflow_versions(conn)
    if _item_pins(conn) != before:
        raise AssertionError("existing item workflow pins changed")
    _assert_current_revisions(conn)


def invariants(conn: Any) -> None:
    """Verify current definitions and immutable item pins remain coherent."""
    _assert_current_revisions(conn)
    invalid = conn.execute(
        "SELECT i.id FROM items i "
        "LEFT JOIN workflow_versions v ON v.id = i.workflow_version_id "
        "WHERE v.id IS NULL OR v.workflow_id <> i.workflow_id LIMIT 1"
    ).fetchone()
    if invalid is not None:
        raise AssertionError("an item has an invalid immutable workflow pin")


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
