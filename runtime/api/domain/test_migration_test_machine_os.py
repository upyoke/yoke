"""OS settings convergence accepts both historical shapes and its own output."""

from __future__ import annotations

import importlib
import json
import sqlite3
import pytest

MIGRATION = importlib.import_module("yoke_core.domain.migrations.0050_test_machine_os")


def database(*documents):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE project_capabilities (id INTEGER PRIMARY KEY, type TEXT, settings TEXT)"
    )
    for number, extra in enumerate(documents):
        name = f"lab-{number}"
        settings = {
            "resource_name": name,
            "host": "lab.invalid",
            "user": "tester",
            "operating_notes": "",
            **extra,
        }
        conn.execute(
            "INSERT INTO project_capabilities(type, settings) VALUES(?, ?)",
            ("test-machine:" + name, json.dumps(settings)),
        )
    return conn


def test_convergence_covers_legacy_removed_history_and_already_published_linux():
    conn = database({"host_kind": "mac-ssh"}, {}, {"os": "linux"}, {"os": "macos"})
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
    first = [
        tuple(row)
        for row in conn.execute(
            "SELECT id,type,settings FROM project_capabilities ORDER BY id"
        )
    ]
    assert [json.loads(row[2])["os"] for row in first] == [
        "macos",
        "macos",
        "linux",
        "macos",
    ]
    assert all("host_kind" not in json.loads(row[2]) for row in first)
    MIGRATION.apply(conn)
    assert first == [
        tuple(row)
        for row in conn.execute(
            "SELECT id,type,settings FROM project_capabilities ORDER BY id"
        )
    ]


def test_invalid_settings_refuse_before_rewriting_any_row():
    conn = database({}, {"os": "windows"})
    before = list(conn.execute("SELECT settings FROM project_capabilities"))
    with pytest.raises(
        AssertionError, match="test_machine_os_convergence_refused.*one of macos, linux"
    ):
        MIGRATION.apply(conn)
    assert before == list(conn.execute("SELECT settings FROM project_capabilities"))


def test_rewrite_declares_the_serving_build_floor():
    assert MIGRATION.MINIMUM_SERVING_VERSION == "next-release"
