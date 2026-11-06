# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import sqlite3

from yoke_core.domain.deployment_run_history_read import (
    RUN_HISTORY_FIELDS,
    RunHistoryCursorError,
    decode_cursor,
    read_deployment_run_history,
)

from yoke_core.domain.deployment_run_list_read import present_deployment_runs

from yoke_core.domain.item_refs_schema import ensure_item_refs_view


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT, public_item_prefix TEXT
        );
        CREATE TABLE environments (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY, project_id INTEGER, name TEXT, stages TEXT
        );
        CREATE TABLE deployment_runs (
            id TEXT PRIMARY KEY, project_id INTEGER, flow TEXT,
            target_tier TEXT, target_environment_id INTEGER, status TEXT,
            current_stage TEXT, created_at TEXT, started_at TEXT,
            completed_at TEXT, carried_work TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT,
            status TEXT, project_sequence INTEGER
        );
        CREATE TABLE deployment_run_items (
            run_id TEXT, item_id INTEGER, added_at TEXT
        );
        INSERT INTO projects VALUES (1, 'visible', 'VIS');
        INSERT INTO projects VALUES (2, 'hidden', 'HID');
        INSERT INTO environments VALUES (1, 'prod'), (2, 'stage');
        INSERT INTO deployment_flows VALUES
            ('release', 1, 'Release', '["build","deploy"]'),
            ('hidden-release', 2, 'Hidden release', '["build"]');
        INSERT INTO items VALUES
            (1, 1, 'Visible rollout', 'done', 17),
            (2, 2, 'Secret migration', 'done', 99);
    """)
    for number in range(53):
        run_id = f"run-20260908-{number:03d}"
        created = (
            "2026-09-08T12:00:00.000000Z"
            if number >= 50
            else (f"2026-09-08T11:{number:02d}:00Z")
        )
        status = ("succeeded", "failed", "cancelled")[number % 3]
        conn.execute(
            "INSERT INTO deployment_runs VALUES (?, 1, 'release', "
            "'persistent', 1, ?, 'complete', ?, ?, ?, ?)",
            (run_id, status, created, created, created, '{"large":"unused"}'),
        )
    conn.execute(
        "INSERT INTO deployment_runs VALUES "
        "('run-live-1', 1, 'release', 'persistent', 1, 'executing', "
        "'deploy', '2026-09-08T13:00:00.000000Z', NULL, NULL, '{}')"
    )
    conn.execute(
        "INSERT INTO deployment_runs VALUES "
        "('run-live-2', 1, 'release', 'persistent', 2, 'created', "
        "'build', '2026-09-08T12:59:00.000000Z', NULL, NULL, '{}')"
    )
    conn.execute(
        "INSERT INTO deployment_runs VALUES "
        "('run-hidden', 2, 'hidden-release', 'persistent', 1, 'failed', "
        "'build', '2026-09-08T14:00:00.000000Z', NULL, NULL, '{}')"
    )
    conn.execute(
        "INSERT INTO deployment_run_items VALUES "
        "('run-20260908-052', 1, '2026-09-08T12:00:00.000000Z'), ('run-live-1', 2, '2026-09-08T12:00:00.000000Z')"
    )
    conn.execute(
        "UPDATE deployment_flows SET stages = ? WHERE id = 'release'",
        (
            '[{"name":"merged"},{"name":"hosted-release"},'
            '{"name":"warm-up"},{"name":"complete"}]',
        ),
    )
    conn.execute(
        "UPDATE deployment_runs SET carried_work = ? WHERE id = ?",
        (
            '{"schema":1,"items":[{"item_id":3207,"ref":"YOK-3080",'
            '"commit_shas":["308ead240af24a12ac1090ce29dc7f69bab48521"]}],'
            '"commits":[],"derivation":{"reason":"complete","status":"derived"}}',
            "run-20260908-051",
        ),
    )
    ensure_item_refs_view(conn)
    conn.commit()
    return conn


def _read(conn, **overrides):
    options = {
        "project_ids": [1],
        "search": None,
        "status": None,
        "environment": None,
        "flow": None,
        "page_size": 50,
        "cursor": None,
        "actor_id": 7,
    }
    options.update(overrides)
    return read_deployment_run_history(conn, **options)
