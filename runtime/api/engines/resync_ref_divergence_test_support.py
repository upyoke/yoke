# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest import mock as mock

import yoke_core.engines.resync as resync_mod

from yoke_core.engines.resync import (
    DriftRecord as DriftRecord,
    PairedItem as PairedItem,
)

from runtime.api.fixtures.file_test_db import connect_test_db as connect_test_db

from runtime.api.engines._resync_test_helpers import (
    populated_db as populated_db,  # noqa: F401 — imported pytest fixture
    test_db,  # noqa: F401 — imported pytest fixture
)

DIVERGENT_ITEM_ID = 4600

DIVERGENT_SEQUENCE = 4544

DIVERGENT_REF = f"YOK-{DIVERGENT_SEQUENCE}"


def _insert_item(
    db_path: str,
    *,
    item_id: int,
    sequence: int,
    title: str,
    github_issue,
    status: str = "implementing",
    workflow: str = "issue",
) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, priority, workflow_id, workflow_version_id, "
            "source, spec, frozen, github_issue, project_id, project_sequence, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, 'medium', %s, "
            "(SELECT current_version_id FROM workflows WHERE id = %s), "
            "'manual', %s, 0, %s, 1, %s, '2026-01-01', '2026-01-01')",
            (
                item_id,
                title,
                status,
                workflow,
                workflow,
                f"{title} spec",
                github_issue,
                sequence,
            ),
        )
        conn.commit()
    finally:
        conn.close()
