"""Shared helpers for test_update_status*.py modules.

Pure helpers (no pytest fixtures) — safe to import from any test module
without triggering pytest fixture-discovery side effects. The naming
convention `<stem>_test_helpers.py` keeps pytest from collecting an
empty test module.
"""

from __future__ import annotations

import io
from typing import Any
from unittest import mock

from yoke_core.domain import db_backend
from yoke_core.domain import update_status


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def task_field(conn: Any, epic_id: int, task_num: int, field: str):
    p = _p(conn)
    row = conn.execute(
        f"SELECT {field} FROM epic_tasks WHERE epic_id={p} AND task_num={p}",
        (str(epic_id), task_num),
    ).fetchone()
    return row[0] if row else None


def item_field(conn: Any, item_id: int, field: str):
    p = _p(conn)
    row = conn.execute(
        f"SELECT {field} FROM items WHERE id={p}",
        (item_id,),
    ).fetchone()
    return row[0] if row else None


def update(conn, epic_id, task_num, new_status, note="", **kwargs):
    """Call update_task_status with captured output and mocked externals."""
    out = io.StringIO()
    err = io.StringIO()
    # Mock external integration hooks to keep tests in-process.
    with mock.patch.object(update_status, "_history_insert"), \
         mock.patch.object(update_status, "_rebuild_board"), \
         mock.patch.object(update_status, "_verify_claim"):
        rc = update_status.update_task_status(
            conn, str(epic_id), str(task_num), new_status, note,
            no_github=True,
            stdout=out,
            stderr=err,
            **kwargs,
        )
    return rc, out.getvalue(), err.getvalue()
