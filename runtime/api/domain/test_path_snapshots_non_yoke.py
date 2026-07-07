"""AC-29 — non-`yoke` project coverage for the path-snapshot bootstrap.

The Yoke-repo graph fixture in
:mod:`runtime.api.domain.test_path_snapshots_yoke_graph` exercises a
single project end-to-end. This sibling file builds an ephemeral
non-`yoke` repo on disk, binds it through the machine-local checkout
map, and asserts the bootstrap succeeds against it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain._path_snapshots_test_helpers import path_snapshot_db
from yoke_core.domain.path_registry import target_at
from yoke_core.domain.path_snapshots import build_head_snapshot


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_id(conn, slug: str) -> int:
    row = conn.execute(
        f"SELECT id FROM projects WHERE slug={_p(conn)}",
        (slug,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    )


@pytest.fixture
def fake_project(tmp_path: Path):
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    repo = tmp_path / "fake-non-yoke-repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("# main\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_main.py").write_text("# tests\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.fixture
def conn_with_project(tmp_path: Path, fake_project: Path):
    with path_snapshot_db(tmp_path, fake_project, project_id="alt") as conn:
        yield conn


def test_bootstrap_against_non_yoke_repo(conn_with_project, fake_project):
    """The bootstrap mints path_targets and a snapshot for a project
    whose id is not 'yoke' and whose checkout lives outside the
    Yoke tree. This is the regression coverage AC-29 demands."""
    snap_id = build_head_snapshot(conn_with_project, "alt")
    assert isinstance(snap_id, int)
    project_id = _project_id(conn_with_project, "alt")

    project_targets = conn_with_project.execute(
        f"SELECT COUNT(*) FROM path_targets WHERE project_id={_p(conn_with_project)}",
        (project_id,),
    ).fetchone()[0]
    # Three files committed (README.md, src/main.py, tests/test_main.py)
    # plus directory targets (src, tests, root sentinel) — at least 6.
    assert project_targets >= 6

    p = _p(conn_with_project)
    snapshot_entries = conn_with_project.execute(
        f"SELECT COUNT(*) FROM path_snapshot_entries WHERE snapshot_id={p}",
        (snap_id,),
    ).fetchone()[0]
    assert snapshot_entries == project_targets

    # Files we wrote should have identity rows.
    for path_string in ("README.md", "src/main.py", "tests/test_main.py"):
        target_id = target_at(conn_with_project, "alt", path_string)
        assert target_id is not None, (
            f"non-yoke project file {path_string!r} missing identity"
        )


def test_bootstrap_is_idempotent_for_non_yoke(conn_with_project):
    """Re-running the bootstrap against the same HEAD must produce no
    additional snapshot rows — the project is bound to a single
    HEAD-pinned snapshot until git advances."""
    a = build_head_snapshot(conn_with_project, "alt")
    b = build_head_snapshot(conn_with_project, "alt")
    assert a == b
    project_id = _project_id(conn_with_project, "alt")
    snapshots = conn_with_project.execute(
        f"SELECT COUNT(*) FROM path_snapshots WHERE project_id={_p(conn_with_project)}",
        (project_id,),
    ).fetchone()[0]
    assert snapshots == 1
