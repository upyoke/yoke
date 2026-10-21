"""Seed items whose public ref number differs from their ``items.id``.

Lane names carry ``PREFIX-<project_sequence>``. These rows make each
sequence also equal some *other* item's ``items.id``, so a reader that
parses the number as the storage key lands on the wrong row and fails.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
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


def add_minimal_item(
    db_path: str, item_id: int, *, project_id: int, sequence: int
) -> None:
    """Create a bare ``items`` table holding one row, for schemas without one."""
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, "
            "project_id INTEGER, project_sequence INTEGER)"
        )
        conn.execute(
            "INSERT INTO items VALUES (%s, %s, %s)", (item_id, project_id, sequence)
        )
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def lane_ref_db(tmp_path: Any) -> Iterator[str]:
    """Yield a DB where ``YOK-60`` is item 600 and ``BUZ-60`` is item 800.

    Item 60 also exists (as ``YOK-9060``), so reading the number in either
    ref as ``items.id`` attributes to the wrong item.
    """
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            seed_buzz_project(conn)
            seed_item(conn, 600, project_id=1, sequence=60, status="implementing")
            seed_item(conn, 60, project_id=1, sequence=9060, status="done")
            seed_item(
                conn,
                800,
                project_id=BUZZ_PROJECT_ID,
                sequence=60,
                status="implementing",
            )
            conn.commit()
        finally:
            conn.close()
        yield db_path


__all__ = [
    "BUZZ_PROJECT_ID",
    "add_minimal_item",
    "lane_ref_db",
    "seed_buzz_project",
    "seed_item",
]
