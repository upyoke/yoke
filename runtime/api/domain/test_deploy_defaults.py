"""Tests for the ``deploy_defaults`` accessor helper.

Covers the read path that item creation and gate-local reconciliation
exercise after the coarse project-level deployment-default columns moved
into the Project Structure aggregate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import deploy_defaults as dd
from yoke_core.domain import project_structure as ps
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


NOW = "2026-04-20T00:00:00Z"
PROJECT_IDS = {**SEED_PROJECT_IDS, "solo": 101}


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_project(db_path: str, slug: str) -> None:
    conn = connect_test_db(db_path)
    try:
        p = _p(conn)
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT(id) DO NOTHING",
            (PROJECT_IDS[slug], slug, slug, NOW),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def initialized_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # The seam owns the per-test DB lifecycle: a real file under tmp_path on
    # SQLite, a disposable per-test database (dropped on context exit) on
    # Postgres. ``ps.cmd_init`` is the apply_schema strategy because the full
    # production ``schema.cmd_init`` does not create the ``project_structure``
    # table this family reads/writes; ``ps.cmd_init`` is that table's DDL owner
    # and resolves its connection through the backend factory. YOKE_DB is
    # bound for the test body so the CLI surface (``dd.main`` -> YOKE_DB) and
    # the db_path-passing helpers hit the same database; on Postgres the binding
    # is inert and the repointed YOKE_PG_DSN selects the per-test DB.
    with init_test_db(tmp_path, apply_schema=ps.cmd_init) as db_path:
        _seed_project(db_path, "solo")
        _seed_project(db_path, "yoke")
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


class TestGetDefaultFlow:
    def test_returns_none_when_unset(self, initialized_db: str) -> None:
        assert dd.get_default_flow("solo", db_path=initialized_db) is None

    def test_returns_seeded_yoke_default(self, initialized_db: str) -> None:
        ps.cmd_seed("yoke", db_path=initialized_db)
        assert (
            dd.get_default_flow("yoke", db_path=initialized_db)
            == "yoke-internal"
        )

    def test_returns_explicitly_written_value(self, initialized_db: str) -> None:
        dd.set_default_flow("solo", "solo-prod", db_path=initialized_db)
        assert (
            dd.get_default_flow("solo", db_path=initialized_db) == "solo-prod"
        )


class TestSetDefaultFlow:
    def test_rejects_empty_flow(self, initialized_db: str) -> None:
        with pytest.raises(ValueError):
            dd.set_default_flow("solo", "", db_path=initialized_db)

    def test_upsert_overwrites_existing(self, initialized_db: str) -> None:
        dd.set_default_flow("solo", "first", db_path=initialized_db)
        dd.set_default_flow("solo", "second", db_path=initialized_db)
        assert dd.get_default_flow("solo", db_path=initialized_db) == "second"

    def test_rejects_unknown_family_payload_shape(
        self, initialized_db: str
    ) -> None:
        """``deploy_defaults`` payload must carry ``deployment_flow``; the
        helper owns that invariant by always writing the right shape."""
        # The helper never constructs a bad payload itself — but the
        # underlying family validator must reject a malformed put so
        # operators who bypass the helper still hit a structural error.
        with pytest.raises(ps.ValidationError):
            ps.apply_patch(
                "solo",
                ops=[{
                    "op": "put",
                    "family": "deploy_defaults",
                    "attachment": "project",
                    "payload": {"wrong_key": "x"},
                }],
                actor="test",
                db_path=initialized_db,
            )


class TestClearDefaultFlow:
    def test_clear_when_absent_returns_false(self, initialized_db: str) -> None:
        assert dd.clear_default_flow("solo", db_path=initialized_db) is False

    def test_clear_when_present_returns_true(self, initialized_db: str) -> None:
        dd.set_default_flow("solo", "solo-prod", db_path=initialized_db)
        assert dd.clear_default_flow("solo", db_path=initialized_db) is True
        assert dd.get_default_flow("solo", db_path=initialized_db) is None


class TestCliSurface:
    """The domain CLI remains the operator write boundary."""

    def test_set_writes_default_flow(
        self, initialized_db: str, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        rc_set = dd.main(["set", "solo", "solo-prod"])
        assert rc_set == 0
        out = capsys.readouterr().out.strip()
        assert "solo-prod" in out
        assert dd.get_default_flow("solo") == "solo-prod"

    def test_clear_removes_default_flow(
        self, initialized_db: str, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        dd.set_default_flow("solo", "solo-prod", db_path=initialized_db)
        rc_clear = dd.main(["clear", "solo"])
        out = capsys.readouterr().out.strip()
        assert rc_clear == 0
        assert "Cleared deploy_defaults" in out
        assert dd.get_default_flow("solo") is None
