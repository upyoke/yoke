"""Tests for the architecture-impact authoritative-status gate.

Covers the two narrow blockers the runner enforces:

* 'uncertain' past refined-idea is rejected with
  GATE_ARCHITECTURE_IMPACT_UNCERTAIN.
* 'architecture_model_change' requires path-claim coverage of an
  architecture-model authoring surface; missing coverage is rejected
  with GATE_ARCHITECTURE_MODEL_CHANGE_NO_SURFACE.

'none' and 'path_context_only' pass without further inspection.

The fixtures seed a per-test database through ``init_test_db`` so the same
bodies build on both engines: SQLite writes a file under ``tmp_path``, Postgres
provisions a disposable database with ``YOKE_PG_DSN`` repointed at it. The
minimal hand-built schema keeps the "table absent" short-circuit reachable on
both backends (the full canonical schema always has the path-claim tables).
"""

from __future__ import annotations

import contextlib

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_architecture_gate_runner import (
    _run_architecture_impact_gate,
)
from runtime.api.fixtures.file_test_db import init_test_db


def _apply_schema(impact: str, claim_path):
    """Return an ``init_test_db`` strategy seeding the minimal gate schema.

    Ids are supplied explicitly so the inserts do not depend on SQLite rowid
    autoincrement (Postgres ``INTEGER PRIMARY KEY`` is not auto-assigned).
    """

    def _apply() -> None:
        conn = db_backend.connect()
        try:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            conn.execute(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, "
                "architecture_impact TEXT NOT NULL DEFAULT 'none')"
            )
            conn.execute(
                f"INSERT INTO items (id, architecture_impact) VALUES ({p}, {p})",
                (1, impact),
            )
            if claim_path is not None:
                conn.execute(
                    "CREATE TABLE path_targets (id INTEGER PRIMARY KEY, "
                    "path_string TEXT NOT NULL)"
                )
                conn.execute(
                    "CREATE TABLE path_claims (id INTEGER PRIMARY KEY, "
                    "item_id INTEGER NOT NULL, state TEXT NOT NULL)"
                )
                conn.execute(
                    "CREATE TABLE path_claim_targets (claim_id INTEGER NOT NULL, "
                    "target_id INTEGER NOT NULL)"
                )
                conn.execute(
                    f"INSERT INTO path_targets (id, path_string) VALUES (1, {p})",
                    (claim_path,),
                )
                conn.execute(
                    "INSERT INTO path_claims (id, item_id, state) "
                    "VALUES (1, 1, 'active')"
                )
                conn.execute(
                    "INSERT INTO path_claim_targets (claim_id, target_id) "
                    "VALUES (1, 1)"
                )
            conn.commit()
        finally:
            conn.close()

    return _apply


@contextlib.contextmanager
def _build_db(tmp_path, impact: str, *, claim_path: str = None):
    with init_test_db(tmp_path, apply_schema=_apply_schema(impact, claim_path)) as path:
        yield path


class TestPassThroughCases:
    @pytest.mark.parametrize("impact", ["none", "path_context_only"])
    def test_low_impact_passes(self, tmp_path, impact):
        with _build_db(tmp_path, impact) as db:
            result = _run_architecture_impact_gate(
                item_id=1,
                target_status="reviewing-implementation",
                db_path=db,
            )
            assert result is None

    def test_unguarded_target_passes(self, tmp_path):
        """Targets outside the gate set (e.g. ``idea``) are bypassed."""
        with _build_db(tmp_path, "uncertain") as db:
            result = _run_architecture_impact_gate(
                item_id=1,
                target_status="idea",
                db_path=db,
            )
            assert result is None


class TestUncertainBlock:
    def test_uncertain_blocks_reviewing_implementation(self, tmp_path):
        with _build_db(tmp_path, "uncertain") as db:
            result = _run_architecture_impact_gate(
                item_id=1,
                target_status="reviewing-implementation",
                db_path=db,
            )
            assert result is not None
            assert result["error_code"] == "GATE_ARCHITECTURE_IMPACT_UNCERTAIN"
            assert "architecture_impact" in result["error"]


class TestArchitectureModelChange:
    def test_no_arch_surface_blocks(self, tmp_path):
        with _build_db(
            tmp_path,
            "architecture_model_change",
            claim_path="runtime/api/domain/unrelated.py",
        ) as db:
            result = _run_architecture_impact_gate(
                item_id=1,
                target_status="reviewing-implementation",
                db_path=db,
            )
            assert result is not None
            assert (result["error_code"]
                    == "GATE_ARCHITECTURE_MODEL_CHANGE_NO_SURFACE")
            assert "architecture-model" in result["error"]

    @pytest.mark.parametrize("path", [
        "runtime/api/domain/architecture_model.py",
        "runtime/api/domain/project_structure.py",
        "runtime/api/engines/doctor_hc_architecture.py",
        "runtime/api/domain/architecture_dependency_scan.py",
    ])
    def test_arch_surface_in_claim_passes(self, tmp_path, path):
        with _build_db(
            tmp_path, "architecture_model_change", claim_path=path,
        ) as db:
            result = _run_architecture_impact_gate(
                item_id=1,
                target_status="reviewing-implementation",
                db_path=db,
            )
            assert result is None

    def test_model_change_with_trailing_newline_passes_with_arch_surface(
        self, tmp_path,
    ):
        with _build_db(
            tmp_path,
            "architecture_model_change\n",
            claim_path="runtime/api/domain/architecture_model.py",
        ) as db:
            result = _run_architecture_impact_gate(
                item_id=1,
                target_status="reviewing-implementation",
                db_path=db,
            )
            assert result is None

    def test_minimal_schema_passes(self, tmp_path):
        """Test fixtures without path-claim tables short-circuit to pass."""
        with _build_db(tmp_path, "architecture_model_change") as db:
            result = _run_architecture_impact_gate(
                item_id=1,
                target_status="reviewing-implementation",
                db_path=db,
            )
            assert result is None
