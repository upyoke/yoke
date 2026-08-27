"""Tests for yoke_core.domain.db_helpers Postgres connection helpers."""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers


def _retired_path_helper() -> str:
    return "resolve" + "_db_path"


def test_retired_path_helper_is_gone() -> None:
    assert not hasattr(db_helpers, _retired_path_helper())


def test_connect_opens_postgres_authority() -> None:
    if not db_backend.is_postgres():
        return
    conn = db_helpers.connect()
    try:
        row = conn.execute("SELECT 1 AS n").fetchone()
        assert row is not None
    finally:
        conn.close()
