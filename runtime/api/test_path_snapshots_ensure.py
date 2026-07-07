"""Tests for the lazy-snapshot helpers.

Covers ``ensure_snapshot_at`` and ``build_snapshot_at_sha`` — the
arbitrary-SHA snapshot path used by activate, boundary checks, and the
post-commit hook so that callers do not have to pre-warm with
``build_head_snapshot``.

Identity-as-location continues to come from
``runtime/api/domain/path_registry.py``; these tests focus on the SHA
selection and idempotency contract introduced by ``ensure_snapshot_at``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain._path_snapshots_test_helpers import (
    NOW,
    _project_row_id,
    path_snapshot_db,
)
from yoke_core.domain.path_snapshots import (
    PathSnapshotError,
    build_snapshot_at_sha,
    ensure_snapshot_at,
)
from yoke_core.domain.schema_init_tables import (
    create_path_registry_tables,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _make_apply_schema(repo_path: Path, project_id: str = "demo"):
    """Build a zero-arg ``apply_schema`` strategy for the CLI tests.

    Seeds the ``projects`` row + path-registry tables against the
    backend-resolved DB so the CLI (which re-resolves its own backend
    connection) reads the same data on SQLite and Postgres. Cross-family FK
    clauses in the registry DDL are stripped by the Postgres facade.
    """

    def _apply() -> None:
        from yoke_core.domain import db_backend
        from yoke_core.domain.events_schema import _create_events_table

        conn = db_backend.connect()
        try:
            p = _p(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS projects ("
                "id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, "
                "name TEXT NOT NULL, "
                "public_item_prefix TEXT NOT NULL DEFAULT 'YOK', "
                "created_at TEXT NOT NULL)"
            )
            register_machine_checkout(
                repo_path.parent / "machine-config",
                repo_path,
                _project_row_id(project_id),
            )
            conn.execute(
                "INSERT INTO projects "
                "(id, slug, name, created_at) "
                f"VALUES ({p}, {p}, {p}, {p})",
                (
                    _project_row_id(project_id),
                    project_id,
                    project_id,
                    NOW,
                ),
            )
            _create_events_table(conn)
            create_path_registry_tables(conn)
            conn.commit()
        finally:
            conn.close()

    return _apply


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a repo with two commits and return (repo, sha1, sha2).

    sha1: head with README.md only
    sha2: HEAD with README.md + src/a.py
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    sha1 = _git(repo, "rev-parse", "HEAD")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "second")
    sha2 = _git(repo, "rev-parse", "HEAD")
    return repo, sha1, sha2


class TestEnsureSnapshotAt:
    def test_returns_existing_id_when_row_present(self, tmp_path):
        repo, _sha1, sha2 = _make_repo(tmp_path)
        with path_snapshot_db(tmp_path, repo) as conn:
            first = ensure_snapshot_at(conn, "demo", sha2)
            second = ensure_snapshot_at(conn, "demo", sha2)
            assert first == second
            p = _p(conn)
            count = conn.execute(
                "SELECT COUNT(*) FROM path_snapshots "
                f"WHERE project_id = {p} AND commit_sha = {p}",
                (_project_row_id("demo"), sha2),
            ).fetchone()[0]
            assert count == 1

    def test_builds_when_missing(self, tmp_path):
        repo, _sha1, sha2 = _make_repo(tmp_path)
        with path_snapshot_db(tmp_path, repo) as conn:
            snap_id = ensure_snapshot_at(conn, "demo", sha2)
            assert snap_id > 0
            p = _p(conn)
            paths = {
                r[0] for r in conn.execute(
                    "SELECT path_string FROM path_targets t "
                    "JOIN path_snapshot_entries e ON e.target_id = t.id "
                    f"WHERE e.snapshot_id = {p} AND t.kind = 'file'",
                    (snap_id,),
                ).fetchall()
            }
            assert paths == {"README.md", "src/a.py"}

    def test_idempotent_with_concurrent_callers(self, tmp_path):
        repo, _sha1, sha2 = _make_repo(tmp_path)
        with path_snapshot_db(tmp_path, repo) as conn:
            ids = {ensure_snapshot_at(conn, "demo", sha2) for _ in range(3)}
            assert len(ids) == 1

    def test_non_head_sha_walks_that_commit_tree(self, tmp_path):
        repo, sha1, sha2 = _make_repo(tmp_path)
        with path_snapshot_db(tmp_path, repo) as conn:
            # HEAD has README + src/a.py; sha1 only has README.
            snap_id_old = ensure_snapshot_at(conn, "demo", sha1)
            snap_id_head = ensure_snapshot_at(conn, "demo", sha2)
            assert snap_id_old != snap_id_head
            p = _p(conn)
            old_paths = {
                r[0] for r in conn.execute(
                    "SELECT path_string FROM path_targets t "
                    "JOIN path_snapshot_entries e ON e.target_id = t.id "
                    f"WHERE e.snapshot_id = {p} AND t.kind = 'file'",
                    (snap_id_old,),
                ).fetchall()
            }
            head_paths = {
                r[0] for r in conn.execute(
                    "SELECT path_string FROM path_targets t "
                    "JOIN path_snapshot_entries e ON e.target_id = t.id "
                    f"WHERE e.snapshot_id = {p} AND t.kind = 'file'",
                    (snap_id_head,),
                ).fetchall()
            }
            assert old_paths == {"README.md"}
            assert head_paths == {"README.md", "src/a.py"}


class TestBuildSnapshotAtSha:
    def test_empty_sha_raises(self, tmp_path):
        repo, _sha1, _sha2 = _make_repo(tmp_path)
        with path_snapshot_db(tmp_path, repo) as conn:
            with pytest.raises(PathSnapshotError, match="commit_sha"):
                build_snapshot_at_sha(conn, "demo", "")

    def test_unknown_sha_raises(self, tmp_path):
        repo, _sha1, _sha2 = _make_repo(tmp_path)
        with path_snapshot_db(tmp_path, repo) as conn:
            with pytest.raises(PathSnapshotError, match="git ls-tree"):
                build_snapshot_at_sha(conn, "demo", "0" * 40)


class TestEnsureHeadCli:
    def test_cli_ensure_head_invokes_build_head(self, tmp_path, monkeypatch):
        repo, _sha1, sha2 = _make_repo(tmp_path)

        with init_test_db(
            tmp_path, apply_schema=_make_apply_schema(repo)
        ) as db_path:
            from yoke_core.domain import schema_common as _schema
            monkeypatch.setattr(_schema, "_resolve_db_path", lambda: db_path)

            from yoke_core.domain import path_snapshots as _ps
            rc = _ps.main(["--ensure-head", "demo"])
            assert rc == 0

            check = connect_test_db(db_path)
            try:
                p = _p(check)
                row = check.execute(
                    "SELECT id FROM path_snapshots "
                    f"WHERE project_id = {p} AND commit_sha = {p}",
                    (_project_row_id("demo"), sha2),
                ).fetchone()
                assert row is not None
            finally:
                check.close()

    def test_cli_no_args_errors(self, tmp_path):
        from yoke_core.domain import path_snapshots as _ps
        with pytest.raises(SystemExit):
            _ps.main([])

    def test_cli_ensure_head_also_warms_integration_target_when_local_ahead(
        self, tmp_path, monkeypatch
    ):
        # Reproduces the dogfood case where local main is ahead of
        # origin/main: --ensure-head must materialise snapshots for BOTH
        # the local HEAD SHA (post-commit-hook contract) AND the
        # integration-target SHA activation will query.
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("hi\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "first")

        bare = tmp_path / "origin.git"
        subprocess.run(
            ["git", "init", "--bare", "-q", "-b", "main", str(bare)],
            check=True,
        )
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "main")
        origin_sha = _git(repo, "rev-parse", "origin/main")

        (repo / "ahead.txt").write_text("ahead\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "ahead of origin")
        local_sha = _git(repo, "rev-parse", "HEAD")
        assert origin_sha != local_sha

        with init_test_db(
            tmp_path, apply_schema=_make_apply_schema(repo)
        ) as db_path:
            from yoke_core.domain import schema_common as _schema
            monkeypatch.setattr(_schema, "_resolve_db_path", lambda: db_path)

            from yoke_core.domain import path_snapshots as _ps
            rc = _ps.main(["--ensure-head", "demo"])
            assert rc == 0

            check = connect_test_db(db_path)
            try:
                p = _p(check)
                local_row = check.execute(
                    "SELECT id FROM path_snapshots "
                    f"WHERE project_id = {p} AND commit_sha = {p}",
                    (_project_row_id("demo"), local_sha),
                ).fetchone()
                origin_row = check.execute(
                    "SELECT id FROM path_snapshots "
                    f"WHERE project_id = {p} AND commit_sha = {p}",
                    (_project_row_id("demo"), origin_sha),
                ).fetchone()
                assert local_row is not None, "local HEAD snapshot missing"
                assert origin_row is not None, (
                    "integration-target snapshot missing"
                )
            finally:
                check.close()
