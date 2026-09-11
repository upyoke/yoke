"""Compact, authorized deployment-run history paging."""

from __future__ import annotations

import sqlite3

from yoke_core.domain.deployment_run_history_read import (
    RUN_HISTORY_FIELDS,
    RunHistoryCursorError,
    decode_cursor,
    read_deployment_run_history,
)
from yoke_core.domain.deployment_run_list_read import present_deployment_runs


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
            "2026-09-08T12:00:00Z"
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
        "'deploy', '2026-09-08T13:00:00Z', '', '', '{}')"
    )
    conn.execute(
        "INSERT INTO deployment_runs VALUES "
        "('run-live-2', 1, 'release', 'persistent', 2, 'created', "
        "'build', '2026-09-08T12:59:00Z', '', '', '{}')"
    )
    conn.execute(
        "INSERT INTO deployment_runs VALUES "
        "('run-hidden', 2, 'hidden-release', 'persistent', 1, 'failed', "
        "'build', '2026-09-08T14:00:00Z', '', '', '{}')"
    )
    conn.execute(
        "INSERT INTO deployment_run_items VALUES "
        "('run-20260908-052', 1, ''), ('run-live-1', 2, '')"
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


def test_initial_and_following_pages_are_complete_stable_and_compact(monkeypatch):
    conn = _database()
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_history_read.present_deployment_runs",
        lambda _conn, rows, **_kwargs: rows,
    )
    first = _read(conn)
    second = _read(conn, cursor=first["next_cursor"])

    assert first["unfinished_count"] == 2
    assert first["completed_match_count"] == 53
    assert first["completed_loaded_count"] == 50
    assert len(first["rows"]) == 52
    assert first["next_cursor"]
    assert len(second["rows"]) == 5
    assert second["completed_loaded_count"] == 53
    assert second["next_cursor"] is None
    first_completed = {
        row["id"]
        for row in first["rows"]
        if row["status"] in {"cancelled", "failed", "succeeded"}
    }
    second_completed = {
        row["id"]
        for row in second["rows"]
        if row["status"] in {"cancelled", "failed", "succeeded"}
    }
    assert first_completed.isdisjoint(second_completed)
    assert len(first_completed | second_completed) == 53
    assert tuple(first["fields"]) == RUN_HISTORY_FIELDS
    assert {row["flow"] for row in first["rows"]} == {"release"}
    assert {row["flow_name"] for row in first["rows"]} == {"Release"}


def test_search_filters_counts_and_facets_before_paging(monkeypatch):
    conn = _database()
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_history_read.present_deployment_runs",
        lambda _conn, rows, **_kwargs: rows,
    )
    by_item = _read(conn, search="VIS-17")
    by_run = _read(conn, search="run-live", environment="prod")
    failed = _read(conn, status="failed", flow="release", page_size=5)

    assert [row["id"] for row in by_item["rows"]] == ["run-20260908-052"]
    assert [row["id"] for row in by_run["rows"]] == ["run-live-1"]
    assert by_run["unfinished_count"] == 1
    assert failed["unfinished_count"] == 0
    assert failed["completed_match_count"] == 18
    assert failed["completed_loaded_count"] == 5
    assert failed["filters"]["projects"] == [{"id": 1, "label": "visible"}]
    assert failed["filters"]["statuses"] == ["failed"]
    assert failed["filters"]["environments"] == ["prod"]
    assert failed["filters"]["flows"] == [{"id": "release", "label": "Release"}]
    assert "run-hidden" not in {row["id"] for row in failed["rows"]}


def test_hidden_member_cannot_make_visible_run_searchable(monkeypatch):
    conn = _database()
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_history_read.present_deployment_runs",
        lambda _conn, rows, **_kwargs: rows,
    )
    result = _read(conn, search="Secret migration")

    assert result["rows"] == []
    assert result["unfinished_count"] == 0
    assert result["completed_match_count"] == 0


def test_compact_presentation_keeps_only_rendered_member_and_stage_facts(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read._member_items",
        lambda *_args, **_kwargs: {
            "run-1": [
                {
                    "id": 99,
                    "ref": "VIS-17",
                    "title": "Visible rollout",
                    "status": "done",
                    "project_id": 1,
                    "project_sequence": 17,
                    "project": "visible",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read.run_gates",
        lambda *_args, **_kwargs: {"run-1": [{"kind": "approval"}]},
    )
    rows = present_deployment_runs(
        object(),
        [
            {
                "id": "run-1",
                "status": "executing",
                "current_stage": "deploy",
                "stages": '["build","deploy"]',
            }
        ],
        actor_id=7,
        visible_project_ids={1},
        include_carried_work=False,
        compact=True,
    )

    assert set(rows[0]["member_items"][0]) == {
        "ref",
        "title",
        "project_id",
        "project_sequence",
    }
    assert rows[0]["gates"] == [{"kind": "approval"}]
    assert "stage_index" not in rows[0]
    assert "stage_count" not in rows[0]


def test_history_query_presents_flow_stages_and_derived_carried_items(
    monkeypatch,
):
    # Sqlite cannot bind the presenter's member-item SQL; the gap under
    # test is the history SELECT plus compact carried-work presentation.
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read._member_items",
        lambda *_args, **_kwargs: {},
    )
    conn = _database()
    result = _read(conn, search="run-20260908-051")
    row = result["rows"][0]

    assert row["id"] == "run-20260908-051"
    assert row["flow"] == "release"
    assert row["flow_name"] == "Release"
    assert [stage["name"] for stage in row["stages"]] == [
        "merged", "hosted-release", "warm-up", "complete",
    ]
    assert all(stage["state"] == "complete" for stage in row["stages"])
    assert row["member_items"] == []
    assert row["carried_work"] == {
        "items": [{"ref": "YOK-3080", "item_id": 3207}],
    }


def test_cursor_refuses_malformed_values_with_reload_recovery():
    for value in ("", "not-base64", "e30"):
        try:
            decode_cursor(value)
        except RunHistoryCursorError as exc:
            assert "Reload the first Runs page" in str(exc)
        else:
            raise AssertionError(f"cursor {value!r} should be refused")
