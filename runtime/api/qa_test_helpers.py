"""Shared fixture builders for the ``test_qa_*`` split files.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports ``make_qa_db_file`` and ``make_basic_requirement`` and wraps them
in local ``@pytest.fixture`` shims (``with make_qa_db_file(tmp_path) as path:
yield path``), then re-exports ``Path`` and ``qa`` so the shape of imports
stays uniform across the family.

Distinct from ``qa_full_test_helpers`` which serves the broader ``test_qa_full*``
suite (different schema scaffolding and seed data). The two helper modules can
coexist; do not merge them.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from yoke_core.domain import qa
from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.api_workflow_test_helpers import (
    install_workflow_registry_and_pin_items,
)
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.qa_transition_test_support import QA_GATED_TRANSITION


_QA_PARENT_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
);
INSERT INTO projects (id, slug, name) VALUES (1, 'yoke', 'yoke');
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'implementing',
    priority TEXT NOT NULL DEFAULT 'medium',
    project_id INTEGER NOT NULL DEFAULT 1,
    project_sequence INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'test'
);
INSERT INTO items (id, project_sequence, created_at, updated_at)
VALUES
    (5, 5, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z'),
    (10, 10, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z'),
    (20, 20, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z'),
    (42, 42, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z'),
    (99, 99, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z');
CREATE TABLE epic_tasks (
    id INTEGER PRIMARY KEY,
    epic_id INTEGER NOT NULL,
    task_num INTEGER NOT NULL,
    title TEXT,
    status TEXT DEFAULT 'planning',
    body TEXT,
    dependencies TEXT,
    UNIQUE(epic_id, task_num)
);
INSERT INTO epic_tasks (epic_id, task_num, title)
VALUES (5, 1, 'Task 1'), (5, 3, 'Task 3');
"""


def _apply_qa_schema() -> None:
    """``apply_schema`` strategy building the QA schema via the backend factory.

    Builds the schema against the active Postgres authority.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _QA_PARENT_SCHEMA)
        install_workflow_registry_and_pin_items(
            conn,
            workflow_id_by_item={5: "epic"},
        )
    finally:
        conn.close()
    qa.cmd_init()


@contextlib.contextmanager
def make_qa_db_file(tmp_path: Path):
    """Yield a backend-aware DB token with the QA tables initialised.

    Delegates to the ``file_test_db`` seam so the fixture gets a disposable
    per-test Postgres database, dropped on exit.
    Used as a context manager: ``with make_qa_db_file(tmp_path) as db_path:``.
    """
    with init_test_db(tmp_path, apply_schema=_apply_qa_schema) as db_path:
        yield db_path


def make_basic_requirement(db_path: str) -> int:
    """Create a basic ``unit_test`` / ``verification`` requirement.

    Returns the requirement ID used by tests that need one seeded row.
    """
    return qa.cmd_requirement_add(
        db_path=db_path,
        item_id=42,
        qa_kind="unit_test",
        qa_phase="verification",
        workflow_transition_id=QA_GATED_TRANSITION,
    )


__all__ = [
    "make_qa_db_file",
    "make_basic_requirement",
    "Path",
    "qa",
]
