"""Shared helpers for the render_body pytest suites.

Split out of the original ``test_render_body.py`` so each authored test file
stays under the 350-line limit.
"""

from __future__ import annotations

import contextlib

import pytest
from pathlib import Path

from yoke_core.domain import db_backend, schema, shepherd
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_render_body_schema() -> None:
    """``apply_schema`` strategy for the render_body suites.

    The legacy helper built the schema in two steps: ``schema.cmd_init()`` for
    the production tables, then ``shepherd.cmd_init(conn)`` for the shepherd /
    dependency tables this family exercises. Both initialization paths now use
    backend-aware schema helpers, so the fixture does not install compatibility
    introspection objects.
    """
    from yoke_core.domain import db_backend

    schema.cmd_init()
    conn = db_backend.connect()
    try:
        seed_project_identities(conn)
        shepherd.cmd_init(conn)
    finally:
        conn.close()


@contextlib.contextmanager
def _init_db(tmp_path: Path):
    """Yield a ``db_path`` token with the render_body schema applied.

    Context-managed because it provisions a disposable per-test Postgres
    database and repoints ``YOKE_PG_DSN`` only for the block's lifetime; every
    DB operation (connect, seed, render) must therefore run inside the ``with``
    block.
    """
    with init_test_db(tmp_path, apply_schema=_apply_render_body_schema) as path:
        yield path


@pytest.fixture
def db_path(tmp_path: Path):
    """Per-test ``db_path`` with the render_body schema applied (CM lifecycle).

    ``_init_db`` is a context manager (Postgres provisions a disposable per-test
    DB and repoints YOKE_PG_DSN for the block only); exposing it as a fixture
    lets the imperative test bodies receive a plain path token while pytest owns
    the enter/exit.
    """
    with _init_db(tmp_path) as path:
        yield path


def _connect(db_path: str):
    return connect_test_db(db_path)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_item(conn, item_id: int, title: str) -> None:
    p = _p(conn)
    conn.execute(
        f"""
        INSERT INTO items (
            id, title, type, status, priority, flow, rework_count, frozen,
            created_at, updated_at, source, project_id, project_sequence
        ) VALUES ({p}, {p}, 'issue', 'idea', 'medium', 'accelerated', 0, 0, {p}, {p}, 'user', {p}, {p})
        """,
        (
            item_id,
            title,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            SEED_PROJECT_IDS["yoke"],
            item_id,
        ),
    )
    conn.commit()


def _set_field(conn, item_id: int, field: str, value: str) -> None:
    p = _p(conn)
    conn.execute(f"UPDATE items SET {field} = {p} WHERE id = {p}", (value, item_id))
    conn.commit()
