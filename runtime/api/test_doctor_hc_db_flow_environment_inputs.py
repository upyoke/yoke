"""A release route must dispatch an environment name its project registers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_db_flow_environment_inputs import (
    _workflow_choice_issues,
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
        CREATE TABLE sites (id INTEGER PRIMARY KEY, project_id INTEGER);
        CREATE TABLE environments (
            id INTEGER PRIMARY KEY, name TEXT, site INTEGER, project_id INTEGER
        );
        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER,
            status TEXT,
            stages TEXT
        );
        """,
    )
    c.execute("INSERT INTO projects (id, slug) VALUES (1, 'acme')")
    c.execute("INSERT INTO sites (id, project_id) VALUES (101, 1)")
    c.execute(
        "INSERT INTO environments (id, name, site, project_id) VALUES "
        "(201, 'prod', 101, 1), "
        "(202, 'stage', 101, 1)"
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
        conn,
        "acme-prod",
        [{"name": "roll", "inputs": {"target_environment": "customer-west"}}],
    )

    record = _run(conn)

    assert record.verdict == "FAIL"
    assert "acme/acme-prod" in record.detail
    assert "target_environment='customer-west'" in record.detail
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
        [{"name": "roll", "inputs": {"target_environment": "legacy-env"}}],
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


def test_workflow_environment_choices_must_equal_registered_names(tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "release.yml").write_text(
        """on:
  workflow_dispatch:
    inputs:
      target_environment:
        type: choice
        options: [stage, customer-west]
""",
        encoding="utf-8",
    )

    issues = _workflow_choice_issues(
        tmp_path, project="acme", names=["prod", "stage"],
    )

    assert len(issues) == 1
    assert "customer-west" in issues[0]
    assert "['prod', 'stage']" in issues[0]


def test_workflow_environment_choices_pass_when_registry_matches(tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "release.yaml").write_text(
        """on:
  workflow_dispatch:
    inputs:
      environment:
        type: choice
        options:
          - stage
          - prod
""",
        encoding="utf-8",
    )

    assert _workflow_choice_issues(
        tmp_path, project="acme", names=["prod", "stage"],
    ) == []
