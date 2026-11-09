"""Tests for the item-side architecture-fitness HCs.

Covers ``HC-architecture-impact-declaration`` (enum validation +
post-refined-idea 'uncertain' guard) and ``HC-architecture-scan-error``
(corrupt ``dependency_edges`` detection without re-scan).

Path-based HC tests (unclassified-path, forbidden-edge,
cross-cutting-entrypoint) live in
:mod:`runtime.api.engines.test_doctor_hc_architecture`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.engines.doctor_hc_architecture_items import (
    hc_architecture_impact_declaration,
    hc_architecture_scan_error,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.path_context_test_helpers import (
    init_minimal_schema,
    mint_target,
)


def _args(project: str = "yoke") -> DoctorArgs:
    return DoctorArgs(project=project)


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = init_minimal_schema(str(tmp_path / "t.db"))
    yield c
    c.close()


def _make_items_table(conn: Any) -> None:
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, status TEXT, "
        "architecture_impact TEXT NOT NULL DEFAULT 'none', "
        "workflow_version_id INTEGER NOT NULL DEFAULT 1)"
    )
    conn.execute("CREATE TABLE workflow_versions (id INTEGER, definition_json TEXT)")
    for version, terminal in ((1, "done"), (2, "archived")):
        conn.execute("INSERT INTO workflow_versions VALUES (%s, %s)", (
            version, json.dumps({"terminal_stage_ids": [terminal]}),
        ))


def _make_snapshot(
    conn: Any, project_id: int = 1,
) -> int:
    cur = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (%s, %s, %s) RETURNING id",
        (project_id, "abc1234", iso8601_now()),
    )
    return int(cur.fetchone()[0])


class TestImpactDeclaration:
    @pytest.mark.parametrize("status,version", [
        ("done", 1), ("cancelled", 1), ("stopped", 1), ("archived", 2),
    ])
    @pytest.mark.parametrize("value", ["major_refactor", "uncertain"])
    def test_terminal_declarations_are_ignored(self, conn, status, version, value):
        _make_items_table(conn)
        conn.execute("INSERT INTO items VALUES (1, %s, %s, %s)", (status, value, version))
        conn.commit()
        rec = RecordCollector()
        hc_architecture_impact_declaration(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"
        assert not rec.results[-1].detail

    def test_done_is_active_when_the_pin_uses_a_different_terminal(self, conn):
        _make_items_table(conn)
        conn.execute("INSERT INTO items VALUES (1, 'done', 'major_refactor', 2)")
        conn.commit()
        rec = RecordCollector()
        hc_architecture_impact_declaration(conn, _args(), rec)
        assert rec.results[-1].result == "WARN"
        assert "major_refactor" in rec.results[-1].detail

    def test_invalid_enum_warns(self, conn):
        _make_items_table(conn)
        conn.execute(
            "INSERT INTO items VALUES (1, 'idea', 'major_refactor', 1)"
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_impact_declaration(conn, _args(), rec)
        assert rec.results[-1].result == "WARN"
        assert "major_refactor" in rec.results[-1].detail
        assert "yoke items structured-field replace" in rec.results[-1].detail
        assert "--field architecture_impact --content <value>" in rec.results[-1].detail
        assert "put the reasoning in the spec" in rec.results[-1].detail
        assert "db_router" not in rec.results[-1].detail

    def test_uncertain_past_refined_idea_warns(self, conn):
        _make_items_table(conn)
        conn.execute(
            "INSERT INTO items VALUES (1, 'implementing', 'uncertain', 1)"
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_impact_declaration(conn, _args(), rec)
        assert rec.results[-1].result == "WARN"
        assert "implementing" in rec.results[-1].detail
        assert "uncertain" in rec.results[-1].detail

    def test_uncertain_at_idea_passes(self, conn):
        _make_items_table(conn)
        conn.execute(
            "INSERT INTO items VALUES (1, 'idea', 'uncertain', 1)"
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_impact_declaration(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"

    def test_resolved_value_passes(self, conn):
        _make_items_table(conn)
        conn.execute(
            "INSERT INTO items VALUES (1, 'implementing', 'none', 1)"
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_impact_declaration(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"

    def test_missing_column_self_skips(self, conn):
        rec = RecordCollector()
        hc_architecture_impact_declaration(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"
        assert "skipping" in rec.results[-1].detail


class TestScanErrorEdge:
    def test_corrupt_dependency_edges_warns(self, conn):
        tid = mint_target(
            conn, "yoke", "runtime/api/domain/corrupt.py",
        )
        snap = _make_snapshot(conn)
        conn.execute(
            "INSERT INTO path_snapshot_entries "
            "(snapshot_id, target_id, line_count, language, "
            "module_name, area, is_generated, dependency_edges) "
            "VALUES (%s, %s, 5, 'python', 'corrupt', NULL, 0, %s)",
            (snap, tid, "not-json{"),
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_scan_error(conn, _args(), rec)
        assert rec.results[-1].result == "WARN"
        assert "corrupt.py" in rec.results[-1].detail

    def test_parse_failure_edge_warns(self, conn):
        tid = mint_target(
            conn, "yoke", "runtime/api/domain/broken.py",
        )
        snap = _make_snapshot(conn)
        conn.execute(
            "INSERT INTO path_snapshot_entries "
            "(snapshot_id, target_id, line_count, language, "
            "module_name, area, is_generated, dependency_edges) "
            "VALUES (%s, %s, 5, 'python', 'broken', NULL, 0, %s)",
            (snap, tid, '[{\"source_module\":\"broken\",'
             '\"imported_module\":\"\",\"imported_name\":\"\",'
             '\"scan_error\":\"SyntaxError: invalid syntax\"}]'),
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_scan_error(conn, _args(), rec)
        assert rec.results[-1].result == "WARN"
        assert "Python import scan failed" in rec.results[-1].detail
        assert "broken.py" in rec.results[-1].detail

    def test_missing_table_self_skips(self, conn):
        conn.execute("DROP TABLE path_snapshot_entries")
        conn.commit()
        rec = RecordCollector()
        hc_architecture_scan_error(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"
        assert "skipping" in rec.results[-1].detail

    def test_clean_rows_pass(self, conn):
        tid = mint_target(conn, "yoke", "runtime/api/domain/ok.py")
        snap = _make_snapshot(conn)
        conn.execute(
            "INSERT INTO path_snapshot_entries "
            "(snapshot_id, target_id, line_count, language, "
            "module_name, area, is_generated, dependency_edges) "
            "VALUES (%s, %s, 5, 'python', 'ok', NULL, 0, '[]')",
            (snap, tid),
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_scan_error(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"
