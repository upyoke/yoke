# ruff: noqa: F811 -- imported pytest fixtures are injected by name

"""Rehearsal names its disposable copy without archiving it."""

from __future__ import annotations

from dataclasses import replace
import os
from unittest.mock import Mock

import pytest

from runtime.api.domain.migration_apply_test_helpers import (
    _audit_row, _seed_apply_item, apply_env,  # noqa: F401 -- fixture registration
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 -- fixture registration
from yoke_core.domain import migration_apply_rehearse as runner
from yoke_core.domain import migration_restore_point
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV


def _run(env):
    return runner.rehearse(
        5001, session_id="test-session", control_db_path=env["control_db"],
        worktree_path=env["worktree"],
    )


def test_validation_copy_covers_batch_and_nested_applies_without_dumps(
    apply_env, monkeypatch, tmp_path,
):
    modules = apply_env["modules_dir"]
    (modules / "other_migration.py").write_text((modules / "sample_migration.py").read_text())
    _seed_apply_item(
        apply_env["control_db"], item_id=5001,
        modules=["sample_migration", "other_migration"], rehearsal_commands=["verify-copy"],
    )
    monkeypatch.setenv(RESTORE_POINT_ENV, "authority-pitr-must-not-be-used")
    from yoke_contracts.machine_config.runtime import yoke_home
    from yoke_core.domain import migration_apply_targets

    dump = Mock(side_effect=AssertionError("rehearsal must not dump"))
    monkeypatch.setattr(migration_apply_targets, "dump_postgres_to_directory", dump)
    home_backups = yoke_home() / "backups"
    previous_backups = set(home_backups.glob("*"))
    seen = []
    verified_modules = []
    dispatch = runner.dispatch_handle

    def assert_copy(operation, identifier, conn=None):
        restore_point = os.environ[RESTORE_POINT_ENV]
        assert restore_point.startswith("validation-copy:postgres-validation:")
        with _conn(apply_env["control_db"]) as control:
            row = control.execute(
                "SELECT backup_path FROM migration_audit "
                "WHERE migration_name = %s ORDER BY id DESC LIMIT 1", (identifier,),
            ).fetchone()
        assert row[0] == ""
        if conn is not None:
            root, external = migration_restore_point.configured_restore_point()
            assert root is None and external == restore_point
            assert migration_restore_point.establish(
                conn, backup_root=root, external_restore_point=external,
            ) == restore_point
        seen.append((operation, restore_point))

    def load(**kwargs):
        handle = dispatch(**kwargs)

        def apply(conn):
            assert_copy("apply", handle.identifier, conn)
            handle.apply(conn)

        def invariants(conn):
            assert_copy("invariants", handle.identifier, conn)
            handle.invariants(conn)

        return replace(handle, apply=apply, invariants=invariants)

    monkeypatch.setattr(runner, "dispatch_handle", load)

    def verify(commands, **kwargs):
        assert commands == ["verify-copy"]
        assert kwargs["cwd"] == apply_env["worktree"]
        assert kwargs["env_var"] == "YOKE_PG_DSN"
        assert kwargs["validation_db_path"] == apply_env["validation_dsn"]
        verified_modules.append(kwargs["module_identifier"])
        assert_copy("commands", kwargs["module_identifier"])
        return [], None

    monkeypatch.setattr(runner, "_run_rehearsal_commands", verify)
    result = _run(apply_env)

    assert result.all_succeeded
    assert verified_modules == ["sample_migration", "other_migration"]
    assert [operation for operation, _ in seen] == ["apply", "invariants", "commands"] * 2
    assert len({point for _, point in seen}) == 1
    assert os.environ[RESTORE_POINT_ENV] == "authority-pitr-must-not-be-used"
    assert {
        (_audit_row(apply_env["control_db"], attempt.audit_id)["state"],
         _audit_row(apply_env["control_db"], attempt.audit_id)["backup_path"])
        for attempt in result.modules
    } == {("rehearsed", "")}
    assert not list((apply_env["worktree"] / ".yoke" / "backups").iterdir())
    assert set(home_backups.glob("*")) == previous_backups
    dump.assert_not_called()


def test_count_failure_releases_lease_before_dispatch(apply_env, monkeypatch):
    _seed_apply_item(apply_env["control_db"], item_id=5001)
    monkeypatch.setattr(runner, "_row_count_map", Mock(side_effect=RuntimeError("unavailable")))
    dispatch = Mock()
    monkeypatch.setattr(runner, "dispatch_handle", dispatch)
    leave = Mock(wraps=runner.migration_territory_claim.leave)
    monkeypatch.setattr(runner.migration_territory_claim, "leave", leave)

    with pytest.raises(MigrationApplyError):
        _run(apply_env)

    dispatch.assert_not_called()
    leave.assert_called_once()
    assert leave.call_args.args[2] == "rehearsal-counts-failed"


def test_author_commands_inherit_the_validation_copy(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from yoke_core.domain import migration_apply_verify
    from yoke_core.domain.migration_restore_point import named_restore_point

    seen = []

    def run(command, **kwargs):
        env = kwargs["env"]
        seen.append((command, env[RESTORE_POINT_ENV], env["YOKE_DB"], env["YOKE_PG_DSN"]))
        return SimpleNamespace(returncode=0, stdout="counts only", stderr="")

    monkeypatch.setattr(migration_apply_verify.subprocess, "run", run)
    monkeypatch.setattr(migration_apply_verify, "_rehearsal_command_timeout_seconds", lambda: 10)
    with named_restore_point("validation-copy:fixture-copy"):
        outcomes, error = migration_apply_verify.run_rehearsal_commands(
            ["verify-copy"], env_var="YOKE_PG_DSN", validation_db_path="fixture-copy",
            module_identifier="sample_migration", cwd=tmp_path,
        )
    assert error is None and outcomes[0]["returncode"] == 0
    assert seen == [("verify-copy", "validation-copy:fixture-copy", "fixture-copy", "fixture-copy")]
