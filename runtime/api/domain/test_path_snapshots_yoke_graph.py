"""Yoke-repo population and traversal checks for path snapshots."""

from __future__ import annotations

import shutil
import statistics
import subprocess
import time
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain._path_snapshots_test_helpers import path_snapshot_db
from yoke_core.domain.path_registry import (
    ROOT_PATH_SENTINEL,
    ancestors_of,
    descendants_of,
    target_at,
)
from yoke_core.domain.path_snapshots import build_head_snapshot


GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS = 0.002


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _yoke_repo_root() -> Path | None:
    here = Path(__file__).resolve()
    candidate = here
    while candidate != candidate.parent:
        if (candidate / ".git").exists():
            return candidate
        candidate = candidate.parent
    return None


@pytest.fixture(scope="module")
def populated_yoke_db(tmp_path_factory: pytest.TempPathFactory):
    root = _yoke_repo_root()
    if root is None or shutil.which("git") is None:
        pytest.skip("no git checkout available for Yoke-repo perf test")
    tmp_path = tmp_path_factory.mktemp("path-snapshots-yoke")
    with path_snapshot_db(tmp_path, root, project_id="yoke") as conn:
        build_head_snapshot(conn, "yoke")
        yield conn, root


class TestYokePopulatedGraph:
    def test_every_committed_file_has_identity(self, populated_yoke_db):
        conn, root = populated_yoke_db
        files = subprocess.run(
            ["git", "-C", str(root),
             "ls-tree", "-r", "--name-only", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        for fp in files:
            if not fp:
                continue
            tid = target_at(conn, 1, fp)
            assert tid is not None, (
                f"file {fp!r} missing from path_targets"
            )

    def test_ancestor_query_is_low_latency(self, populated_yoke_db):
        conn, _root = populated_yoke_db
        row = conn.execute(
            "SELECT id FROM path_targets WHERE kind = 'file' "
            "ORDER BY length(path_string) - "
            "length(replace(path_string, '/', '')) DESC, "
            "length(path_string) DESC LIMIT 1"
        ).fetchone()
        assert row is not None, "no committed file in registry"
        leaf = int(row[0])
        durations = []
        for _ in range(100):
            t0 = time.perf_counter()
            ancestors_of(conn, leaf)
            durations.append(time.perf_counter() - t0)
        median = statistics.median(durations)
        assert median < GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS, (
            f"median ancestor query {median * 1000:.3f}ms exceeds "
            f"{GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS * 1000:.1f}ms"
        )

    def test_descendants_query_is_low_latency_on_subtree(
        self, populated_yoke_db
    ):
        conn, _root = populated_yoke_db
        p = _p(conn)
        row = conn.execute(
            "SELECT id FROM path_targets "
            f"WHERE kind = 'directory' AND path_string <> {p} "
            "ORDER BY (length(path_string) - "
            "length(replace(path_string, '/', ''))) DESC, "
            "length(path_string) DESC LIMIT 1",
            (ROOT_PATH_SENTINEL,),
        ).fetchone()
        assert row is not None, "no directory targets to traverse"
        sub = int(row[0])
        durations = []
        for _ in range(50):
            t0 = time.perf_counter()
            descendants_of(conn, sub)
            durations.append(time.perf_counter() - t0)
        median = statistics.median(durations)
        assert median < GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS, (
            f"median descendants query {median * 1000:.3f}ms exceeds "
            f"{GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS * 1000:.1f}ms"
        )
