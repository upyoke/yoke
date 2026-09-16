"""The frozen identity a paged run row carries to the run detail page.

The page's compact shape trims the member listing; it must not trim the run's
own identity. Which candidate a run carries, the artifact built from it, and
when its membership stopped changing are what decide whether evidence
recorded against the run still answers for it — and a detail page reading
those four facts from this row renders "not recorded" for every one of them
when the projection leaves them out.
"""

from __future__ import annotations

import sqlite3

from yoke_core.domain.deployment_run_history_read import (
    RUN_HISTORY_FIELDS,
    read_deployment_run_history,
)


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
            completed_at TEXT, carried_work TEXT, release_lineage TEXT,
            artifact_identity TEXT, composition_frozen_at TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT,
            status TEXT, project_sequence INTEGER
        );
        CREATE TABLE deployment_run_items (
            run_id TEXT, item_id INTEGER, added_at TEXT
        );
        INSERT INTO projects VALUES (1, 'visible', 'VIS');
        INSERT INTO environments VALUES (1, 'stage');
        INSERT INTO deployment_flows VALUES
            ('release', 1, 'Release', '["deploy"]');
        INSERT INTO deployment_runs VALUES
            ('run-frozen', 1, 'release', 'persistent', 1, 'executing',
             'deploy', '2026-09-15T10:00:00Z', '', '', '{}',
             'aa11bb22cc33dd44ee55ff6677889900aabbccdd',
             'ghcr.io/example/demo@sha256:4f1c', '2026-09-15T10:00:10Z'),
            ('run-open', 1, 'release', 'persistent', 1, 'created',
             'deploy', '2026-09-15T09:00:00Z', '', '', '{}',
             NULL, NULL, NULL);
    """)
    conn.commit()
    return conn


def _row(monkeypatch, run_id: str) -> dict:
    # Presentation joins members and gates in psycopg paramstyle, which this
    # in-memory fixture does not speak; the subject here is the projection.
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_history_read.present_deployment_runs",
        lambda _conn, rows, **_kwargs: rows,
    )
    page = read_deployment_run_history(
        _database(),
        project_ids=[1],
        search=None,
        status=None,
        environment=None,
        flow=None,
        page_size=10,
        cursor=None,
        actor_id=None,
    )
    return next(row for row in page["rows"] if row["id"] == run_id)


def test_the_page_declares_the_identity_fields_it_serves() -> None:
    for field in ("release_lineage", "artifact_identity", "composition_frozen_at"):
        assert field in RUN_HISTORY_FIELDS


def test_a_frozen_run_carries_its_candidate_artifact_and_freeze_moment(
    monkeypatch,
) -> None:
    row = _row(monkeypatch, "run-frozen")
    assert row["release_lineage"] == "aa11bb22cc33dd44ee55ff6677889900aabbccdd"
    assert row["artifact_identity"] == "ghcr.io/example/demo@sha256:4f1c"
    assert row["composition_frozen_at"] == "2026-09-15T10:00:10Z"


def test_an_unfrozen_run_carries_the_absence_rather_than_omitting_the_field(
    monkeypatch,
) -> None:
    # Not yet frozen and frozen are different states. The field travels empty
    # so the reader can say which one this is.
    row = _row(monkeypatch, "run-open")
    for field in ("release_lineage", "artifact_identity", "composition_frozen_at"):
        assert field in row
        assert not row[field]
