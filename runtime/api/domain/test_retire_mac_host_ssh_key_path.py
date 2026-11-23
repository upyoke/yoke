"""Migration 0121 removes the retired Mac-host key path from every server."""

import json
from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain.migration_history import load_migration_module

_BEFORE = {
    "database": {"location": "box"},
    "servers": [
        {
            "ssh_key_path": "~/.ssh/acme",
            "mac_host": "testy@mini",
            "mac_host_ssh_key_path": "~/.ssh/personal",
            "mac_host_key_fingerprint": "SHA256:K",
        },
        {"mac_host_ssh_key_path": "~/.ssh/other"},
        "not-a-server",
    ],
}
_AFTER = {
    "database": {"location": "box"},
    "servers": [
        {
            "ssh_key_path": "~/.ssh/acme",
            "mac_host": "testy@mini",
            "mac_host_key_fingerprint": "SHA256:K",
        },
        {},
        "not-a-server",
    ],
}
_UNTOUCHED = ['{"servers": "odd"}', "not json", '{"database": {}}']


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_removes_the_key_everywhere_and_replay_changes_nothing(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    conn.execute("CREATE TEMP TABLE environments (id INTEGER, settings TEXT)")
    conn.execute(f"INSERT INTO environments VALUES (1, '{json.dumps(_BEFORE)}')")
    for offset, raw in enumerate(_UNTOUCHED, start=2):
        conn.execute(f"INSERT INTO environments VALUES ({offset}, '{raw}')")
    from yoke_core.domain import migrations

    path = Path(migrations.__file__).parent / "0121_retire_mac_host_ssh_key_path.py"
    module = load_migration_module(path, path.stem)
    module.apply(conn)
    first = conn.execute("SELECT id, settings FROM environments ORDER BY id").fetchall()
    module.apply(conn)
    second = conn.execute("SELECT id, settings FROM environments ORDER BY id").fetchall()

    assert json.loads(first[0][1]) == _AFTER
    assert [tuple(row) for row in first] == [tuple(row) for row in second]
    assert [row[1] for row in first[1:]] == _UNTOUCHED
