"""db_mutation_gate — stamp/clear helpers and evidence gate.

Split out of ``test_db_mutation_gate.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.db_mutation_gate import (
    check_implementing_to_reviewing_implementation_gate,
    clear_attestation_frozen_at,
    stamp_attestation_frozen_at,
)
from yoke_core.domain.db_mutation_gate_test_helpers import (
    _seed_capability,
    _seed_flow_with_migration_apply,
    _seed_project,
    _write_decision_record,
    _write_module,
    ensure_audit_table,
    gate_audit_path,
    gate_db_context,
    seed_audit_row,
)
from yoke_core.domain.migration_model_capability import (
    RECIPE_WEBAPP_SQLITE_EMPTY,
    RUNNER_KIND_GOVERNED_MODULE,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed


@pytest.fixture
def gate_db(tmp_path: Path):
    with gate_db_context(tmp_path) as (conn, repo_path):
        yield conn, repo_path


class TestStampClear:
    def test_stamp_writes_then_idempotent(self, gate_db) -> None:
        conn, _ = gate_db
        insert_item(
            conn, id=1, project="yoke",
            db_compatibility_attestation="{}",
        )
        stamp1 = stamp_attestation_frozen_at(1, conn=conn)
        stamp2 = stamp_attestation_frozen_at(1, conn=conn)
        assert stamp1 == stamp2
        row = conn.execute(
            "SELECT db_compatibility_attestation FROM items WHERE id=1",
        ).fetchone()
        parsed = json.loads(row[0])
        assert parsed["frozen_at"] == stamp1

    def test_stamp_appends_escalations(self, gate_db) -> None:
        conn, _ = gate_db
        insert_item(
            conn, id=2, project="yoke",
            db_compatibility_attestation="{}",
        )
        stamp_attestation_frozen_at(
            2, conn=conn,
            extra_escalations=[
                {"from": "pre_merge_safe", "to": "pre_merge_breaking",
                 "reason": "scanner: drop_table",
                 "source": "scanner",
                 "observed_at": "2026-04-23T00:00:00Z"},
            ],
        )
        parsed = json.loads(
            conn.execute(
                "SELECT db_compatibility_attestation FROM items WHERE id=2",
            ).fetchone()[0]
        )
        assert parsed["class_escalations"][0]["source"] == "scanner"

    def test_clear_removes_stamp(self, gate_db) -> None:
        conn, _ = gate_db
        insert_item(
            conn, id=3, project="yoke",
            db_compatibility_attestation=json.dumps({"frozen_at": "2026-04-23T00:00:00Z"}),
        )
        cleared = clear_attestation_frozen_at(3, conn=conn)
        assert cleared
        parsed = json.loads(
            conn.execute(
                "SELECT db_compatibility_attestation FROM items WHERE id=3",
            ).fetchone()[0]
        )
        assert "frozen_at" not in parsed

    def test_clear_returns_false_when_no_stamp(self, gate_db) -> None:
        conn, _ = gate_db
        insert_item(
            conn, id=4, project="yoke",
            db_compatibility_attestation="{}",
        )
        assert clear_attestation_frozen_at(4, conn=conn) is False


class TestEvidenceGate:
    def _externalwebapp_webapp_seed(self) -> dict:
        return {
            "default_model": "primary",
            "models": {
                "primary": {
                    "authoritative_db": {
                        "kind": "sqlite_file",
                        "location": {"path": "app/data/app.db"},
                    },
                    "validation_surface": {
                        "kind": "worktree_local_sqlite",
                        "provisioning": {
                            "path": ".yoke/validation.db",
                            "recipe": RECIPE_WEBAPP_SQLITE_EMPTY,
                        },
                    },
                    "runner": {
                        "kind": RUNNER_KIND_GOVERNED_MODULE,
                        "config": {
                            "modules_dir": "app/db/migrations",
                            "connection_env_var": "APP_DB_PATH",
                        },
                    },
                },
            },
        }

    def _stage_apply(self, gate_db, identifier: str = "demo_module") -> int:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        _seed_capability(conn, "yoke", governed_postgres_test_seed())
        _seed_flow_with_migration_apply(conn, "yoke")
        modules_dir = "runtime/api/domain/migrations"
        _write_module(repo_path, modules_dir, identifier)
        profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": [identifier],
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "additive_only",
        }
        insert_item(
            conn, id=4242, project="yoke", status="implementing",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        return 4242

    def _audit_path(self, gate_db) -> str:
        # The gate's items+audit database is one per-test DB (see
        # gate_db_context). migration_audit already exists there; the path token
        # matches init_test_db's db_path so the gate's own connection lands on
        # the same database on both backends.
        _conn, repo_path = gate_db
        return gate_audit_path(repo_path)

    def test_state_none_passes(self, gate_db) -> None:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        insert_item(conn, id=1, project="yoke", status="implementing")
        outcome = check_implementing_to_reviewing_implementation_gate(
            1, conn=conn,
        )
        assert outcome.passed

    def test_apply_missing_audit_blocks(self, gate_db) -> None:
        conn, _ = gate_db
        item_id = self._stage_apply(gate_db)
        audit_path = self._audit_path(gate_db)
        outcome = check_implementing_to_reviewing_implementation_gate(
            item_id, conn=conn, audit_db_path=audit_path,
        )
        assert not outcome.passed
        assert any("no migration_audit row" in e for e in outcome.errors)

    def test_apply_with_completed_state_passes(self, gate_db) -> None:
        conn, repo_path = gate_db
        item_id = self._stage_apply(gate_db)
        audit_path = self._audit_path(gate_db)
        seed_audit_row(
            repo_path,
            columns="migration_name, state, project_id, model_name, started_at",
            placeholders="?, 'completed', ?, 'primary', ?",
            values=("demo_module", 1, "2026-04-23T00:00:00Z"),
        )
        outcome = check_implementing_to_reviewing_implementation_gate(
            item_id, conn=conn, audit_db_path=audit_path,
        )
        assert outcome.passed, outcome.errors

    def test_apply_uses_project_configured_webapp_python_model(
        self, gate_db
    ) -> None:
        conn, repo_path = gate_db
        identifier = "001_create_accounts"
        _seed_project(conn, "externalwebapp", repo_path)
        _seed_capability(conn, "externalwebapp", self._externalwebapp_webapp_seed())
        _seed_flow_with_migration_apply(conn, "externalwebapp")
        _write_module(repo_path, "app/db/migrations", identifier)
        profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": [identifier],
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "additive_only",
        }
        insert_item(
            conn, id=4343, project="externalwebapp", status="implementing",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        # This test does not pass audit_db_path: the gate resolves the
        # authoritative DB from the externalwebapp capability config (app/data/app.db).
        # On SQLite the gate opens that file, so migration_audit must exist
        # there; on Postgres db_helpers.connect ignores the path and reaches the
        # per-test DSN database (table already present, ensure is a no-op).
        audit_path = repo_path / "app" / "data" / "app.db"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        ensure_audit_table(str(audit_path))
        seed_audit_row(
            repo_path,
            columns="migration_name, state, project_id, model_name, started_at",
            placeholders="?, 'completed', ?, 'primary', ?",
            values=(identifier, 2, "2026-04-23T00:00:00Z"),
            audit_path=str(audit_path),
        )

        outcome = check_implementing_to_reviewing_implementation_gate(
            4343, conn=conn,
        )

        assert outcome.passed, outcome.errors

    def test_apply_non_completed_state_still_blocks(self, gate_db) -> None:
        # Only ``state='completed'`` satisfies the evidence gate. Rows
        # stuck in earlier states (rehearsed / live_applied) do not.
        conn, repo_path = gate_db
        item_id = self._stage_apply(gate_db)
        audit_path = self._audit_path(gate_db)
        seed_audit_row(
            repo_path,
            columns=(
                "migration_name, state, project_id, model_name, "
                "backup_path, tables_declared, expected_deltas, "
                "pre_row_counts, started_at"
            ),
            placeholders=(
                "?, 'live_applied', ?, 'primary', "
                "'', '[]', '{}', '{}', ?"
            ),
            values=("demo_module", 1, "2026-04-23T00:00:00Z"),
        )
        outcome = check_implementing_to_reviewing_implementation_gate(
            item_id, conn=conn, audit_db_path=audit_path,
        )
        assert not outcome.passed
        assert any("no migration_audit row" in e for e in outcome.errors)

    def test_retire_missing_record_blocks(self, gate_db) -> None:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        _seed_capability(conn, "yoke", governed_postgres_test_seed())
        _seed_flow_with_migration_apply(conn, "yoke")
        profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "retire",
            "migration_modules": ["dead_module"],
            "compatibility_class": "pre_merge_breaking",
        }
        insert_item(
            conn, id=7, project="yoke", status="implementing",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        outcome = check_implementing_to_reviewing_implementation_gate(
            7, conn=conn,
        )
        assert not outcome.passed
        assert any("missing decision record" in e for e in outcome.errors)

    def test_retire_record_present_passes(self, gate_db) -> None:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        _seed_capability(conn, "yoke", governed_postgres_test_seed())
        _seed_flow_with_migration_apply(conn, "yoke")
        _write_decision_record(repo_path, "dead_module")
        profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "retire",
            "migration_modules": ["dead_module"],
            "compatibility_class": "pre_merge_breaking",
        }
        insert_item(
            conn, id=8, project="yoke", status="implementing",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        outcome = check_implementing_to_reviewing_implementation_gate(
            8, conn=conn,
        )
        assert outcome.passed, outcome.errors

    def test_retire_record_wrong_model_blocks(self, gate_db) -> None:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        _seed_capability(conn, "yoke", governed_postgres_test_seed())
        _seed_flow_with_migration_apply(conn, "yoke")
        _write_decision_record(
            repo_path, "dead_module", model_name="other",
        )
        profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "retire",
            "migration_modules": ["dead_module"],
            "compatibility_class": "pre_merge_breaking",
        }
        insert_item(
            conn, id=9, project="yoke", status="implementing",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        outcome = check_implementing_to_reviewing_implementation_gate(
            9, conn=conn,
        )
        assert not outcome.passed
        assert any("model_name" in e for e in outcome.errors)
