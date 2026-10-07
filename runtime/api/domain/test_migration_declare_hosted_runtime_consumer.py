"""The former hosted-runtime bridge converges into a declared consumer."""

import importlib
import json
import sqlite3

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0058_declare_hosted_runtime_consumer"
)


def database(environments, *, consumer_org=1):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, org_id INTEGER);"
        "CREATE TABLE sites (id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT);"
        "CREATE TABLE environments (id INTEGER PRIMARY KEY, site INTEGER, settings TEXT);"
    )
    conn.execute("INSERT INTO projects VALUES (1, 'yoke', ?)", (consumer_org,))
    conn.execute("INSERT INTO projects VALUES (3, 'platform', 1)")
    conn.execute("INSERT INTO sites VALUES (10, 3, 'Yoke API')")
    conn.execute("INSERT INTO sites VALUES (11, 1, 'yoke')")
    for env_id, site, settings in environments:
        conn.execute(
            "INSERT INTO environments VALUES (?, ?, ?)",
            (env_id, site, json.dumps(settings)),
        )
    return conn


def stored(conn, env_id):
    row = conn.execute(
        "SELECT settings FROM environments WHERE id = ?", (env_id,)
    ).fetchone()
    return json.loads(row[0])


def test_hosted_runtime_on_the_shared_site_declares_its_consumer():
    conn = database(
        [
            (1, 10, {"qa": {"hosted_runtime": True}, "hosts": {"api": "x"}}),
            (2, 11, {"qa": {"hosted_runtime": True}}),
            (3, 10, {"qa": {"hosted_runtime": False}}),
        ]
    )

    MIGRATION.apply(conn)

    assert stored(conn, 1) == {
        "qa": {"hosted_runtime": True, "hosted_runtime_consumer": "yoke"},
        "hosts": {"api": "x"},
    }
    assert stored(conn, 2) == {"qa": {"hosted_runtime": True}}
    assert stored(conn, 3) == {"qa": {"hosted_runtime": False}}


def test_existing_declaration_is_kept_and_reapplying_is_a_no_op():
    conn = database(
        [(1, 10, {"qa": {"hosted_runtime": True, "hosted_runtime_consumer": "other"}})]
    )

    before = conn.total_changes
    MIGRATION.apply(conn)

    assert conn.total_changes == before
    assert stored(conn, 1)["qa"]["hosted_runtime_consumer"] == "other"


def test_consumer_in_another_organization_is_not_declared():
    conn = database([(1, 10, {"qa": {"hosted_runtime": True}})], consumer_org=2)

    MIGRATION.apply(conn)

    assert "hosted_runtime_consumer" not in stored(conn, 1)["qa"]
