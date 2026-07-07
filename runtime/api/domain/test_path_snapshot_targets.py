"""Tests for bulk snapshot target resolution.

Covers ``resolve_snapshot_target_ids`` (the bulk form of the C4
find-or-mint contract) and dedicated coverage for the bulk disappearance
query. Single-path resolver tests live in ``test_path_registry.py``;
snapshot-builder tests in ``test_path_snapshots.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import path_registry
from yoke_core.domain.path_registry import (
    KIND_DIRECTORY,
    KIND_FILE,
    ROOT_PATH_SENTINEL,
)
from yoke_core.domain.path_snapshot_targets import (
    _targets_with_observed_disappearance,
    resolve_snapshot_target_ids,
)
from yoke_core.domain.schema_init_tables import (
    create_path_registry_tables,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

NOW = "2026-04-29T00:00:00Z"


def _p(conn) -> str:
    from yoke_core.domain import db_backend
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_path_registry_schema() -> None:
    """Build the minimal path-registry schema on the active test backend."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, "
            "name TEXT NOT NULL, "
            "default_branch TEXT NOT NULL DEFAULT 'main', github_repo TEXT, "
            "public_item_prefix TEXT NOT NULL DEFAULT 'YOK', "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (4, "p", "p", NOW),
        )
        conn.execute("CREATE TABLE events (event_id TEXT PRIMARY KEY)")
        create_path_registry_tables(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def fresh_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_path_registry_schema) as path:
        conn = connect_test_db(path)
        try:
            yield conn
        finally:
            conn.close()


def _snapshot(conn, sha: str, *, project_id: int = 4,
              present: tuple = ()) -> int:
    cur = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        f"VALUES ({_p(conn)}, {_p(conn)}, {_p(conn)}) RETURNING id",
        (project_id, sha, NOW),
    )
    snapshot_id = int(cur.fetchone()[0])
    for target_id in present:
        conn.execute(
            "INSERT INTO path_snapshot_entries (snapshot_id, target_id) "
            f"VALUES ({_p(conn)}, {_p(conn)})",
            (snapshot_id, target_id),
        )
    return snapshot_id


def test_bulk_snapshot_resolution_preserves_reappearance_generation(
    fresh_db,
):
    first = resolve_snapshot_target_ids(
        fresh_db,
        project_id=4,
        targets=[
            (ROOT_PATH_SENTINEL, KIND_DIRECTORY),
            ("x.py", KIND_FILE),
        ],
        now_iso=NOW,
    ).target_ids["x.py"]
    _snapshot(fresh_db, "sha1", present=(first,))
    _snapshot(fresh_db, "sha2")

    second = resolve_snapshot_target_ids(
        fresh_db,
        project_id=4,
        targets=[
            (ROOT_PATH_SENTINEL, KIND_DIRECTORY),
            ("x.py", KIND_FILE),
        ],
        now_iso=NOW,
    ).target_ids["x.py"]

    assert second != first
    row = fresh_db.execute(
        f"SELECT generation FROM path_targets WHERE id = {_p(fresh_db)}",
        (second,),
    ).fetchone()
    assert row[0] == 2


class TestBulkDisappearanceQuery:
    """Dedicated coverage for the bulk disappearance query.

    The set-form of ``path_registry._disappearance_observed`` (the C4
    trajectory): disappeared iff the target was present in some snapshot
    and a later snapshot of the same project lacks it.
    """

    def _mint(self, conn, path_string: str) -> int:
        return path_registry._mint_target(
            conn, 4, path_string, KIND_FILE, None, 1, NOW
        )

    def _disappeared(self, conn, target_ids) -> set:
        return _targets_with_observed_disappearance(
            conn, project_id=4, target_ids=target_ids
        )

    def test_present_then_absent_from_later_snapshot(self, fresh_db):
        tid = self._mint(fresh_db, "gone.py")
        _snapshot(fresh_db, "s1", present=(tid,))
        _snapshot(fresh_db, "s2")

        assert self._disappeared(fresh_db, [tid]) == {tid}

    def test_present_in_latest_snapshot_is_not_disappeared(self, fresh_db):
        tid = self._mint(fresh_db, "alive.py")
        _snapshot(fresh_db, "s1", present=(tid,))

        assert self._disappeared(fresh_db, [tid]) == set()

    def test_never_present_target_is_degenerate_not_disappeared(
        self, fresh_db
    ):
        # First-scan trajectory: snapshots exist but the target was never
        # in one (e.g. a planned target) — reuse, never a generation bump.
        tid = self._mint(fresh_db, "planned.py")
        _snapshot(fresh_db, "s1")

        assert self._disappeared(fresh_db, [tid]) == set()

    def test_reappearance_in_newest_snapshot_clears_disappearance(
        self, fresh_db
    ):
        tid = self._mint(fresh_db, "flicker.py")
        _snapshot(fresh_db, "s1", present=(tid,))
        _snapshot(fresh_db, "s2")
        _snapshot(fresh_db, "s3", present=(tid,))

        assert self._disappeared(fresh_db, [tid]) == set()

    def test_other_project_snapshots_do_not_count(self, fresh_db):
        fresh_db.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            f"VALUES ({_p(fresh_db)}, {_p(fresh_db)}, {_p(fresh_db)}, "
            f"{_p(fresh_db)})",
            (5, "other", "Other", NOW),
        )
        tid = self._mint(fresh_db, "ours.py")
        _snapshot(fresh_db, "s1", present=(tid,))
        _snapshot(fresh_db, "other-s2", project_id=5)

        assert self._disappeared(fresh_db, [tid]) == set()

    def test_mixed_batch_returns_only_disappeared_ids(self, fresh_db):
        gone = self._mint(fresh_db, "gone.py")
        alive = self._mint(fresh_db, "alive.py")
        never = self._mint(fresh_db, "never.py")
        _snapshot(fresh_db, "s1", present=(gone, alive))
        _snapshot(fresh_db, "s2", present=(alive,))

        assert self._disappeared(
            fresh_db, [gone, alive, never, gone]
        ) == {gone}

    def test_empty_input_returns_empty_set(self, fresh_db):
        assert self._disappeared(fresh_db, []) == set()
