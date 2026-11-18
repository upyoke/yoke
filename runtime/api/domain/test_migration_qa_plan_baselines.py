"""The baseline migration repairs authoring rows without changing QA history."""

from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module


def _migration():
    path = Path(migrations.__file__).parent / "0114_declare_legacy_qa_plan_baselines.py"
    return load_migration_module(path, path.stem)


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_legacy_heads_convert_and_only_recorded_retirements_are_restored(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    migration = _migration()
    conn.execute(
        "CREATE TEMP TABLE qa_plans(id INTEGER, retired_at TEXT, retired_by_actor_id "
        "INTEGER, retirement_reason TEXT, updated_at TIMESTAMP)"
    )
    conn.execute(
        "CREATE TEMP TABLE qa_plan_cases(id INTEGER, plan_id INTEGER, position INTEGER, "
        "case_key TEXT, method_id TEXT, method_config TEXT, entry_surface TEXT, "
        "host_baselines TEXT, starting_state TEXT, starting_state_reason TEXT, "
        "updated_at TIMESTAMP)"
    )
    conn.execute(
        "CREATE TEMP TABLE qa_methods(id TEXT, runner_id TEXT, required_capability_kinds TEXT)"
    )
    conn.execute("CREATE TEMP TABLE qa_runs(id INTEGER, historical_start TEXT)")
    conn.execute("INSERT INTO qa_runs VALUES (35,'as_is')")
    conn.execute(
        "INSERT INTO qa_methods VALUES ('mission','agent_mission','[]'),"
        "('machine','host_control','[]'),('command','worktree_run','[]')"
    )
    marker = "%s" if backend == "postgres" else "?"
    for plan_id, reason in enumerate((*migration._RETIREMENT_REASONS, "independent retirement"), 1):
        conn.execute(
            f"INSERT INTO qa_plans VALUES ({marker},'retired',2,{marker},NULL)",
            (plan_id, reason),
        )
    conn.execute(
        "INSERT INTO qa_plan_cases VALUES "
        """(1,1,1,'browser','mission','{"test_machine":"lab","browser_identities":["operator"]}',NULL,'[]','as_is','old',NULL),"""
        """(2,1,2,'clean-host','machine','{}',NULL,'[]','as_is','old',NULL),"""
        """(3,2,1,'prepare','machine','{}',NULL,'[]','as_is','old',NULL),"""
        """(4,2,2,'verify','machine','{"command":"yoke status"}',NULL,'[]','inherit',NULL,NULL),"""
        """(5,3,1,'controller','command','{}',NULL,'[]','as_is','obsolete',NULL),"""
        """(6,3,2,'host-command','command','{"test_machine":"lab","command":"yoke browser authorize --test-machine lab"}',NULL,'[]',NULL,NULL,NULL),"""
        """(7,3,3,'old-fresh-browser','mission','{"test_machine":"lab","browser_identities":["operator"]}',NULL,'["fresh-host"]','baseline',NULL,NULL)"""
    )

    migration.apply(conn)
    migration.apply(conn)
    migration.invariants(conn)

    assert conn.execute(
        "SELECT host_baselines,starting_state,starting_state_reason FROM qa_plan_cases ORDER BY id"
    ).fetchall() == [
        ('["shell-preconfigured"]', "baseline", None),
        ('["fresh-host"]', "baseline", None),
        ('["shell-preconfigured"]', "baseline", None),
        ("[]", "inherit", None),
        ("[]", None, None),
        ('["shell-preconfigured"]', "baseline", None),
        ('["shell-preconfigured"]', "baseline", None),
    ]
    assert conn.execute(
        "SELECT retired_at,retired_by_actor_id,retirement_reason FROM qa_plans ORDER BY id"
    ).fetchall() == [(None, None, None), (None, None, None), ("retired", 2, "independent retirement")]
    assert conn.execute("SELECT historical_start FROM qa_runs").fetchone() == ("as_is",)
