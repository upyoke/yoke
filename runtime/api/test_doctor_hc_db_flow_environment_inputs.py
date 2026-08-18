"""A release route must dispatch an environment name its project registers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_db_flow_environment_inputs import (
    hc_flow_stage_environment_input,
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


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(
        c,
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT);
        CREATE TABLE sites (id TEXT PRIMARY KEY, project_id INTEGER);
        CREATE TABLE environments (id TEXT PRIMARY KEY, name TEXT, site TEXT);
        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER,
            status TEXT,
            stages TEXT
        );
        """,
    )
    c.execute("INSERT INTO projects (id, slug) VALUES (1, 'acme')")
    c.execute("INSERT INTO sites (id, project_id) VALUES ('acme-web', 1)")
    c.execute(
        "INSERT INTO environments (id, name, site) VALUES "
        "('acme-web-prod', 'prod', 'acme-web'), "
        "('acme-web-stage', 'stage', 'acme-web')"
    )
    c.commit()
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _add_flow(conn, flow_id: str, stages: list, status: str = "active") -> None:
    conn.execute(
        "INSERT INTO deployment_flows (id, project_id, status, stages) "
        "VALUES (%s, 1, %s, %s)",
        (flow_id, status, json.dumps(stages)),
    )
    conn.commit()


def _run(conn) -> _Record:
    rec = _RecorderStub()
    hc_flow_stage_environment_input(conn, _DoctorArgsStub(), rec)
    assert len(rec.records) == 1
    return rec.records[0]


def test_registered_environment_name_passes(conn):
    _add_flow(conn, "acme-prod", [{"name": "roll", "inputs": {"target_environment": "prod"}}])

    assert _run(conn).verdict == "PASS"


def test_unregistered_environment_name_fails_and_names_the_alternatives(conn):
    _add_flow(
        conn, "acme-prod", [{"name": "roll", "inputs": {"target_environment": "production"}}]
    )

    record = _run(conn)

    assert record.verdict == "FAIL"
    assert "acme/acme-prod" in record.detail
    assert "target_environment='production'" in record.detail
    # The refusal names what the project does register, so the repair is
    # visible without a second lookup.
    assert "prod, stage" in record.detail


def test_runtime_placeholder_is_not_a_literal_to_check(conn):
    # The route defers the environment to the run that starts it; the runner
    # fills this from the run's typed environment reference.
    _add_flow(
        conn,
        "acme-typed",
        [{"name": "roll", "inputs": {"target_environment": "{target_environment}"}}],
    )

    assert _run(conn).verdict == "PASS"


def test_disabled_route_is_retained_history_and_not_checked(conn):
    # A disabled definition cannot start a run and is immutable by design, so
    # flagging it would report a defect nobody is allowed to repair.
    _add_flow(
        conn,
        "acme-old",
        [{"name": "roll", "inputs": {"target_environment": "production"}}],
        status="disabled",
    )

    assert _run(conn).verdict == "PASS"


def test_inputs_without_an_environment_key_are_ignored(conn):
    _add_flow(
        conn,
        "acme-prod",
        [{"name": "roll", "inputs": {"release_mode": "normal", "platform_ref": "abc123"}}],
    )

    assert _run(conn).verdict == "PASS"


def test_unparseable_stage_json_is_left_to_the_stage_json_check(conn):
    conn.execute(
        "INSERT INTO deployment_flows (id, project_id, status, stages) "
        "VALUES ('acme-broken', 1, 'active', 'not json')"
    )
    conn.commit()

    assert _run(conn).verdict == "PASS"
