"""Tests for the project-level context routing helper."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import context_routing
from yoke_core.domain import project_structure as ps
from yoke_core.domain.db_helpers import connect
from runtime.api.fixtures.file_test_db import init_test_db


def _seed_demo_project(path: str) -> None:
    conn = connect(path)
    try:
        conn.execute(
            """
            INSERT INTO projects
                (id, slug, name, public_item_prefix, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                slug = EXCLUDED.slug,
                name = EXCLUDED.name,
                public_item_prefix = EXCLUDED.public_item_prefix
            """,
            (100, "demo", "Demo", "YOK", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def initialized_db(tmp_path: Path) -> Iterator[str]:
    # Backend-aware per-test DB: a real file on SQLite, a disposable per-test
    # database on Postgres (YOKE_PG_DSN repointed for the context). Isolation
    # is the load-bearing property here — without it the Postgres tests share
    # the DSN-pointed database and one test's seeds pollute the next.
    with init_test_db(tmp_path, apply_schema=lambda: ps.cmd_init()) as path:
        _seed_demo_project(path)
        yield path


def test_helpers_read_project_wide_docs_and_topics(initialized_db: str) -> None:
    ps.apply_patch(
        "demo",
        ops=[
            {
                "op": "put",
                "family": "context_routing",
                "attachment": "project",
                "entry_key": "always",
                "payload": {"docs": ["AGENTS.md"]},
            },
            {
                "op": "put",
                "family": "context_routing",
                "attachment": "project",
                "entry_key": "testing",
                "payload": {"docs": ["docs/TESTING.md"]},
            },
            {
                "op": "put",
                "family": "context_routing",
                "attachment": "project",
                "entry_key": "frontend",
                "payload": {"docs": ["docs/DASHBOARD.md"]},
            },
        ],
        db_path=initialized_db,
    )

    assert context_routing.get_always_docs("demo", db_path=initialized_db) == [
        "AGENTS.md"
    ]
    assert context_routing.list_topics("demo", db_path=initialized_db) == [
        "frontend",
        "testing",
    ]
    assert context_routing.get_topic_docs(
        "demo", "testing", db_path=initialized_db
    ) == ["docs/TESTING.md"]
    assert context_routing.get_topic_docs(
        "demo", "always", db_path=initialized_db
    ) == []
    assert context_routing.get_topic_map("demo", db_path=initialized_db) == {
        "frontend": ["docs/DASHBOARD.md"],
        "testing": ["docs/TESTING.md"],
    }


def test_set_and_clear_entry(initialized_db: str) -> None:
    context_routing.set_entry(
        "demo", "backend", ["docs/API.md"], db_path=initialized_db,
    )
    assert context_routing.get_topic_docs(
        "demo", "backend", db_path=initialized_db,
    ) == ["docs/API.md"]

    assert context_routing.clear_entry(
        "demo", "backend", db_path=initialized_db,
    )
    assert context_routing.get_topic_docs(
        "demo", "backend", db_path=initialized_db,
    ) == []
    assert not context_routing.clear_entry(
        "demo", "backend", db_path=initialized_db,
    )


def test_cli_prints_docs_and_uses_miss_exit_code(
    initialized_db: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("YOKE_DB", initialized_db)
    context_routing.set_entry(
        "demo", "always", ["AGENTS.md", "docs/OVERVIEW.md"], db_path=initialized_db,
    )

    assert context_routing.main(["get-always", "demo"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "AGENTS.md",
        "docs/OVERVIEW.md",
    ]

    assert context_routing.main(["get-topic", "demo", "testing"]) == 1
    assert capsys.readouterr().out == ""


def test_cli_rejects_reserved_topic_name(
    initialized_db: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("YOKE_DB", initialized_db)

    rc = context_routing.main(["set-topic", "demo", "always", "AGENTS.md"])

    assert rc == 1
    assert "reserved" in capsys.readouterr().err
