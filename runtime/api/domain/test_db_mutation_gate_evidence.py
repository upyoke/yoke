"""db_mutation_gate — stamp/clear helpers and evidence gate.

Split out of ``test_db_mutation_gate.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.migration_model_test import (
    TEST_MIGRATION_MODULES_DIR as DEFAULT_MODULES_DIR,
)
from pathlib import Path

import pytest

from yoke_core.domain.db_mutation_gate import (
    check_implementing_to_reviewing_implementation_gate,
    clear_attestation_frozen_at,
    stamp_attestation_frozen_at,
)
from runtime.api.domain.db_mutation_gate_test_helpers import (
    _seed_capability,
    _seed_project,
    _write_module,
    gate_db_context,
    seed_audit_row,
)
from yoke_core.domain.migration_model_capability import (
    RECIPE_WEBAPP_SQLITE_EMPTY,
    RUNNER_KIND_GOVERNED_MODULE,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.migration_model_test import (
    governed_postgres_test_seed,
    membership_ledger_test_seed,
)


@pytest.fixture
def gate_db(tmp_path: Path):
    with gate_db_context(tmp_path) as (conn, repo_path):
        yield conn, repo_path


class TestStampClear:
    def test_stamp_writes_then_idempotent(self, gate_db) -> None:
        conn, _ = gate_db
        insert_item(
            conn,
            id=1,
            project="yoke",
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

    def test_new_stamp_uses_canonical_microseconds(self, gate_db, monkeypatch) -> None:
        from yoke_contracts import timestamps

        conn, _ = gate_db
        clock = timestamps.parse_instant("1969-12-31T23:59:59.123456Z")
        monkeypatch.setattr(timestamps, "utc_now", lambda: clock)
        insert_item(conn, id=1, project="yoke", db_compatibility_attestation="{}")
        stamp = stamp_attestation_frozen_at(1, conn=conn)
        assert stamp == "1969-12-31T23:59:59.123456Z"
        stored = json.loads(
            conn.execute(
                "SELECT db_compatibility_attestation FROM items WHERE id=1",
            ).fetchone()[0]
        )
        assert stored["frozen_at"] == stamp

    @pytest.mark.parametrize(
        "stamp",
        [
            "2026-04-22T17:52:49Z",
            "2024-02-29T00:00:00.1Z",
            "1969-12-31T23:59:59.123456Z",
        ],
    )
    def test_restamp_preserves_frozen_json_identity(self, gate_db, stamp) -> None:
        from yoke_core.domain.db_compatibility_attestation import canonical_json

        conn, _ = gate_db
        raw = canonical_json({"frozen_at": stamp, "invariants": ["frozen evidence"]})
        insert_item(conn, id=1, project="yoke", db_compatibility_attestation=raw)
        assert stamp_attestation_frozen_at(1, conn=conn) == stamp
        assert (
            conn.execute(
                "SELECT db_compatibility_attestation FROM items WHERE id=1",
            ).fetchone()[0]
            == raw
        )

    def test_invalid_existing_stamp_refuses_before_write(self, gate_db) -> None:
        from yoke_core.domain.db_compatibility_attestation import (
            DbCompatibilityAttestationError,
        )

        conn, _ = gate_db
        raw = json.dumps({"frozen_at": "2026-02-30T00:00:00Z"})
        insert_item(conn, id=1, project="yoke", db_compatibility_attestation=raw)
        with pytest.raises(DbCompatibilityAttestationError, match="invalid_instant"):
            stamp_attestation_frozen_at(1, conn=conn)
        assert (
            conn.execute(
                "SELECT db_compatibility_attestation FROM items WHERE id=1",
            ).fetchone()[0]
            == raw
        )

    def test_stamp_appends_escalations(self, gate_db) -> None:
        conn, _ = gate_db
        insert_item(
            conn,
            id=2,
            project="yoke",
            db_compatibility_attestation="{}",
        )
        stamp_attestation_frozen_at(
            2,
            conn=conn,
            extra_escalations=[
                {
                    "from": "pre_merge_safe",
                    "to": "pre_merge_breaking",
                    "reason": "scanner: drop_table",
                    "source": "scanner",
                    "observed_at": "2026-04-23T00:00:00Z",
                },
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
            conn,
            id=3,
            project="yoke",
            db_compatibility_attestation=json.dumps(
                {"frozen_at": "2026-04-23T00:00:00Z"}
            ),
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
            conn,
            id=4,
            project="yoke",
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
                            "ledger": membership_ledger_test_seed(),
                        },
                    },
                },
            },
        }

    def _stage_apply(self, gate_db, identifier: str = "demo_module") -> int:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        _seed_capability(conn, "yoke", governed_postgres_test_seed())
        modules_dir = DEFAULT_MODULES_DIR
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
            conn,
            id=4242,
            project="yoke",
            status="implementing",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        return 4242

    def test_state_none_passes(self, gate_db) -> None:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        insert_item(conn, id=1, project="yoke", status="implementing")
        outcome = check_implementing_to_reviewing_implementation_gate(
            1,
            conn=conn,
        )
        assert outcome.passed

    def test_apply_missing_audit_blocks(self, gate_db) -> None:
        conn, _ = gate_db
        item_id = self._stage_apply(gate_db)
        outcome = check_implementing_to_reviewing_implementation_gate(
            item_id,
            conn=conn,
        )
        assert not outcome.passed
        assert any("no passing rehearsal receipt" in e for e in outcome.errors)

    def test_apply_with_rehearsed_state_passes(self, gate_db) -> None:
        conn, repo_path = gate_db
        item_id = self._stage_apply(gate_db)
        seed_audit_row(
            repo_path,
            columns="migration_name, state, project_id, model_name, started_at",
            placeholders="?, 'rehearsed', ?, 'primary', ?",
            values=("demo_module", 1, "2026-04-23T00:00:00Z"),
        )
        outcome = check_implementing_to_reviewing_implementation_gate(
            item_id,
            conn=conn,
        )
        assert outcome.passed, outcome.errors

    def test_apply_uses_project_configured_webapp_python_model(self, gate_db) -> None:
        conn, repo_path = gate_db
        identifier = "001_create_accounts"
        _seed_project(conn, "externalwebapp", repo_path)
        _seed_capability(conn, "externalwebapp", self._externalwebapp_webapp_seed())
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
            conn,
            id=4343,
            project="externalwebapp",
            status="implementing",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        # The model's authority is a project-local SQLite file the control
        # plane never opens. The receipt is item evidence and lives on the
        # control plane that holds the item, which is where the gate reads it.
        seed_audit_row(
            repo_path,
            columns="migration_name, state, project_id, model_name, started_at",
            placeholders="?, 'rehearsed', ?, 'primary', ?",
            values=(identifier, 2, "2026-04-23T00:00:00Z"),
        )

        outcome = check_implementing_to_reviewing_implementation_gate(
            4343,
            conn=conn,
        )

        assert outcome.passed, outcome.errors

    def test_apply_unrehearsed_state_still_blocks(self, gate_db) -> None:
        # A row that never reached rehearsal is not evidence. States at or
        # past ``rehearsed`` count; earlier ones do not.
        conn, repo_path = gate_db
        item_id = self._stage_apply(gate_db)
        seed_audit_row(
            repo_path,
            columns=(
                "migration_name, state, project_id, model_name, "
                "backup_path, tables_declared, expected_deltas, "
                "pre_row_counts, started_at"
            ),
            placeholders=("?, 'planned', ?, 'primary', '', '[]', '{}', '{}', ?"),
            values=("demo_module", 1, "2026-04-23T00:00:00Z"),
        )
        outcome = check_implementing_to_reviewing_implementation_gate(
            item_id,
            conn=conn,
        )
        assert not outcome.passed
        assert any("no passing rehearsal receipt" in e for e in outcome.errors)
