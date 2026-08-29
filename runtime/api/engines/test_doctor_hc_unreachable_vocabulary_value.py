"""Unit tests for ``HC-unreachable-vocabulary-value``.

Each test builds a throwaway source tree plus a disposable Postgres table
carrying a CHECK-declared vocabulary, then asserts which of the three kinds of
reachability evidence clears a value and which leaves it reported.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks.check_unreachable_vocabulary_value import (
    HC_ID,
    constraint_vocabularies,
    hc_unreachable_vocabulary_value,
    unreachable_values,
)

_LAUNCHES_DDL = """
CREATE TABLE launches (
    launch_id TEXT PRIMARY KEY,
    origin TEXT NOT NULL CHECK(origin IN ('operator','retired_backstop'))
);
"""

#: The declaration alone — a constant, its vocabulary membership, and nothing
#: that writes either value. This is the shape an incomplete removal leaves.
_VOCABULARY_MODULE = '''
ORIGIN_OPERATOR = "operator"
ORIGIN_RETIRED_BACKSTOP = "retired_backstop"

ORIGINS = (ORIGIN_OPERATOR, ORIGIN_RETIRED_BACKSTOP)
'''


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    handle = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(handle, _LAUNCHES_DDL)
    yield handle
    handle.close()


@pytest.fixture
def tree(tmp_path):
    """A repo-shaped tree holding only the vocabulary declaration."""
    package = tmp_path / "packages" / "vocabulary"
    package.mkdir(parents=True)
    (package / "origins.py").write_text(_VOCABULARY_MODULE, encoding="utf-8")
    return tmp_path


def _add_module(tree: Path, name: str, body: str) -> None:
    (tree / "packages" / "vocabulary" / name).write_text(body, encoding="utf-8")


def test_reads_every_check_declared_vocabulary(conn):
    vocabulary = constraint_vocabularies(conn)
    assert ("launches", "origin", "operator") in vocabulary
    assert ("launches", "origin", "retired_backstop") in vocabulary


def test_reports_value_with_no_producer_and_no_rows(conn, tree):
    findings = unreachable_values(conn, tree)
    assert len(findings) == 2
    assert any("'retired_backstop'" in finding for finding in findings)


def test_names_the_surviving_definition_and_its_dead_readers(conn, tree):
    _add_module(
        tree,
        "reader.py",
        "from packages.vocabulary.origins import ORIGIN_RETIRED_BACKSTOP\n"
        "\n"
        "def is_backstop(row):\n"
        "    return row['origin'] == ORIGIN_RETIRED_BACKSTOP\n",
    )
    finding = next(
        f for f in unreachable_values(conn, tree) if "retired_backstop" in f
    )
    assert "origins.py:3" in finding
    assert "reader.py:4" in finding
    assert "Remediation:" in finding


def test_a_stored_row_clears_the_value(conn, tree):
    conn.execute(
        "INSERT INTO launches (launch_id, origin) VALUES (%s, %s)",
        ("launch-1", "retired_backstop"),
    )
    findings = unreachable_values(conn, tree)
    assert not any("retired_backstop" in finding for finding in findings)


def test_a_literal_writer_inside_sql_clears_the_value(conn, tree):
    _add_module(
        tree,
        "writer.py",
        "def retire(conn):\n"
        "    conn.execute(\"UPDATE launches SET origin='retired_backstop'\")\n",
    )
    findings = unreachable_values(conn, tree)
    assert not any("retired_backstop" in finding for finding in findings)


def test_a_named_producer_in_another_module_clears_the_value(conn, tree):
    _add_module(
        tree,
        "writer.py",
        "from packages.vocabulary.origins import ORIGIN_RETIRED_BACKSTOP\n"
        "\n"
        "def build():\n"
        "    return {'origin': ORIGIN_RETIRED_BACKSTOP}\n",
    )
    findings = unreachable_values(conn, tree)
    assert not any("retired_backstop" in finding for finding in findings)


def test_a_test_file_is_not_a_producer(conn, tree):
    _add_module(
        tree,
        "test_origins.py",
        "from packages.vocabulary.origins import ORIGIN_RETIRED_BACKSTOP\n"
        "\n"
        "def test_row():\n"
        "    assert {'origin': ORIGIN_RETIRED_BACKSTOP}\n",
    )
    findings = unreachable_values(conn, tree)
    assert any("retired_backstop" in finding for finding in findings)


def test_a_value_absent_from_source_is_database_only_residue(conn, tmp_path):
    (tmp_path / "packages").mkdir()
    assert unreachable_values(conn, tmp_path) == []


def test_records_warn_with_the_findings(conn, tree, monkeypatch):
    monkeypatch.setattr(
        "yoke_project_checks.check_unreachable_vocabulary_value"
        "._resolve_repo_root",
        lambda: str(tree),
    )
    rec = RecordCollector()
    hc_unreachable_vocabulary_value(conn, DoctorArgs(), rec)
    row = next(r for r in rec.results if r.check_id == HC_ID)
    assert row.result == "WARN"
    assert "retired_backstop" in row.detail


def test_records_pass_when_every_value_is_reachable(conn, tree, monkeypatch):
    _add_module(
        tree,
        "writer.py",
        "from packages.vocabulary.origins import (\n"
        "    ORIGIN_OPERATOR,\n"
        "    ORIGIN_RETIRED_BACKSTOP,\n"
        ")\n"
        "\n"
        "def build(retired):\n"
        "    return ORIGIN_RETIRED_BACKSTOP if retired else ORIGIN_OPERATOR\n",
    )
    monkeypatch.setattr(
        "yoke_project_checks.check_unreachable_vocabulary_value"
        "._resolve_repo_root",
        lambda: str(tree),
    )
    rec = RecordCollector()
    hc_unreachable_vocabulary_value(conn, DoctorArgs(), rec)
    row = next(r for r in rec.results if r.check_id == HC_ID)
    assert row.result == "PASS"
