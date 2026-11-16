"""Migration 0110 renames stored WSL-backed Test Machines to os wsl."""

import json
from pathlib import Path
import sqlite3

import pytest

from yoke_contracts.machine_config.test_machine import validate_test_machine_settings
from yoke_core.domain.migration_history import load_migration_module

_WINDOWS_LAB = {
    "resource_name": "windows-lab", "host": "54.236.107.83", "user": "Administrator",
    "os": "windows", "operating_notes": "WSL2 Ubuntu",
    "cloud_instance_id": "i-07b658cc018669344",
}
_LINUX_LAB = {
    "resource_name": "linux-lab", "host": "100.53.45.66", "user": "yoketest",
    "os": "linux", "operating_notes": "",
}


def _apply(conn) -> None:
    from yoke_core.domain import migrations

    path = Path(migrations.__file__).parent / "0110_wsl_test_machine_os.py"
    load_migration_module(path, path.stem).apply(conn)


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_windows_test_machines_become_wsl_and_others_stay(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TEMP TABLE project_capabilities (id INTEGER, type TEXT, settings TEXT)"
    )
    rows = (
        (1, "test-machine:windows-lab", json.dumps(_WINDOWS_LAB)),
        (2, "test-machine:linux-lab", json.dumps(_LINUX_LAB)),
        (3, "github", json.dumps({"os": "windows"})),
    )
    for row in rows:
        conn.execute(
            "INSERT INTO project_capabilities VALUES "
            f"({row[0]}, '{row[1]}', '{row[2]}')"
        )

    _apply(conn)
    _apply(conn)

    stored = {
        row[0]: row[1]
        for row in conn.execute("SELECT id, settings FROM project_capabilities")
    }
    windows_lab = json.loads(stored[1])
    assert windows_lab == {**_WINDOWS_LAB, "os": "wsl"}
    assert validate_test_machine_settings(windows_lab)["os"] == "wsl"
    assert stored[1] == json.dumps(windows_lab, separators=(",", ":"), sort_keys=True)
    assert stored[2] == json.dumps(_LINUX_LAB)
    assert json.loads(stored[3]) == {"os": "windows"}
