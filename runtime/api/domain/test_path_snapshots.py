"""Scanner tests for path registry identity layer — HEAD snapshot building.

Covers idempotency, atomicity, machine-local checkout resolution, and
whole-repo identity against a real git tree.

Identity-layer tests live in
``runtime/api/domain/test_path_registry.py``. Yoke-populated graph
performance tests live in
``runtime/api/domain/test_path_snapshots_yoke_graph.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.path_registry import (
    ROOT_PATH_SENTINEL,
    ancestors_of,
    target_at,
)
from yoke_core.domain.path_snapshots import (
    PathSnapshotError,
    build_head_snapshot,
)
from yoke_core.domain._path_snapshots_test_helpers import (
    NOW,
    path_snapshot_db,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True,
    )
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True,
    )
    return repo


@pytest.fixture
def small_repo(tmp_path):
    return _make_repo(
        tmp_path,
        {
            "README.md": "hi\n",
            "src/a.py": "a\n",
            "src/sub/b.py": "b\n",
            "docs/intro.md": "doc\n",
        },
    )


# ---------------------------------------------------------------------------
# Repo-path resolution and basic build
# ---------------------------------------------------------------------------


class TestRepoPathResolution:
    def test_missing_project_raises(self, tmp_path):
        with path_snapshot_db(tmp_path, None, project_id=None) as conn:
            with pytest.raises(LookupError, match="project 'ghost' not found"):
                build_head_snapshot(conn, "ghost")

    def test_unreadable_repo_path_raises(self, tmp_path):
        with path_snapshot_db(tmp_path, tmp_path / "missing") as conn:
            with pytest.raises(PathSnapshotError, match="not a"):
                build_head_snapshot(conn, "demo")


class TestBuildHeadSnapshot:
    def test_creates_snapshot_with_committed_files(self, small_repo):
        with path_snapshot_db(small_repo.parent, small_repo) as conn:
            snap_id = build_head_snapshot(conn, "demo")
            p = _p(conn)
            paths = {
                r[0] for r in conn.execute(
                    "SELECT path_string FROM path_targets t "
                    "JOIN path_snapshot_entries e ON e.target_id = t.id "
                    f"WHERE e.snapshot_id = {p} AND t.kind = 'file'",
                    (snap_id,),
                ).fetchall()
            }
            assert paths == {
                "README.md",
                "src/a.py",
                "src/sub/b.py",
                "docs/intro.md",
            }

    def test_directories_chain_to_root_sentinel(self, small_repo):
        with path_snapshot_db(small_repo.parent, small_repo) as conn:
            build_head_snapshot(conn, "demo")
            leaf = target_at(conn, "demo", "src/sub/b.py")
            assert leaf is not None
            chain = ancestors_of(conn, leaf)
            # Walk from b.py up: src/sub → src → root.
            chain_paths = [
                conn.execute(
                    f"SELECT path_string FROM path_targets WHERE id = {_p(conn)}",
                    (tid,),
                ).fetchone()[0]
                for tid in chain
            ]
            assert chain_paths == ["src/sub", "src", ROOT_PATH_SENTINEL]

    def test_root_has_null_parent(self, small_repo):
        with path_snapshot_db(small_repo.parent, small_repo) as conn:
            build_head_snapshot(conn, "demo")
            root = target_at(conn, "demo", ROOT_PATH_SENTINEL)
            assert root is not None
            p = _p(conn)
            row = conn.execute(
                f"SELECT parent_target_id FROM path_targets WHERE id = {p}",
                (root,),
            ).fetchone()
            assert row[0] is None

    def test_whole_repo_identity_matches_git_ls_tree(self, small_repo):
        # AC-4 + AC-23: every committed path at HEAD plus derived parent
        # directories has a path_target row.
        with path_snapshot_db(small_repo.parent, small_repo) as conn:
            snap_id = build_head_snapshot(conn, "demo")
            git_files = sorted(
                line for line in subprocess.run(
                    ["git", "-C", str(small_repo),
                     "ls-tree", "-r", "--name-only", "HEAD"],
                    check=True, capture_output=True, text=True,
                ).stdout.splitlines() if line
            )
            p = _p(conn)
            registered_files = sorted(
                r[0] for r in conn.execute(
                    "SELECT path_string FROM path_targets t "
                    "JOIN path_snapshot_entries e ON e.target_id = t.id "
                    f"WHERE e.snapshot_id = {p} AND t.kind = 'file'",
                    (snap_id,),
                ).fetchall()
            )
            assert git_files == registered_files


# ---------------------------------------------------------------------------
# Idempotency and atomicity
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_rerun_same_head_returns_same_snapshot_id(self, small_repo):
        with path_snapshot_db(small_repo.parent, small_repo) as conn:
            first = build_head_snapshot(conn, "demo")
            second = build_head_snapshot(conn, "demo")
            assert first == second

    def test_rerun_does_not_duplicate_targets_or_entries(self, small_repo):
        with path_snapshot_db(small_repo.parent, small_repo) as conn:
            build_head_snapshot(conn, "demo")
            t1 = conn.execute(
                "SELECT COUNT(*) FROM path_targets"
            ).fetchone()[0]
            e1 = conn.execute(
                "SELECT COUNT(*) FROM path_snapshot_entries"
            ).fetchone()[0]
            s1 = conn.execute(
                "SELECT COUNT(*) FROM path_snapshots"
            ).fetchone()[0]
            build_head_snapshot(conn, "demo")
            t2 = conn.execute(
                "SELECT COUNT(*) FROM path_targets"
            ).fetchone()[0]
            e2 = conn.execute(
                "SELECT COUNT(*) FROM path_snapshot_entries"
            ).fetchone()[0]
            s2 = conn.execute(
                "SELECT COUNT(*) FROM path_snapshots"
            ).fetchone()[0]
            assert (t1, e1, s1) == (t2, e2, s2)

    def test_atomic_rollback_on_failure(self, small_repo, monkeypatch):
        with path_snapshot_db(small_repo.parent, small_repo) as conn:
            from yoke_core.domain import path_snapshots as ps

            def boom(*_args, **_kwargs):
                raise RuntimeError("simulated mid-build failure")

            monkeypatch.setattr(ps, "_walk_head_files", boom)
            with pytest.raises(RuntimeError, match="simulated"):
                build_head_snapshot(conn, "demo")
            # No partial state: nothing should have been minted.
            assert conn.execute(
                "SELECT COUNT(*) FROM path_targets"
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM path_snapshots"
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM path_snapshot_entries"
            ).fetchone()[0] == 0
