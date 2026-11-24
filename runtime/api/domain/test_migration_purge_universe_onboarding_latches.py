"""Onboarding cleanup preserves owned history and replays without changes."""

from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module

UNIVERSE_KEYS = (
    "finish_installation_wizard", "connect_harness", "first_deploy", "run_onboard",
)
MACHINE_IDS = ("live", "retired", "orphan")


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_purge_keeps_run_onboard_and_owned_machine_history(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TEMP TABLE machines (machine_id TEXT PRIMARY KEY, retired_at TEXT)"
    )
    conn.execute("INSERT INTO machines VALUES ('live', NULL), ('retired', '2026-08-01')")
    conn.execute(
        "CREATE TEMP TABLE overview_activation_facts (module_key TEXT, activated_at TEXT)"
    )
    conn.execute(
        "CREATE TEMP TABLE overview_machine_activation_facts "
        "(machine_id TEXT, module_key TEXT, activated_at TEXT)"
    )
    for index, key in enumerate(UNIVERSE_KEYS, start=1):
        conn.execute(
            "INSERT INTO overview_activation_facts "
            f"VALUES ('{key}', '2026-09-0{index}')"
        )
    for index, machine_id in enumerate(MACHINE_IDS, start=1):
        conn.execute(
            "INSERT INTO overview_machine_activation_facts "
            f"VALUES ('{machine_id}', 'connect_harness', '2026-08-0{index}')"
        )

    path = Path(migrations.__file__).parent / "0123_purge_universe_onboarding_latches.py"
    module = load_migration_module(path, path.stem)
    assert module.MINIMUM_SERVING_VERSION == "next-release"

    for _ in range(2):
        module.apply(conn)
        universe = conn.execute(
            "SELECT module_key, activated_at FROM overview_activation_facts"
        ).fetchall()
        machines = conn.execute(
            "SELECT machine_id, module_key, activated_at "
            "FROM overview_machine_activation_facts ORDER BY machine_id"
        ).fetchall()
        assert [tuple(row) for row in universe] == [("run_onboard", "2026-09-04")]
        assert [tuple(row) for row in machines] == [
            ("live", "connect_harness", "2026-08-01"),
            ("retired", "connect_harness", "2026-08-02"),
        ]
