"""Planned path-claim coverage for rehearsal-command dry runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from yoke_core.domain import attestation_rehearsal_dryrun as dryrun
from yoke_core.domain.attestation_rehearsal_dryrun import (
    validate_attestation_rehearsal_commands,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _declared_profile() -> Dict[str, object]:
    return {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": "apply",
        "migration_modules": ["future_index"],
    }


def _attestation(rehearsal_commands: List[str]) -> Dict[str, object]:
    return {
        "frozen_at": "2026-05-24T00:00:00Z",
        "pre_merge_readers_writers": "n/a",
        "invariants": "n/a",
        "rehearsal_commands": rehearsal_commands,
        "residual_risk_notes": "n/a",
    }


@pytest.fixture
def conn(tmp_path, monkeypatch):
    def _apply_schema() -> None:
        from yoke_core.domain import db_backend

        seeded = db_backend.connect()
        try:
            execute_schema_script(
                seeded,
                """
                CREATE TABLE items (
                  id INTEGER PRIMARY KEY,
                  project_id INTEGER,
                  project_sequence INTEGER,
                  db_mutation_profile TEXT,
                  db_compatibility_attestation TEXT
                );
                CREATE TABLE path_claims (
                  id INTEGER PRIMARY KEY,
                  item_id INTEGER,
                  state TEXT
                );
                CREATE TABLE path_claim_targets (
                  claim_id INTEGER NOT NULL,
                  target_id INTEGER NOT NULL
                );
                CREATE TABLE path_targets (
                  id INTEGER PRIMARY KEY,
                  path_string TEXT,
                  materialization_state TEXT NOT NULL DEFAULT 'observed'
                );
                """
            )
            seeded.commit()
        finally:
            seeded.close()

    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        seeded = connect_test_db(db_path)
        monkeypatch.setattr(dryrun, "_resolve_repo_root", lambda: _REPO_ROOT)
        try:
            yield seeded
        finally:
            seeded.close()


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_item(conn: Any, item_id: int, command: str) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO items (id, project_id, project_sequence, "
        "db_mutation_profile, db_compatibility_attestation) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (
            item_id,
            1,
            item_id,
            json.dumps(_declared_profile()),
            json.dumps(_attestation([command])),
        ),
    )
    conn.commit()


def _claim_path(
    conn: Any,
    item_id: int,
    path: str,
    *,
    claim_state: str = "planned",
    materialization_state: str = "planned",
) -> None:
    claim_id = item_id * 10
    target_id = item_id * 100
    p = _p(conn)
    conn.execute(
        f"INSERT INTO path_claims (id, item_id, state) VALUES ({p}, {p}, {p})",
        (claim_id, item_id, claim_state),
    )
    conn.execute(
        "INSERT INTO path_targets "
        f"(id, path_string, materialization_state) VALUES ({p}, {p}, {p})",
        (target_id, path, materialization_state),
    )
    conn.execute(
        f"INSERT INTO path_claim_targets (claim_id, target_id) VALUES ({p}, {p})",
        (claim_id, target_id),
    )
    conn.commit()


class TestPlannedPathClaimTokens:
    def test_missing_planned_claim_path_passes(self, conn) -> None:
        path = "runtime/api/domain/migrations/test_future_index.py"
        _seed_item(conn, 1, f"{sys.executable} -m pytest {path} -q")
        _claim_path(conn, 1, path)

        outcomes = validate_attestation_rehearsal_commands(conn, 1)

        assert len(outcomes) == 1
        assert outcomes[0].passed is True
        assert outcomes[0].failure_reason == ""

    def test_missing_unclaimed_path_still_fails(self, conn) -> None:
        path = "runtime/api/domain/migrations/test_unclaimed_future.py"
        _seed_item(conn, 2, f"{sys.executable} -m pytest {path} -q")

        outcomes = validate_attestation_rehearsal_commands(conn, 2)

        assert len(outcomes) == 1
        assert outcomes[0].passed is False
        assert outcomes[0].failure_reason == "missing_path"
        assert outcomes[0].failure_token == path

    def test_missing_observed_claim_path_still_fails(self, conn) -> None:
        path = "runtime/api/domain/migrations/test_observed_missing.py"
        _seed_item(conn, 3, f"{sys.executable} -m pytest {path} -q")
        _claim_path(conn, 3, path, materialization_state="observed")

        outcomes = validate_attestation_rehearsal_commands(conn, 3)

        assert len(outcomes) == 1
        assert outcomes[0].passed is False
        assert outcomes[0].failure_reason == "missing_path"

    def test_placeholder_still_fails_for_planned_claim_path(self, conn) -> None:
        path = "runtime/api/domain/migrations/test_future_index.py"
        _seed_item(conn, 4, f"{sys.executable} -m pytest <worktree>/{path} -q")
        _claim_path(conn, 4, path)

        outcomes = validate_attestation_rehearsal_commands(conn, 4)

        assert len(outcomes) == 1
        assert outcomes[0].passed is False
        assert outcomes[0].failure_reason == "unresolved_placeholder"
