"""Shared helpers and fixtures for the lint_event_registry pytest suites.

Split out of the original ``test_lint_event_registry.py`` so each authored
test file stays under the 350-line limit. Lives outside the ``test_*.py``
collection pattern so pytest does not pick it up as a test module.
"""

from __future__ import annotations

import json
import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import init_test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_registry_schema() -> None:
    """``init_test_db`` strategy: an ``event_registry`` table with two rows.

    Resolves its connection through the backend factory (``YOKE_DB`` on
    SQLite, the repointed ``YOKE_PG_DSN`` on Postgres) so the same fixture
    builds on both engines.
    """
    conn = db_backend.connect()
    try:
        conn.execute(
            """
            CREATE TABLE event_registry (
                event_name TEXT PRIMARY KEY,
                event_kind TEXT NOT NULL,
                event_type TEXT NOT NULL,
                owner_service TEXT NOT NULL,
                description TEXT NOT NULL,
                context_schema TEXT,
                severity_default TEXT NOT NULL DEFAULT 'INFO',
                added_in TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        p = _placeholder(conn)
        conn.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, "
            f"owner_service, description, status) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            ("ActiveEvent", "lifecycle", "system", "core", "active test event", "active"),
        )
        conn.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, "
            f"owner_service, description, status) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            (
                "DeprecatedEvent",
                "lifecycle",
                "system",
                "core",
                "deprecated test event",
                "deprecated",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _apply_no_table_schema() -> None:
    """``init_test_db`` strategy: a DB without an ``event_registry`` table."""
    conn = db_backend.connect()
    try:
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def registry_db(tmp_path):
    """A DB with an ``event_registry`` table and two rows (both backends)."""
    with init_test_db(tmp_path, apply_schema=_apply_registry_schema) as path:
        yield path


@pytest.fixture()
def no_table_db(tmp_path):
    """A DB without an ``event_registry`` table (both backends)."""
    with init_test_db(tmp_path, apply_schema=_apply_no_table_schema) as path:
        yield path


def _payload(command: str, shape: str = "tool_input", **meta) -> str:
    """Serialize a PreToolUse payload with the requested shape."""
    if shape == "top_level":
        data: dict = {"command": command}
    else:
        data = {shape: {"command": command}}
    data.update(meta)
    return json.dumps(data)
