"""Tests for the canonical path registry identity layer.

Covers target_at + parent/child traversal, the C4 disappearance /
reappearance generation contract, and the static no-Project-Structure /
no-git-similarity audits.

Snapshot-builder tests live in
``runtime/api/domain/test_path_snapshots.py``. Schema shape tests live in
``runtime/api/domain/test_path_registry_schema.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import path_registry, path_snapshots
from yoke_core.domain.path_registry import (
    KIND_DIRECTORY,
    KIND_FILE,
    ROOT_PATH_SENTINEL,
    _all_paths_with_kinds,
    _parent_path_string,
    _resolve_path_target_id,
    ancestors_of,
    descendants_of,
    target_at,
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


# ---------------------------------------------------------------------------
# Path utilities (AC-17 sentinel handling)
# ---------------------------------------------------------------------------


class TestPathUtilities:
    def test_root_sentinel_has_no_parent(self):
        assert _parent_path_string(ROOT_PATH_SENTINEL) is None

    def test_top_level_path_parents_to_root(self):
        assert _parent_path_string("README.md") == ROOT_PATH_SENTINEL

    def test_nested_path_parent_chain(self):
        assert _parent_path_string("runtime/api/foo.py") == "runtime/api"
        assert _parent_path_string("runtime/api") == "runtime"
        assert _parent_path_string("runtime") == ROOT_PATH_SENTINEL

    def test_all_paths_with_kinds_root_first_then_dirs_then_files(self):
        files = ["a/b/c.py", "a/d.py", "top.txt"]
        out = _all_paths_with_kinds(files)
        assert out[0] == (ROOT_PATH_SENTINEL, KIND_DIRECTORY)
        # Every file appears exactly once with kind=file.
        files_in_out = [p for p, k in out if k == KIND_FILE]
        assert sorted(files_in_out) == sorted(set(files))
        # Every parent directory appears as kind=directory before its
        # children.  Verify ``a/b`` precedes ``a/b/c.py``.
        positions = {p: i for i, (p, _k) in enumerate(out)}
        assert positions["a/b"] < positions["a/b/c.py"]
        assert positions["a"] < positions["a/b"]


# ---------------------------------------------------------------------------
# Find-or-mint and target_at (AC-7 idempotency, AC-19 uniqueness)
# ---------------------------------------------------------------------------


class TestTargetIdentity:
    def test_initial_mint_returns_generation_one(self, fresh_db):
        tid = _resolve_path_target_id(
            fresh_db, 4, "a/b.py", KIND_FILE, None, NOW
        )
        row = fresh_db.execute(
            f"SELECT generation FROM path_targets WHERE id = {_p(fresh_db)}",
            (tid,),
        ).fetchone()
        assert row[0] == 1

    def test_idempotent_resolution_reuses_id(self, fresh_db):
        a = _resolve_path_target_id(
            fresh_db, 4, "x.py", KIND_FILE, None, NOW
        )
        b = _resolve_path_target_id(
            fresh_db, 4, "x.py", KIND_FILE, None, NOW
        )
        assert a == b

    def test_target_at_returns_latest_generation(self, fresh_db):
        # Mint two generations explicitly to verify target_at picks the
        # latest.  Manual generation seeding only — no snapshot trajectory
        # required.
        p = _p(fresh_db)
        fresh_db.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, "
            f"parent_target_id, created_at) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            (4, KIND_FILE, "x.py", 1, None, NOW),
        )
        cur = fresh_db.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, "
            f"parent_target_id, created_at) VALUES ({p}, {p}, {p}, {p}, {p}, {p}) "
            "RETURNING id",
            (4, KIND_FILE, "x.py", 2, None, NOW),
        )
        latest = int(cur.fetchone()[0])
        assert target_at(fresh_db, 4, "x.py") == latest
        assert target_at(fresh_db, 4, "missing") is None

    def test_disappearance_then_reappearance_bumps_generation(
        self, fresh_db
    ):
        # First scan: mint generation 1.
        first_target_id = _resolve_path_target_id(
            fresh_db, 4, "x.py", KIND_FILE, None, NOW
        )
        # Snapshot 1 has it present.
        cur = fresh_db.execute(
            "INSERT INTO path_snapshots "
            f"(project_id, commit_sha, built_at) VALUES ({_p(fresh_db)}, {_p(fresh_db)}, {_p(fresh_db)}) "
            "RETURNING id",
            (4, "sha1", NOW),
        )
        s1 = int(cur.fetchone()[0])
        fresh_db.execute(
            "INSERT INTO path_snapshot_entries (snapshot_id, target_id) "
            f"VALUES ({_p(fresh_db)}, {_p(fresh_db)})",
            (s1, first_target_id),
        )
        # Snapshot 2: path is absent (no entry inserted).
        fresh_db.execute(
            "INSERT INTO path_snapshots "
            f"(project_id, commit_sha, built_at) VALUES ({_p(fresh_db)}, {_p(fresh_db)}, {_p(fresh_db)})",
            (4, "sha2", NOW),
        )
        # Path reappears at scan time → must mint generation 2.
        second_target_id = _resolve_path_target_id(
            fresh_db, 4, "x.py", KIND_FILE, None, NOW
        )
        assert second_target_id != first_target_id
        row = fresh_db.execute(
            f"SELECT generation FROM path_targets WHERE id = {_p(fresh_db)}",
            (second_target_id,),
        ).fetchone()
        assert row[0] == 2

    def test_kind_change_bumps_generation(self, fresh_db):
        first = _resolve_path_target_id(
            fresh_db, 4, "asset", KIND_FILE, None, NOW
        )
        second = _resolve_path_target_id(
            fresh_db, 4, "asset", KIND_DIRECTORY, None, NOW
        )
        assert second != first
        row = fresh_db.execute(
            f"SELECT kind, generation FROM path_targets WHERE id = {_p(fresh_db)}",
            (second,),
        ).fetchone()
        assert (row[0], row[1]) == (KIND_DIRECTORY, 2)


# ---------------------------------------------------------------------------
# Ancestors / descendants traversal (AC-3 substrate, AC-17 root sentinel)
# ---------------------------------------------------------------------------


class TestAncestorsDescendants:
    def _build_tree(self, conn):
        ids = {}
        ids[ROOT_PATH_SENTINEL] = _resolve_path_target_id(
            conn, 4, ROOT_PATH_SENTINEL, KIND_DIRECTORY, None, NOW
        )
        for path, kind in [
            ("a", KIND_DIRECTORY),
            ("a/b", KIND_DIRECTORY),
            ("a/b/c.py", KIND_FILE),
            ("a/d.py", KIND_FILE),
        ]:
            parent = _parent_path_string(path)
            parent_id = ids[parent] if parent is not None else None
            ids[path] = _resolve_path_target_id(
                conn, 4, path, kind, parent_id, NOW
            )
        return ids

    def test_root_has_no_parent(self, fresh_db):
        ids = self._build_tree(fresh_db)
        assert ancestors_of(fresh_db, ids[ROOT_PATH_SENTINEL]) == []

    def test_ancestors_are_root_to_leaf_in_nearest_first(self, fresh_db):
        ids = self._build_tree(fresh_db)
        chain = ancestors_of(fresh_db, ids["a/b/c.py"])
        assert chain == [ids["a/b"], ids["a"], ids[ROOT_PATH_SENTINEL]]

    def test_descendants_includes_full_subtree(self, fresh_db):
        ids = self._build_tree(fresh_db)
        sub = set(descendants_of(fresh_db, ids["a"]))
        assert ids["a/b"] in sub
        assert ids["a/b/c.py"] in sub
        assert ids["a/d.py"] in sub
        assert ids["a"] not in sub

    def test_root_descendants_cover_every_other_target(self, fresh_db):
        ids = self._build_tree(fresh_db)
        sub = set(descendants_of(fresh_db, ids[ROOT_PATH_SENTINEL]))
        expected = {tid for path, tid in ids.items() if path != ROOT_PATH_SENTINEL}
        assert sub == expected


# ---------------------------------------------------------------------------
# Static audits — no Project Structure dep;
# no git rename / similarity flags
# ---------------------------------------------------------------------------


class TestStaticAudits:
    def _read_module(self, mod) -> str:
        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_path_registry_does_not_import_project_structure(self):
        text = self._read_module(path_registry)
        assert "project_structure" not in text

    def test_path_snapshots_does_not_import_project_structure(self):
        text = self._read_module(path_snapshots)
        assert "project_structure" not in text

    def test_no_git_rename_or_similarity_flags_in_scanner(self):
        text = self._read_module(path_snapshots)
        for forbidden in (
            "--find-renames",
            "--find-copies",
            "--similarity",
            "diff-filter",
        ):
            assert forbidden not in text, (
                f"scanner must not use git inference flag {forbidden!r}"
            )

    def test_scanner_does_not_write_continuity_facts(self):
        # Registry and snapshot observation code stays read-only with
        # respect to authored continuity/context tables. The dedicated
        # path_continuity and path_context modules own those writes.
        for module in (path_snapshots, path_registry):
            text = self._read_module(module)
            for table in (
                "path_moves",
                "path_context_values",
                "recording_actors",
            ):
                for stmt in (
                    f"CREATE TABLE IF NOT EXISTS {table}",
                    f"CREATE TABLE {table}",
                    f"INSERT INTO {table}",
                    f"UPDATE {table}",
                    f"DELETE FROM {table}",
                ):
                    assert stmt not in text, (
                        f"forbidden executable statement {stmt!r} in "
                        f"{module.__file__}"
                    )
