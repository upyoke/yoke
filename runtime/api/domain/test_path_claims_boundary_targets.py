from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    seed_target,
)
from yoke_core.domain.path_claims_boundary_targets import (
    path_strings_for_target_ids,
)


class CountingConnection:
    def __init__(self, inner):
        self._conn = inner
        self.path_target_selects = 0

    def execute(self, sql, params=()):
        if "FROM path_targets" in sql:
            self.path_target_selects += 1
        return self._conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_path_strings_are_loaded_in_batches(conn):
    target_ids = [
        seed_target(conn, path_string=f"src/file_{idx}.py")
        for idx in range(5)
    ]
    missing_id = max(target_ids) + 1000
    wrapped = CountingConnection(conn)

    paths = path_strings_for_target_ids(
        wrapped,
        [target_ids[2], missing_id, target_ids[0], target_ids[2], target_ids[4]],
        batch_size=2,
    )

    assert paths == [
        "src/file_2.py",
        f"<unknown target {missing_id}>",
        "src/file_0.py",
        "src/file_2.py",
        "src/file_4.py",
    ]
    assert wrapped.path_target_selects == 3


def test_path_strings_skip_database_for_empty_input(conn):
    wrapped = CountingConnection(conn)

    assert path_strings_for_target_ids(wrapped, []) == []
    assert wrapped.path_target_selects == 0


def test_path_strings_reject_invalid_batch_size(conn):
    with pytest.raises(ValueError, match="batch_size"):
        path_strings_for_target_ids(conn, [1], batch_size=0)
