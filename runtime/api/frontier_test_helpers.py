"""Shared DB builders and item/dep inserters for ``test_frontier_*``.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports the builders/inserters it needs and uses them directly — no
``@pytest.fixture`` wrapping is required since these helpers return disposable
Postgres test connections that close/drop themselves via the facade finalizer.

The schema itself is built by ``create_dependency_test_db`` from the sibling
module ``runtime.api.test_dependency_schema`` — re-exported here so the split
files can import everything from one place if they prefer (they may still
import directly from ``test_dependency_schema`` to mirror the original style).
"""

from __future__ import annotations

from typing import Any

from runtime.api.test_dependency_schema import create_dependency_test_db


PROJECT_IDS = {
    "yoke": 1,
    "buzz": 2,
}


def make_test_db() -> Any:
    """Create a disposable DB with minimal items + dependencies schema."""
    return create_dependency_test_db()


def insert_item(
    conn: Any,
    item_id: int,
    title: str = "",
    status: str = "idea",
    priority: str = "medium",
    project: str = "yoke",
    frozen: int = 0,
    created_at: str = "2026-01-01T00:00:00Z",
    item_type: str = "issue",
    spec: str | None = None,
) -> None:
    if not title:
        title = f"Item {item_id}"
    if spec is None:
        # Default spec is non-trivial so frontier_compute's idea-body
        # completeness check classifies the row as runnable. Tests that
        # specifically want a title-only body must pass spec="" or a
        # spec equal to "# {title}".
        spec = f"# {title}\n\nDefault spec body for fixture {item_id}."
    project_id = int(project) if str(project).isdigit() else PROJECT_IDS.get(project, 1)
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "project_id, project_sequence, frozen, created_at, updated_at, spec) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            item_id, title, item_type, status, priority,
            project_id, item_id, frozen,
            created_at, created_at, spec,
        ),
    )


def insert_dep(
    conn: Any,
    dependent: str,
    blocking: str,
    gate_point: str = "activation",
    satisfaction: str = "status:done",
) -> None:
    """Insert a dependency row using canonical schema."""
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, gate_point, satisfaction, source, created_at) "
        "VALUES (%s, %s, %s, %s, 'test', '2026-01-01T00:00:00Z')",
        (dependent, blocking, gate_point, satisfaction),
    )


__all__ = [
    "create_dependency_test_db",
    "make_test_db",
    "insert_item",
    "insert_dep",
]
