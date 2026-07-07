"""Tests for the two-unit apply contract — rehearsal unit.

Original module covered every flavor of the apply contract. It is now split
across sibling files so each authored file stays under the 350-line limit:
this file covers the rehearsal happy path and rehearsal failure branches.
Live-apply happy path/refusal lives in ``test_migration_apply_live`` and the
live-verify failure recovery + profile gating lives in
``test_migration_apply_failure``. Heavy fixture/helper code lives in
``migration_apply_test_helpers``.
"""

from __future__ import annotations

import json
import sys

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.migration_apply import (
    FAIL_TEST_APPLY,
    FAIL_TEST_VERIFY,
    RehearseResult,
    STATE_REHEARSED,
    rehearse,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    _NO_APPLY_MIGRATION_BODY,
    _RAISING_MIGRATION_BODY,
    _audit_row,
    _connect_validation_db,
    _seed_apply_item,
    apply_env,
)
from yoke_core.domain.migration_apply_resolve import ModuleOverrideResolution
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures


class TestDbTargets:
    def test_postgres_target_connects_with_native_psycopg(self, monkeypatch) -> None:
        from yoke_core.domain import migration_apply_targets as targets
        from yoke_core.domain.migration_apply_targets import DbTarget, connect_db_target

        sentinel = object()
        monkeypatch.setattr(targets.db_backend, "connect_psycopg", lambda dsn: sentinel)

        target = DbTarget(kind="postgres", target="dbname=test", display="postgres:test")
        assert connect_db_target(target) is sentinel

    def test_sqlite_rollback_backup_fails_closed(self, tmp_path) -> None:
        from yoke_core.domain.migration_apply_contract import MigrationApplyError
        from yoke_core.domain.migration_apply_targets import (
            DbTarget,
            create_rollback_backup,
        )

        target = DbTarget(
            kind="sqlite_file",
            target=str(tmp_path / "app.db"),
            display="app.db",
        )
        with pytest.raises(MigrationApplyError) as excinfo:
            create_rollback_backup(target, "pre-live-apply-demo", worktree_path=tmp_path)

        msg = str(excinfo.value)
        assert "SQLite rollback backups" in msg
        assert "yoke_core.domain.backup" in msg
        assert "Postgres" in msg


