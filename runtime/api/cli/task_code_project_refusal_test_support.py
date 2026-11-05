# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import os

from io import StringIO

from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)

from yoke_cli.commands.adapters import task

from yoke_contracts.session_identity import AMBIENT_ENV_VARS


def remove_code_repository(db_path: str, slug: str = "yoke") -> None:
    """Make the fixture project folder-only: no registered code repository."""
    conn = _conn(db_path)
    try:
        conn.execute("UPDATE projects SET github_repo = NULL WHERE slug = %s", (slug,))
        conn.commit()
    finally:
        conn.close()
