"""Duplicate scoped lock rows converge to one durable holder."""

import importlib

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.db_savepoint import savepoint

ENTRY = importlib.import_module(
    "yoke_core.domain.migrations.0102_merge_lock_scope_unique"
)


def test_duplicate_scope_keeps_lowest_id_and_enforces_uniqueness(test_db):
    test_db.execute("DROP INDEX IF EXISTS idx_merge_locks_scope")
    for row_id in [2, 1]:
        test_db.execute(
            "INSERT INTO merge_locks(id, session_id, branch, acquired_at, expires_at, "
            "project_slug, target_branch) VALUES(%s,'holder','ITEM-1',now(),now(),"
            "'project','main')",
            (row_id,),
        )
    from yoke_core.domain.merge_lock_schema import ensure_scope_index
    ensure_scope_index(test_db)
    assert test_db.execute("SELECT COUNT(*) FROM merge_locks").fetchone()[0] == 2
    ENTRY.apply(test_db)
    ENTRY.apply(test_db)
    ENTRY.invariants(test_db)
    assert test_db.execute("SELECT id FROM merge_locks").fetchone()[0] == 1
    with pytest.raises(db_backend.integrity_error_types(test_db)):
        with savepoint(test_db, "duplicate_lock", owns=False):
            test_db.execute(
                "INSERT INTO merge_locks(session_id,branch,acquired_at,expires_at,"
                "project_slug,target_branch) VALUES('other','ITEM-2',now(),now(),"
                "'project','main')"
            )

