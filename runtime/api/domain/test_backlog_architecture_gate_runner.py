"""Tests for the architecture-impact authoritative-status gate.

Covers the one narrow blocker the runner enforces:

* 'uncertain' past refined-idea is rejected with
  GATE_ARCHITECTURE_IMPACT_UNCERTAIN.

'none', 'path_context_only', and 'architecture_model_change' pass without
further inspection.

The fixtures seed a per-test database through ``init_test_db`` so the same
bodies build on both engines: SQLite writes a file under ``tmp_path``, Postgres
provisions a disposable database with ``YOKE_PG_DSN`` repointed at it. The
minimal hand-built schema includes empty path-claim tables so the model-change
case proves that no registered path claim is required on either backend.
"""

from __future__ import annotations

import contextlib

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_architecture_gate_runner import (
    _run_architecture_impact_gate,
)
from runtime.api.fixtures.file_test_db import init_test_db


def _apply_schema(impact: str):
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
            conn.execute(
                "CREATE TABLE path_targets (id INTEGER PRIMARY KEY, "
                "path_string TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE path_claims (id INTEGER PRIMARY KEY, "
                "owner_kind TEXT NOT NULL, owner_item_id INTEGER NOT NULL, "
                "state TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE path_claim_targets (claim_id INTEGER NOT NULL, "
                "target_id INTEGER NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()

    return _apply


@contextlib.contextmanager
def _build_db(tmp_path, impact: str):
    with init_test_db(tmp_path, apply_schema=_apply_schema(impact)) as path:
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
    def test_model_change_passes_without_path_claims(self, tmp_path):
        with _build_db(tmp_path, "architecture_model_change") as db:
            result = _run_architecture_impact_gate(
                item_id=1,
                target_status="reviewing-implementation",
                db_path=db,
            )
            assert result is None
