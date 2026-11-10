"""Exercise the actual previous-release SQL, including nullable environments."""

from pathlib import Path

import pytest

from yoke_core.domain.deployment_run_carried_work import (
    previous_release_run,
    prospective_previous_release,
)
from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module


class ObservedConnection:
    def __init__(self, conn):
        self.conn = conn
        self.plan = ""

    def execute(self, sql, params):
        self.plan = "\n".join(
            row[0] for row in self.conn.execute("EXPLAIN " + sql, params)
        )
        return self.conn.execute(sql, params)


@pytest.fixture
def release_history(test_db):
    # Use the shipped index definition on a realistic history distribution.
    # A temporary table isolates the fixture from production schema constraints.
    path = Path(migrations.__file__).parent / "0107_session_polling_indexes.py"
    load_migration_module(path, path.stem).apply(test_db)
    index = test_db.execute(
        "SELECT pg_get_indexdef(indexrelid) FROM pg_index "
        "WHERE indexrelid='idx_deployment_runs_project_environment_status'::regclass"
    ).fetchone()[0]
    test_db.execute(
        "CREATE TEMP TABLE deployment_runs (id TEXT PRIMARY KEY,project_id INTEGER,"
        "target_environment_id INTEGER,status TEXT,created_at TIMESTAMPTZ,"
        "completed_at TIMESTAMPTZ,release_lineage TEXT,bound_sources TEXT)"
    )
    test_db.execute(index.replace("public.deployment_runs", "deployment_runs"))
    test_db.execute(
        "INSERT INTO deployment_runs SELECT 'old-'||n,1,"
        "CASE WHEN n%4=0 THEN NULL ELSE n%4 END,'succeeded',"
        "'2020-01-01'::timestamptz + n*interval '1 minute',"
        "'2020-01-01'::timestamptz + n*interval '1 minute','old','{}' "
        "FROM generate_series(1,2000) n"
    )
    # Equal completion timestamps must retain created_at and id tie-breakers;
    # null completion remains last, regardless of a newer creation timestamp.
    for env in (None, 1):
        for suffix, created, completed, status, project in (
            ("a", "2025-01-01", "2025-01-02", "succeeded", 1),
            ("b", "2025-01-01", "2025-01-02", "succeeded", 1),
            ("c", "2025-01-01 12:00", "2025-01-02", "succeeded", 1),
            ("self", "2026-01-01", "2026-01-02", "succeeded", 1),
            ("unfinished", "2027-01-01", None, "succeeded", 1),
            ("failed", "2027-01-01", "2027-01-02", "failed", 1),
            ("other-project", "2027-01-01", "2027-01-02", "succeeded", 2),
        ):
            test_db.execute(
                "INSERT INTO deployment_runs VALUES (%s,%s,%s,%s,%s,%s,'new','{}')",
                (f"{env}-{suffix}", project, env, status, created, completed),
            )
    test_db.execute("ANALYZE deployment_runs")
    return test_db


@pytest.mark.parametrize("environment_id", [None, 1])
def test_actual_previous_release_query_is_indexed_and_preserves_order(
    release_history, environment_id
):
    conn = ObservedConnection(release_history)
    run_id = f"{environment_id}-self"
    expected = release_history.execute(
        "SELECT id FROM deployment_runs WHERE project_id=1 AND status='succeeded' "
        "AND id<>%s AND target_environment_id IS NOT DISTINCT FROM %s "
        "ORDER BY completed_at DESC NULLS LAST,created_at DESC,id DESC LIMIT 1",
        (run_id, environment_id),
    ).fetchone()[0]
    row = previous_release_run(conn, run_id, 1, environment_id)
    assert row["id"] == expected == f"{environment_id}-c"
    # The regression is the concrete environment lookup. Null environment
    # history is a broad cohort here; its plan is cost-based, its result exact.
    if environment_id is not None:
        assert "idx_deployment_runs_project_environment_status" in conn.plan, conn.plan
        assert "Seq Scan" not in conn.plan, conn.plan
    release_history.execute("DELETE FROM deployment_runs WHERE id=%s", (expected,))
    assert (
        previous_release_run(conn, run_id, 1, environment_id)["id"]
        == f"{environment_id}-b"
    )
    assert previous_release_run(conn, run_id, 1, 99) is None


def test_prospective_takeover_still_uses_explicit_previous_release(release_history):
    conn = ObservedConnection(release_history)
    with prospective_previous_release(conn, "current", "1-a"):
        row = previous_release_run(conn, "current", 1, None)
    assert row["id"] == "1-a"
    assert "deployment_runs_pkey" in conn.plan, conn.plan
