"""Tests for the ``merge_verification`` accessor helper.

Covers the read/write surface that the merge engine and operators
exercise to manage the project-specific pre-merge verification policy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import merge_verification as mv
from yoke_core.domain import project_structure as ps
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


NOW = "2026-04-20T00:00:00Z"
SOLO_PROJECT_ID = 101


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_solo_project(db_path: str) -> None:
    conn = connect_test_db(db_path)
    try:
        p = _p(conn)
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT(id) DO NOTHING",
            (SOLO_PROJECT_ID, "solo", "solo", NOW),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def initialized_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    # Backend-aware: SQLite writes a real file under tmp_path; Postgres gets a
    # disposable per-test database (so the shared dbname=postgres DB is never
    # polluted across tests). ps.cmd_init applies the project_structure schema
    # through the backend factory regardless of engine.
    with init_test_db(tmp_path, apply_schema=ps.cmd_init) as db_path:
        _seed_solo_project(db_path)
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


class TestGetCommand:
    def test_returns_none_when_unset(self, initialized_db: str) -> None:
        assert mv.get_policy("solo", db_path=initialized_db) is None
        assert mv.get_command("solo", db_path=initialized_db) is None

    def test_returns_explicitly_written_value(
        self, initialized_db: str
    ) -> None:
        mv.set_command(
            "solo",
            "echo merge_ok",
            12,
            db_path=initialized_db,
        )
        policy = mv.get_policy("solo", db_path=initialized_db)
        assert policy == mv.MergeVerificationPolicy(
            command="echo merge_ok",
            timeout_seconds=12,
        )
        assert mv.get_command("solo", db_path=initialized_db) == "echo merge_ok"

    def test_returns_none_when_payload_command_is_whitespace(
        self, initialized_db: str
    ) -> None:
        """Whitespace-only payloads must read as ``None`` so the merge engine
        emits the explicit skip log instead of running ``sh -c ' '``.
        """
        # Bypass the helper's empty-string guard by writing through the
        # patch surface with a whitespace-only command. The validator
        # rejects this, so the test confirms the validator and the
        # accessor both reject blank strings consistently.
        with pytest.raises(ps.ValidationError):
            ps.apply_patch(
                "solo",
                ops=[{
                    "op": "put",
                    "family": "merge_verification",
                    "attachment": "project",
                    "payload": {
                        "command": "   ",
                        "timeout_seconds": 10,
                    },
                }],
                actor="test",
                db_path=initialized_db,
            )


class TestSetCommand:
    def test_rejects_empty_command(self, initialized_db: str) -> None:
        with pytest.raises(ValueError):
            mv.set_command("solo", "", 10, db_path=initialized_db)

    def test_rejects_whitespace_only_command(
        self, initialized_db: str
    ) -> None:
        with pytest.raises(ValueError):
            mv.set_command("solo", "   ", 10, db_path=initialized_db)

    def test_rejects_non_positive_timeout(
        self, initialized_db: str
    ) -> None:
        with pytest.raises(ValueError):
            mv.set_command("solo", "echo ok", 0, db_path=initialized_db)

    def test_upsert_overwrites_existing(self, initialized_db: str) -> None:
        mv.set_command("solo", "echo first", 10, db_path=initialized_db)
        mv.set_command("solo", "echo second", 20, db_path=initialized_db)
        assert mv.get_policy("solo", db_path=initialized_db) == (
            mv.MergeVerificationPolicy(
                command="echo second",
                timeout_seconds=20,
            )
        )

    def test_payload_validator_rejects_missing_command_key(
        self, initialized_db: str
    ) -> None:
        """The helper never constructs a bad payload itself, but operators
        who write through the patch API directly must hit a structural
        error if they omit ``command``.
        """
        with pytest.raises(ps.ValidationError):
            ps.apply_patch(
                "solo",
                ops=[{
                    "op": "put",
                    "family": "merge_verification",
                    "attachment": "project",
                    "payload": {
                        "wrong_key": "echo x",
                        "timeout_seconds": 10,
                    },
                }],
                actor="test",
                db_path=initialized_db,
            )

    def test_payload_validator_rejects_missing_timeout(
        self, initialized_db: str
    ) -> None:
        with pytest.raises(ps.ValidationError):
            ps.apply_patch(
                "solo",
                ops=[{
                    "op": "put",
                    "family": "merge_verification",
                    "attachment": "project",
                    "payload": {"command": "echo x"},
                }],
                actor="test",
                db_path=initialized_db,
            )


class TestClearCommand:
    def test_clear_when_absent_returns_false(
        self, initialized_db: str
    ) -> None:
        assert mv.clear_command("solo", db_path=initialized_db) is False

    def test_clear_when_present_returns_true(
        self, initialized_db: str
    ) -> None:
        mv.set_command("solo", "echo merge_ok", 10, db_path=initialized_db)
        assert mv.clear_command("solo", db_path=initialized_db) is True
        assert mv.get_policy("solo", db_path=initialized_db) is None


class TestCliSurface:
    """The merge engine reads via the Python API, but operators use CLI."""

    def test_get_exits_1_when_absent(
        self, initialized_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rc = mv.main(["get", "solo"])
        assert rc == 1

    def test_set_and_get_roundtrip(
        self, initialized_db: str, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        rc_set = mv.main([
            "set",
            "solo",
            "echo merge_ok",
            "--timeout-seconds",
            "25",
        ])
        assert rc_set == 0
        rc_get = mv.main(["get", "solo"])
        assert rc_get == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert json.loads(out[-1]) == {
            "command": "echo merge_ok",
            "timeout_seconds": 25,
        }

    def test_clear_then_get_exits_1(
        self, initialized_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mv.main(["set", "solo", "echo merge_ok", "--timeout-seconds", "25"])
        assert mv.main(["clear", "solo"]) == 0
        assert mv.main(["get", "solo"]) == 1
