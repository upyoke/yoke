"""Seed items whose public ref number differs from their ``items.id``.

Lane names carry ``PREFIX-<project_sequence>``. These rows make each
sequence also equal some *other* item's ``items.id``, so a reader that
parses the number as the storage key lands on the wrong row and fails.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import iso8601_now

BUZZ_PROJECT_ID = 7


def seed_buzz_project(conn: Any) -> None:
    conn.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (%s, 'buzz', 'Buzz', 'BUZ', %s)",
        (BUZZ_PROJECT_ID, iso8601_now()),
    )


def seed_item(
    conn: Any,
    item_id: int,
    *,
    project_id: int,
    sequence: int,
    status: str,
    workflow_id: str = "issue",
) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, "
        "status, priority, project_id, project_sequence, created_at, "
        "updated_at, source) VALUES (%s, %s, %s, (SELECT current_version_id "
        "FROM workflows WHERE id = %s), %s, 'medium', %s, %s, %s, %s, 'test')",
        (
            item_id,
            f"item {item_id}",
            workflow_id,
            workflow_id,
            status,
            project_id,
            sequence,
            now,
            now,
        ),
    )


__all__ = ["BUZZ_PROJECT_ID", "seed_buzz_project", "seed_item"]
