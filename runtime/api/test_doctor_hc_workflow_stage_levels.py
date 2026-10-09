"""Doctor check for non-terminal items pinned to level-less workflow versions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_workflow_stage_levels import (
    hc_workflow_stage_level_pins,
)


@dataclass
class _DoctorArgsStub:
    project: str = "yoke"
    fix: bool = False
    rebuild_board: bool = False


@dataclass
class _Record:
    slug: str
    label: str
    verdict: str
    detail: str


class _RecorderStub:
    def __init__(self) -> None:
        self.records: List[_Record] = []

    def record(self, slug: str, label: str, verdict: str, detail: str) -> None:
        self.records.append(_Record(slug, label, verdict, detail))


def _definition(level: str | None) -> str:
    stages = [{"id": "idea"}, {"id": "implementing"}, {"id": "done"}]
    for stage in stages[:2]:
        if level:
            stage["level"] = level
    return json.dumps({"stages": stages, "terminal_stage_ids": ["done"]})


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(
        c,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT,
            public_item_prefix TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            project_sequence INTEGER,
            status TEXT,
            workflow_id TEXT,
            workflow_version_id INTEGER
        );
        CREATE TABLE workflows (
            id TEXT PRIMARY KEY,
            current_version_id INTEGER
        );
        CREATE TABLE workflow_versions (
            id INTEGER PRIMARY KEY,
            workflow_id TEXT,
            version INTEGER,
            definition_json TEXT
        );
        """,
    )
    c.execute(
        "INSERT INTO projects (id, slug, public_item_prefix) VALUES (1, 'yoke', 'YOK')"
    )
    c.execute(
        "INSERT INTO workflow_versions (id, workflow_id, version, definition_json) "
        "VALUES (10, 'dash', 1, %s), (11, 'dash', 2, %s)",
        (_definition(None), _definition("SENIOR")),
    )
    c.execute("INSERT INTO workflows (id, current_version_id) VALUES ('dash', 11)")
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _item(conn, item_id: int, sequence: int, status: str, version_id: int) -> None:
    conn.execute(
        "INSERT INTO items (id, project_id, project_sequence, status, "
        "workflow_id, workflow_version_id) VALUES (%s, 1, %s, %s, 'dash', %s)",
        (item_id, sequence, status, version_id),
    )


def _run(conn) -> _Record:
    rec = _RecorderStub()
    hc_workflow_stage_level_pins(conn, _DoctorArgsStub(), rec)
    assert len(rec.records) == 1
    return rec.records[0]


def test_passes_when_every_live_pin_is_levelled(conn):
    _item(conn, 1, 701, "implementing", 11)
    _item(conn, 2, 702, "done", 10)
    record = _run(conn)
    assert record.slug == "HC-workflow-stage-level-pins"
    assert record.verdict == "PASS"


def test_fails_naming_item_and_migrate_recipe(conn):
    _item(conn, 3, 703, "implementing", 10)
    record = _run(conn)
    assert record.verdict == "FAIL"
    assert "YOK-703 (implementing): pinned to dash v1" in record.detail
    assert "idea, implementing" in record.detail
    assert "stage_level_missing" in record.detail
    assert "yoke workflows item migrate YOK-703 --version 2 --preview" in record.detail
    assert "yoke workflows item migrate YOK-703 --version 2`" in record.detail


def test_terminal_items_on_levelless_versions_are_ignored(conn):
    _item(conn, 4, 704, "done", 10)
    assert _run(conn).verdict == "PASS"


def test_levelless_current_version_names_publish_recovery(conn):
    conn.execute("UPDATE workflows SET current_version_id = 10")
    _item(conn, 5, 705, "idea", 10)
    record = _run(conn)
    assert record.verdict == "FAIL"
    assert "current version is not levelled either" in record.detail
    assert "--version 1" not in record.detail