class TestRehearseHappyPath:
    def test_rehearse_creates_audit_row_with_rehearsed_state(self, apply_env) -> None:
        _seed_apply_item(apply_env["control_db"], item_id=5001)
        result = rehearse(
            5001,
            session_id="test-session",
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        assert isinstance(result, RehearseResult)
        assert result.all_succeeded
        assert len(result.modules) == 1
        mod = result.modules[0]
        assert mod.state == STATE_REHEARSED
        assert mod.audit_id is not None
        row = _audit_row(apply_env["authoritative_db"], mod.audit_id)
        assert row["state"] == STATE_REHEARSED
        assert row["source_fingerprint"] is not None
        assert row["rehearsed_at"] is not None
        assert row["model_name"] == "primary"
        assert row["project_id"] == 1
        assert row["session_id"] == "test-session"
        assert row["test_copy_path"].startswith("postgres-validation:")

    def test_rehearse_applies_module_to_validation_db_only(self, apply_env) -> None:
        _seed_apply_item(apply_env["control_db"], item_id=5002)
        rehearse(
            5002,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        # Validation DB has the table, authoritative DB does not.
        with _connect_validation_db(apply_env) as val:
            val_has = _table_exists(val, "widgets")
        with db_backend.connect_psycopg(apply_env["authoritative_db"]) as auth:
            auth_has = _table_exists(auth, "widgets")
        assert val_has
        assert not auth_has

    def test_rehearse_captures_fingerprint_of_authoritative_db(self, apply_env) -> None:
        from yoke_core.domain.schema_fingerprint import fingerprint_kind

        conn = db_backend.connect_psycopg(apply_env["authoritative_db"])
        try:
            expected = fingerprint_kind("postgres", conn)
        finally:
            conn.close()
        _seed_apply_item(apply_env["control_db"], item_id=5003)
        result = rehearse(
            5003,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        assert result.source_fingerprint == expected

    def test_cli_override_uses_resolved_worktree_for_both_units(
        self, monkeypatch, tmp_path,
    ) -> None:
        from yoke_core.domain import migration_apply as cli

        class Result:
            item_id = 7000
            model_name = "primary"
            validation_db_path = "validation.db"
            authoritative_db_path = "authoritative.db"
            lease_id = "lease-1"
            modules = []
            source_fingerprint = None
            rehearsed_at = None
            all_succeeded = True

        worktree = tmp_path / "feature"
        module_path = worktree / "runtime" / "migrations" / "sample.py"
        module_path.parent.mkdir(parents=True)
        module_path.write_text("def apply(conn): pass\n", encoding="utf-8")
        item_id = 7000
        resolution = ModuleOverrideResolution(
            module_path=module_path, slug="sample", source_path=module_path,
            worktree_path=worktree, item_id=item_id,
        )
        seen = []
        monkeypatch.setattr(
            cli, "_resolve_override_from_cli",
            lambda item_id, requested: resolution,
        )

        def fake_unit(item_id, *, module_override=None, worktree_path=None):
            seen.append((item_id, module_override, worktree_path))
            return Result()

        monkeypatch.setattr(cli, "rehearse", fake_unit)
        monkeypatch.setattr(cli, "live_apply", fake_unit)
        args = [f"YOK-{item_id}", "--module-path-override", str(module_path)]
        assert cli.main(["rehearse", *args]) == 0
        assert cli.main(["live-apply", *args]) == 0
        assert seen == [(item_id, resolution, worktree), (item_id, resolution, worktree)]


class TestRehearseFailures:
    def test_missing_module_marks_test_apply_failed(self, apply_env) -> None:
        _seed_apply_item(
            apply_env["control_db"], item_id=5010,
            modules=["nonexistent_module"],
        )
        result = rehearse(
            5010,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        mod = result.modules[0]
        assert not mod.succeeded
        assert mod.state == FAIL_TEST_APPLY
        assert "not found" in mod.error

    def test_module_without_apply_marks_test_apply_failed(self, apply_env) -> None:
        (apply_env["modules_dir"] / "no_apply_module.py").write_text(
            _NO_APPLY_MIGRATION_BODY, encoding="utf-8",
        )
        _seed_apply_item(
            apply_env["control_db"], item_id=5011,
            modules=["no_apply_module"],
        )
        result = rehearse(
            5011,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        mod = result.modules[0]
        assert mod.state == FAIL_TEST_APPLY
        assert "apply(conn)" in mod.error

    def test_module_apply_raises_marks_test_apply_failed(self, apply_env) -> None:
        (apply_env["modules_dir"] / "raising_module.py").write_text(
            _RAISING_MIGRATION_BODY, encoding="utf-8",
        )
        _seed_apply_item(
            apply_env["control_db"], item_id=5012,
            modules=["raising_module"],
        )
        result = rehearse(
            5012,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        mod = result.modules[0]
        assert mod.state == FAIL_TEST_APPLY
        assert "synthetic module.apply() failure" in mod.error

    def test_invariants_raise_marks_test_verify_failed(self, apply_env) -> None:
        # Seed the tripwire into the validation DB so the module's
        # invariants() raises after apply.
        with _connect_validation_db(apply_env) as val:
            val.execute("CREATE TABLE IF NOT EXISTS trip_invariants (id INTEGER)")
            val.commit()
        _seed_apply_item(apply_env["control_db"], item_id=5013)
        result = rehearse(
            5013,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        mod = result.modules[0]
        assert mod.state == FAIL_TEST_VERIFY
        assert "invariant tripwire table present" in mod.error

    def test_failing_rehearsal_command_marks_test_verify_failed(self, apply_env) -> None:
        _seed_apply_item(
            apply_env["control_db"], item_id=5014,
            rehearsal_commands=["exit 1"],
        )
        result = rehearse(
            5014,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        mod = result.modules[0]
        assert mod.state == FAIL_TEST_VERIFY
        assert "rehearsal command failed" in mod.error

    def test_rehearsal_commands_outcomes_append_to_attestation(self, apply_env) -> None:
        _seed_apply_item(
            apply_env["control_db"], item_id=5015,
            rehearsal_commands=["echo ok"],
        )
        rehearse(
            5015,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        conn = db_backend.connect_psycopg(apply_env["authoritative_db"])
        try:
            row = conn.execute(
                "SELECT db_compatibility_attestation FROM items WHERE id = %s",
                (5015,),
            ).fetchone()
        finally:
            conn.close()
        attestation = json.loads(row[0])
        outcomes = attestation.get("rehearsal_outcomes") or []
        assert len(outcomes) == 1
        assert outcomes[0]["command"] == "echo ok"
        assert outcomes[0]["returncode"] == 0

    def test_rehearsal_command_timeout_reads_config(self, monkeypatch, tmp_path):
        from yoke_core.domain import migration_apply_verify as verify
        from yoke_core.domain import runtime_settings

        monkeypatch.setattr(
            runtime_settings,
            "get_seconds",
            lambda key, default, *, config_path=None: (
                2 if key == verify.REHEARSAL_COMMAND_TIMEOUT_CONFIG else default
            ),
        )

        outcomes, error = verify._run_rehearsal_commands(
            [
                f"{sys.executable} -c "
                "\"import time; time.sleep(0.1); print('done')\""
            ],
            env_var="YOKE_DB",
            validation_db_path=str(tmp_path / "validation.db"),
            cwd=tmp_path,
        )

        assert error is None
        assert outcomes[0]["returncode"] == 0
        assert "done" in outcomes[0]["stdout"]

    def test_rehearsal_command_timeout_stderr_names_deadline(
        self, monkeypatch, tmp_path,
    ):
        from yoke_core.domain import migration_apply_verify as verify
        from yoke_core.domain import runtime_settings

        monkeypatch.setattr(
            runtime_settings,
            "get_seconds",
            lambda key, default, *, config_path=None: (
                1 if key == verify.REHEARSAL_COMMAND_TIMEOUT_CONFIG else default
            ),
        )

        outcomes, error = verify._run_rehearsal_commands(
            [f"{sys.executable} -c \"import time; time.sleep(2)\""],
            env_var="YOKE_DB",
            validation_db_path=str(tmp_path / "validation.db"),
            cwd=tmp_path,
        )

        assert "rehearsal command timed out" in error
        assert outcomes[0]["returncode"] == -1
        assert outcomes[0]["stderr"] == "timeout after 1s"
