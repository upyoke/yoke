"""Stored organization settings converge after message reinjection retirement."""

from __future__ import annotations

import importlib
import json
import sqlite3


migration = importlib.import_module(
    "yoke_core.domain.migrations.0025_remove_message_reinjection_policy"
)


def test_migration_removes_only_the_retired_fleet_override() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE organizations (id INTEGER PRIMARY KEY, settings TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO organizations(id,settings) VALUES(1,?)",
        (
            json.dumps(
                {
                    "fleet": {
                        "reinject_until_acknowledged": False,
                        "wake_after_idle_seconds": 120,
                    }
                }
            ),
        ),
    )
    conn.execute(
        "INSERT INTO organizations(id,settings) VALUES(2,?)",
        (json.dumps({"fleet": {"reinject_until_acknowledged": True}}),),
    )

    migration.apply(conn)
    migration.invariants(conn)

    first = json.loads(
        conn.execute("SELECT settings FROM organizations WHERE id=1").fetchone()[0]
    )
    second = json.loads(
        conn.execute("SELECT settings FROM organizations WHERE id=2").fetchone()[0]
    )
    assert first == {"fleet": {"wake_after_idle_seconds": 120}}
    assert second == {}
