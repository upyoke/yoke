"""Tests for HC-path-claim-owner-kind."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_path_claim_owner_kind import (
    hc_path_claim_owner_kind,
)


@dataclass
class _Rec:
    name: str
    desc: str
    status: str
    detail: str


class _Collector:
    def __init__(self) -> None:
        self.records: List[_Rec] = []

    def record(self, name: str, desc: str, status: str, detail: str) -> None:
        self.records.append(_Rec(name, desc, status, detail))


@dataclass
class _Args:
    verbose: bool = False


_TYPED_SCHEMA = """
CREATE TABLE items (id INTEGER PRIMARY KEY);
CREATE TABLE path_claims (
    id INTEGER PRIMARY KEY,
    state TEXT,
    item_id INTEGER,
    work_claim_id INTEGER,
    session_id TEXT,
    owner_kind TEXT,
    owner_item_id INTEGER,
    owner_session_id TEXT,
    owner_work_claim_id INTEGER
);
"""


def _disposable_pg_db(ddl: str) -> Any:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    if ddl:
        apply_fixture_ddl(c, ddl)
    return pg_testdb.drop_database_on_close(c, name)


@pytest.fixture
def typed_conn() -> Any:
    c = _disposable_pg_db(_TYPED_SCHEMA)
    yield c
    c.close()


def _run(conn) -> _Collector:
    rec = _Collector()
    hc_path_claim_owner_kind(conn, _Args(), rec)
    return rec


class TestPass:
    def test_pass_on_empty_table(self, typed_conn):
        rec = _run(typed_conn)
        assert rec.records[0].status == "PASS"

    def test_pass_on_well_typed_item_owner(self, typed_conn):
        typed_conn.execute("INSERT INTO items (id) VALUES (42)")
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind, owner_item_id) "
            "VALUES (1, 'active', 'item', 42)"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "PASS"

    def test_pass_on_well_typed_session_owner(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind, owner_session_id) "
            "VALUES (1, 'active', 'session', 'sess-A')"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "PASS"

    def test_pass_on_well_typed_process_owner(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind, owner_work_claim_id) "
            "VALUES (1, 'active', 'process', 9)"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "PASS"


class TestSkipOnPreMigrationSchema:
    def test_skip_when_typed_columns_absent(self):
        c = _disposable_pg_db(
            "CREATE TABLE path_claims (id INTEGER PRIMARY KEY, state TEXT)"
        )
        try:
            rec = _run(c)
            assert rec.records[0].status == "SKIP"
            assert "owner columns absent" in rec.records[0].detail
        finally:
            c.close()

    def test_pass_when_path_claims_missing(self):
        c = _disposable_pg_db("")
        try:
            rec = _run(c)
            assert rec.records[0].status == "PASS"
            assert "missing" in rec.records[0].detail
        finally:
            c.close()


class TestNullOwnerKind:
    def test_warn_for_null_owner_on_non_terminal(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, item_id, work_claim_id) "
            "VALUES (10, 'active', 1, 2)"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "WARN"
        assert "id=10" in rec.records[0].detail
        assert "item_id=1" in rec.records[0].detail
        assert "work_claim_id=2" in rec.records[0].detail

    def test_terminal_null_owner_does_not_warn(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, item_id, work_claim_id) "
            "VALUES (11, 'released', 1, 2)"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "PASS"


class TestInvalidOwnerKindEnum:
    def test_warn_on_unknown_kind(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind) "
            "VALUES (12, 'planned', 'orphan')"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "WARN"
        assert "outside the closed enum" in rec.records[0].detail
        assert "id=12" in rec.records[0].detail


class TestMissingTypedField:
    def test_item_kind_without_owner_item_id(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind) "
            "VALUES (13, 'planned', 'item')"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "WARN"
        assert "lack the matching typed owner" in rec.records[0].detail
        assert "id=13" in rec.records[0].detail

    def test_session_kind_without_owner_session_id(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind) "
            "VALUES (14, 'active', 'session')"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "WARN"
        assert "id=14" in rec.records[0].detail

    def test_process_kind_without_owner_work_claim(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind) "
            "VALUES (15, 'planned', 'process')"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "WARN"
        assert "id=15" in rec.records[0].detail


class TestOffAxisOwnerFields:
    def test_item_kind_with_owner_session_id(self, typed_conn):
        typed_conn.execute("INSERT INTO items (id) VALUES (5)")
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind, owner_item_id, "
            "owner_session_id) VALUES (16, 'active', 'item', 5, 'sess-X')"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "WARN"
        assert "off-axis owner field" in rec.records[0].detail
        assert "id=16" in rec.records[0].detail

    def test_session_kind_with_owner_item_id(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind, owner_session_id, "
            "owner_item_id) VALUES (17, 'active', 'session', 'sess-Y', 99)"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "WARN"
        assert "id=17" in rec.records[0].detail


class TestDanglingItemReference:
    def test_dangling_item_id_flagged(self, typed_conn):
        # owner_item_id=999 with no row in items
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind, owner_item_id) "
            "VALUES (18, 'active', 'item', 999)"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "WARN"
        assert "dangling" in rec.records[0].detail
        assert "id=18" in rec.records[0].detail

    def test_dangling_item_terminal_state_not_flagged(self, typed_conn):
        typed_conn.execute(
            "INSERT INTO path_claims (id, state, owner_kind, owner_item_id) "
            "VALUES (19, 'released', 'item', 999)"
        )
        rec = _run(typed_conn)
        assert rec.records[0].status == "PASS"
