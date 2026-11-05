# ruff: noqa: F811
"""Scope uniqueness and transaction safety of lock acquisition."""

from datetime import timedelta

import pytest

from yoke_contracts.timestamps import utc_now
from yoke_core.domain import merge_lock
from yoke_core.domain.db_helpers import instant_parameter
from runtime.api.engines._merge_worktree_test_helpers import mw_db  # noqa: F401


def test_second_acquire_refuses_and_preserves_borrowed_transaction(mw_db):
    conn = mw_db["conn"]
    scope = merge_lock.LockScope("project", "main")
    first = merge_lock.acquire("ITEM-1", conn=conn, scope=scope)
    with pytest.raises(merge_lock.MergeLockHeld):
        merge_lock.acquire("ITEM-2", conn=conn, scope=scope)
    assert conn.execute("SELECT branch FROM merge_locks").fetchall()[0][0] == "ITEM-1"
    assert "ITEM-1" in merge_lock.check(conn, scope=scope)
    merge_lock.release(first, conn=conn)


def test_expired_scope_row_is_replaced(mw_db):
    conn = mw_db["conn"]
    scope = merge_lock.LockScope("project", "main")
    merge_lock.acquire("ITEM-1", conn=conn, scope=scope)
    p = merge_lock._p(conn)
    conn.execute(
        f"UPDATE merge_locks SET expires_at = {p}",
        (instant_parameter(conn, utc_now() - timedelta(minutes=1)),),
    )
    merge_lock.acquire("ITEM-2", conn=conn, scope=scope)
    assert conn.execute("SELECT branch FROM merge_locks").fetchone()[0] == "ITEM-2"


def test_different_scopes_acquire(mw_db):
    conn = mw_db["conn"]
    for scope in [
        merge_lock.LockScope("one", "main"),
        merge_lock.LockScope("two", "main"),
        merge_lock.LockScope("one", "stage"),
    ]:
        merge_lock.acquire("ITEM-1", conn=conn, scope=scope)
    assert conn.execute("SELECT COUNT(*) FROM merge_locks").fetchone()[0] == 3
