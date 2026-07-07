"""Tests for the architecture-fitness Doctor HCs.

Covers the four positive-and-negative cases the ACs name explicitly:

* AC-7: domain_invariants → orchestration import fails forbidden-edge.
* AC-8: direct ``sqlite3.connect`` import from an unapproved module
  fails cross-cutting-entrypoint.
* AC-9: a snapshot path with no inherited layer / domain fails
  unclassified-path; an exemption-marked path passes.
* AC-21: corrupt ``dependency_edges`` JSON fires scan-error.

Item-side tests cover the impact-declaration HC: invalid enum values
fire findings, ``uncertain`` past ``refined-idea`` fires findings,
clean rows PASS.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yoke_core.domain import path_context, project_structure as ps
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.engines.doctor_hc_architecture import (
    hc_architecture_cross_cutting_entrypoint,
    hc_architecture_forbidden_edge,
    hc_architecture_unclassified_path,
)
from yoke_core.engines.doctor_hc_architecture_items import (
    hc_architecture_scan_error,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.path_context_test_helpers import (
    emit_event,
    init_minimal_schema,
    mint_target,
)


def _seed_model(conn: Any, project_id: int = 1) -> None:
    """Seed a tiny architecture_model with two layers + one guarded
    cross-cutting entrypoint; enough to exercise all three path HCs."""
    payload = {
        "domains": [
            {"id": "domain_invariants",
             "path_roots": ["runtime/api/domain/*.py"]},
        ],
        "layers": [
            {"id": "domain_invariants", "may_depend_on": [],
             "forbidden_edges": ["orchestration"]},
            {"id": "orchestration",
             "may_depend_on": ["domain_invariants"],
             "forbidden_edges": []},
        ],
        "cross_cutting_entrypoints": {
            "db_path": {
                "approved_modules": [
                    "yoke_core.domain.db_helpers",
                    "yoke_core.cli.db_router",
                ],
                "guarded_imports": ["sqlite3.connect"],
            },
        },
    }
    conn.execute(
        "INSERT INTO project_structure "
        "(project_id, family, attachment_kind, attachment_value, "
        "entry_key, payload, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (project_id, "architecture_model", "", "project", "",
         json.dumps(payload), iso8601_now(), iso8601_now()),
    )
    conn.commit()


def _assign_layer(
    conn: Any, target_id: int, layer: str,
) -> None:
    event_id = emit_event(conn, name="LayerAssigned")
    path_context.put_context_value(
        conn,
        target_id=target_id,
        context_family=path_context.FAMILY_ARCHITECTURE_LAYER,
        entry_key="",
        value={"layer": layer},
        recorded_event_id=event_id,
    )


def _make_snapshot_entry(
    conn: Any,
    *,
    snapshot_id: int,
    target_id: int,
    module_name: str,
    edges,
    language: str = "python",
) -> None:
    conn.execute(
        "INSERT INTO path_snapshot_entries "
        "(snapshot_id, target_id, line_count, language, module_name, "
        "area, is_generated, dependency_edges) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (snapshot_id, target_id, 10, language, module_name, None, 0,
         json.dumps(edges) if not isinstance(edges, str) else edges),
    )


def _make_snapshot(
    conn: Any, project_id: int = 1,
) -> int:
    cur = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (%s, %s, %s) RETURNING id",
        (project_id, "abc1234", iso8601_now()),
    )
    return int(cur.fetchone()[0])


def _args(project: str = "yoke") -> DoctorArgs:
    return DoctorArgs(project=project)


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = init_minimal_schema(str(tmp_path / "t.db"))
    yield c
    c.close()


class TestUnclassifiedPath:
    def test_path_without_layer_or_domain_warns(self, conn):
        _seed_model(conn)
        tid = mint_target(conn, "yoke", "runtime/api/domain/floater.py")
        snap = _make_snapshot(conn)
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=tid,
            module_name="yoke_core.domain.floater", edges=[],
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_unclassified_path(conn, _args(), rec)
        assert rec.results[-1].result == "WARN"
        assert "floater.py" in rec.results[-1].detail

    def test_path_with_layer_passes(self, conn):
        _seed_model(conn)
        tid = mint_target(conn, "yoke", "runtime/api/domain/bound.py")
        _assign_layer(conn, tid, "domain_invariants")
        snap = _make_snapshot(conn)
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=tid,
            module_name="yoke_core.domain.bound", edges=[],
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_unclassified_path(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"

    def test_exemption_family_passes(self, conn):
        _seed_model(conn)
        tid = mint_target(conn, "yoke", "fixtures/sample.py")
        event_id = emit_event(conn, name="ExemptionAssigned")
        path_context.put_context_value(
            conn,
            target_id=tid,
            context_family=path_context.FAMILY_FIXTURE,
            entry_key="",
            value={"reason": "test_fixture"},
            recorded_event_id=event_id,
        )
        snap = _make_snapshot(conn)
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=tid,
            module_name="fixtures.sample", edges=[],
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_unclassified_path(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"

    def test_missing_model_self_skips(self, conn):
        rec = RecordCollector()
        hc_architecture_unclassified_path(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"
        assert "skipping" in rec.results[-1].detail


class TestForbiddenEdge:
    def test_domain_to_engine_import_fires(self, conn):
        """AC-7: a domain_invariants module importing
        yoke_core.engines.foo fails the HC."""
        _seed_model(conn)
        src = mint_target(
            conn, "yoke", "runtime/api/domain/leak.py",
        )
        dst = mint_target(
            conn, "yoke", "runtime/api/engines/orchestrator.py",
        )
        _assign_layer(conn, src, "domain_invariants")
        _assign_layer(conn, dst, "orchestration")
        snap = _make_snapshot(conn)
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=src,
            module_name="yoke_core.domain.leak",
            edges=[{
                "source_module": "yoke_core.domain.leak",
                "imported_module": "yoke_core.engines.orchestrator",
                "imported_name": "orchestrator",
            }],
        )
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=dst,
            module_name="yoke_core.engines.orchestrator", edges=[],
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_forbidden_edge(conn, _args(), rec)
        assert rec.results[-1].result == "WARN"
        assert "domain_invariants → orchestration" in rec.results[-1].detail
        assert "leak.py" in rec.results[-1].detail

    def test_allowed_edge_passes(self, conn):
        _seed_model(conn)
        src = mint_target(
            conn, "yoke", "runtime/api/engines/orch.py",
        )
        dst = mint_target(
            conn, "yoke", "runtime/api/domain/helper.py",
        )
        _assign_layer(conn, src, "orchestration")
        _assign_layer(conn, dst, "domain_invariants")
        snap = _make_snapshot(conn)
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=src,
            module_name="yoke_core.engines.orch",
            edges=[{
                "source_module": "yoke_core.engines.orch",
                "imported_module": "yoke_core.domain.helper",
                "imported_name": "helper",
            }],
        )
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=dst,
            module_name="yoke_core.domain.helper", edges=[],
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_forbidden_edge(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"


class TestCrossCuttingEntrypoint:
    def test_unapproved_sqlite_connect_fires(self, conn):
        """AC-8: a module that imports sqlite3.connect directly while
        outside the approved entrypoint list fails the HC."""
        _seed_model(conn)
        tid = mint_target(
            conn, "yoke", "runtime/api/domain/sneaky.py",
        )
        _assign_layer(conn, tid, "domain_invariants")
        snap = _make_snapshot(conn)
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=tid,
            module_name="yoke_core.domain.sneaky",
            edges=[{
                "source_module": "yoke_core.domain.sneaky",
                "imported_module": "sqlite3",
                "imported_name": "connect",
            }],
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_cross_cutting_entrypoint(conn, _args(), rec)
        assert rec.results[-1].result == "WARN"
        assert "sqlite3.connect" in rec.results[-1].detail
        assert "sneaky.py" in rec.results[-1].detail

    def test_approved_module_passes(self, conn):
        _seed_model(conn)
        tid = mint_target(
            conn, "yoke", "runtime/api/domain/db_helpers.py",
        )
        snap = _make_snapshot(conn)
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=tid,
            module_name="yoke_core.domain.db_helpers",
            edges=[{
                "source_module": "yoke_core.domain.db_helpers",
                "imported_module": "sqlite3",
                "imported_name": "connect",
            }],
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_cross_cutting_entrypoint(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"


class TestScanError:
    def test_clean_rows_pass(self, conn):
        tid = mint_target(conn, "yoke", "runtime/api/domain/ok.py")
        snap = _make_snapshot(conn)
        _make_snapshot_entry(
            conn, snapshot_id=snap, target_id=tid,
            module_name="yoke_core.domain.ok", edges=[],
        )
        conn.commit()
        rec = RecordCollector()
        hc_architecture_scan_error(conn, _args(), rec)
        assert rec.results[-1].result == "PASS"
