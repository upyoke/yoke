# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import os

from unittest.mock import patch

import pytest

from yoke_core.domain import epic

from runtime.api.conftest import insert_item, insert_epic_task

from runtime.api.fixtures.file_test_db import (
    apply_test_schema,
    connect_test_db,
    init_test_db,
)


@pytest.fixture
def db(tmp_path):
    # Backend-aware: SQLite file on SQLite, disposable per-test database on
    # Postgres (YOKE_PG_DSN repointed for the context).
    with init_test_db(tmp_path, apply_schema=apply_test_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()
