"""Tests for HC-project-verification-configured.

Covers: silent self-skip on missing structure table, PASS when a project has a
command_definitions command OR only a merge_verification policy, WARN when a
project has neither (the real bare-install state), the inert list excludes
configured projects, and an empty command payload counts as inert.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_project_verification import (
    CHECK_ID,
    hc_project_verification_configured,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _disposable_pg_db(ddl: str) -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    if ddl:
        apply_fixture_ddl(conn, ddl)
    return pg_testdb.drop_database_on_close(conn, name)


def _make_conn() -> Any:
    return _disposable_pg_db(
        "CREATE TABLE projects ("
        " id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL);"
        "CREATE TABLE project_structure ("
        " id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
        " family TEXT NOT NULL, payload TEXT);"
    )


def _record(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_project_verification_configured(conn, DoctorArgs(), rec)
    return rec


def _add_project(conn, pid, slug) -> None:
    conn.execute("INSERT INTO projects (id, slug) VALUES (%s, %s)", (pid, slug))


def _add_structure(conn, sid, pid, family, payload) -> None:
    conn.execute(
        "INSERT INTO project_structure (id, project_id, family, payload) "
        "VALUES (%s, %s, %s, %s)",
        (sid, pid, family, payload),
    )


def test_self_skip_when_structure_table_missing() -> None:
    conn = _disposable_pg_db("CREATE TABLE projects (id INTEGER, slug TEXT)")
    assert _record(conn).results == []


def test_pass_when_project_has_command_definitions() -> None:
    conn = _make_conn()
    _add_project(conn, 1, "yoke")
    _add_structure(conn, 1, 1, "command_definitions", '{"command":"pytest"}')
    rec = _record(conn)
    assert rec.results[0].result == "PASS"
    assert rec.results[0].check_id == CHECK_ID


def test_pass_when_project_has_only_merge_verification() -> None:
    conn = _make_conn()
    _add_project(conn, 1, "buzz")
    _add_structure(
        conn, 1, 1, "merge_verification",
        '{"command":"npm test","timeout_seconds":600}',
    )
    assert _record(conn).results[0].result == "PASS"


def test_warn_when_project_has_neither() -> None:
    conn = _make_conn()
    _add_project(conn, 1, "platform")  # the real bare-install state
    rec = _record(conn)
    assert rec.results[0].result == "WARN"
    assert "platform" in rec.results[0].detail


def test_warn_excludes_configured_projects() -> None:
    conn = _make_conn()
    _add_project(conn, 1, "yoke")
    _add_structure(conn, 1, 1, "command_definitions", '{"command":"pytest"}')
    _add_project(conn, 2, "platform")
    rec = _record(conn)
    assert rec.results[0].result == "WARN"
    inert_line = rec.results[0].detail.split("policy: ", 1)[1].split("\n")[0]
    assert "platform" in inert_line
    assert "yoke" not in inert_line


def test_empty_command_payload_is_inert() -> None:
    conn = _make_conn()
    _add_project(conn, 1, "empty")
    _add_structure(conn, 1, 1, "command_definitions", '{"command":""}')
    assert _record(conn).results[0].result == "WARN"
