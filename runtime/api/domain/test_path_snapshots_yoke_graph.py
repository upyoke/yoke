"""Synthetic large-tree traversal checks for path snapshots."""

from __future__ import annotations

import statistics
import time

import pytest

from yoke_core.domain import db_backend
from runtime.api.domain._path_snapshots_test_helpers import path_snapshot_db
from yoke_core.domain.path_registry import (
    ROOT_PATH_SENTINEL,
    ancestors_of,
    descendants_of,
)
from runtime.api.domain._path_snapshots_test_helpers import NOW


# Shared workers add scheduler jitter to microbenchmarks; this keeps the
# regression guard tight without treating the host as a calibrated benchmark.
# 3ms failed on a loaded CI shard at 3.012ms median; 10ms still flags a
# real traversal regression.
GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS = 0.010


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# 20,000 files in 200 subtrees, each eight directories deep: 21,601 rows.
FILE_COUNT = 20_000
TREE_COUNT = 200
TREE_DEPTH = 8
GRAPH_ROW_COUNT = 1 + TREE_COUNT * TREE_DEPTH + FILE_COUNT


@pytest.fixture(scope="module")
def populated_graph(tmp_path_factory: pytest.TempPathFactory):
    tmp_path = tmp_path_factory.mktemp("path-snapshots-synthetic")
    with path_snapshot_db(tmp_path, tmp_path, project_id="yoke") as conn:
        rows = [(1, 1, "directory", ROOT_PATH_SENTINEL, 1, None, NOW)]
        for tree in range(TREE_COUNT):
            parent, path = 1, ""
            for depth in range(TREE_DEPTH):
                path += ("/" if path else "") + f"tree{tree}_level{depth}"
                row_id = len(rows) + 1
                rows.append((row_id, 1, "directory", path, 1, parent, NOW))
                parent = row_id
            for file in range(FILE_COUNT // TREE_COUNT):
                rows.append(
                    (len(rows) + 1, 1, "file", f"{path}/f{file}", 1, parent, NOW)
                )
        p = _p(conn)
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO path_targets (id, project_id, kind, path_string, "
                "generation, parent_target_id, created_at) VALUES ("
                + ", ".join([p] * 7)
                + ")",
                rows,
            )
        conn.commit()
        assert conn.execute("SELECT count(*) FROM path_targets").fetchone()[0] == (
            GRAPH_ROW_COUNT
        )
        conn.execute("ANALYZE path_targets")
        yield conn


class TestSyntheticPopulatedGraph:
    def test_ancestor_query_is_low_latency(self, populated_graph):
        conn = populated_graph
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
            assert len(ancestors_of(conn, leaf)) == TREE_DEPTH + 1
            durations.append(time.perf_counter() - t0)
        median = statistics.median(durations)
        assert median < GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS, (
            f"median ancestor query {median * 1000:.3f}ms exceeds "
            f"{GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS * 1000:.1f}ms"
        )

    def test_descendants_query_is_low_latency_on_subtree(self, populated_graph):
        conn = populated_graph
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
            assert len(descendants_of(conn, sub)) == FILE_COUNT // TREE_COUNT
            durations.append(time.perf_counter() - t0)
        median = statistics.median(durations)
        assert median < GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS, (
            f"median descendants query {median * 1000:.3f}ms exceeds "
            f"{GRAPH_TRAVERSAL_MEDIAN_BUDGET_SECONDS * 1000:.1f}ms"
        )
