"""Measure changed-HEAD context work with a declared architecture map."""

import logging
from time import perf_counter

from runtime.api.domain.test_architecture_path_context_seed import (
    _model, _snapshot_with, _write_model,
)
from runtime.api.path_context_test_helpers import init_minimal_schema
from yoke_core.domain.project_snapshot_head_refresh import refresh_after_head_change


class CountingConnection:
    def __init__(self, conn):
        self.conn = conn
        self.statements = 0

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, *args, **kwargs):
        self.statements += 1
        return self.conn.execute(*args, **kwargs)


def test_changed_head_refresh_cost(tmp_path, caplog):
    conn = init_minimal_schema(str(tmp_path / "timing.db"))
    try:
        _write_model(conn, _model())
        _snapshot_with(conn, [f"src/billing/file_{i}.py" for i in range(200)])
        counted = CountingConnection(conn)
        with caplog.at_level(logging.INFO):
            start = perf_counter()
            result = refresh_after_head_change(
                counted, 1, [{"ref": "HEAD", "commit_sha": "new", "snapshot_id": 1}],
                [], previous_head="old",
            )
            elapsed = perf_counter() - start
        assert result["architecture_refresh"]["layer_rows"] == 200
        assert counted.statements < 40
        assert sum("snapshot_head_refresh" in r.message for r in caplog.records) == 3
        print(f"refresh_seconds={elapsed:.3f} statements={counted.statements}")
        print(caplog.text)
    finally:
        conn.close()
