# ruff: noqa: F811 -- imported pytest fixtures are injected by name

"""Validation mutation requires its own retained, audited restore point."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from runtime.api.domain.migration_apply_test_helpers import (
    _audit_row, _seed_apply_item, apply_env,  # noqa: F401 -- fixture registration
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 -- fixture registration
from yoke_core.domain import migration_apply_rehearse as runner
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV


def _run(env):
    return runner.rehearse(
        5001, session_id="test-session", control_db_path=env["control_db"],
        worktree_path=env["worktree"],
    )


def test_one_exact_private_baseline_covers_batch_and_all_verification(
    apply_env, monkeypatch,
):
    modules = apply_env["modules_dir"]
    (modules / "other_migration.py").write_text((modules / "sample_migration.py").read_text())
    _seed_apply_item(
        apply_env["control_db"], item_id=5001,
        modules=["sample_migration", "other_migration"], rehearsal_commands=["verify-copy"],
    )
    monkeypatch.setenv(RESTORE_POINT_ENV, "authority-pitr-must-not-be-used")
    establish = Mock(wraps=runner.establish)
    monkeypatch.setattr(runner, "establish", establish)
    seen = []
    verified_modules = []
    dispatch = runner.dispatch_handle

    def assert_archive(operation, identifier):
        archive = Path(os.environ[RESTORE_POINT_ENV])
        assert archive.parent == apply_env["worktree"] / ".yoke" / "backups"
        assert archive.is_file() and archive.stat().st_size > 0
        assert archive.stat().st_mode & 0o777 == 0o600
        assert archive.parent.stat().st_mode & 0o777 == 0o700
        with _conn(apply_env["control_db"]) as control:
            row = control.execute(
                "SELECT backup_path FROM migration_audit "
                "WHERE migration_name = %s ORDER BY id DESC LIMIT 1", (identifier,),
            ).fetchone()
        assert row[0] == str(archive)  # A different connection sees the committed receipt.
        seen.append((operation, str(archive)))

    def load(**kwargs):
        handle = dispatch(**kwargs)

        def apply(conn):
            assert_archive("apply", handle.identifier)
            handle.apply(conn)

        def invariants(conn):
            assert_archive("invariants", handle.identifier)
            handle.invariants(conn)

        return replace(handle, apply=apply, invariants=invariants)

    monkeypatch.setattr(runner, "dispatch_handle", load)

    def verify(commands, **kwargs):
        assert commands == ["verify-copy"]
        assert kwargs["env_var"] == "YOKE_PG_DSN"
        assert kwargs["validation_db_path"] == apply_env["validation_dsn"]
        assert kwargs["cwd"] == apply_env["worktree"]
        verified_modules.append(kwargs["module_identifier"])
        assert_archive("commands", kwargs["module_identifier"])
        return [], None

    monkeypatch.setattr(runner, "_run_rehearsal_commands", verify)
    result = _run(apply_env)

    assert result.all_succeeded
    assert verified_modules == ["sample_migration", "other_migration"]
    establish.assert_called_once()
    assert establish.call_args.kwargs == {
        "backup_root": apply_env["worktree"] / ".yoke" / "backups",
        "backup_target_dsn": apply_env["validation_dsn"],
        "external_restore_point": None,
    }
    assert apply_env["validation_dsn"] != apply_env["authoritative_db"]
    assert [operation for operation, _ in seen] == ["apply", "invariants", "commands"] * 2
    archives = {path for _, path in seen}
    assert len(archives) == 1
    archive = Path(archives.pop())
    assert archive.is_file() and archive.stat().st_size > 0
    assert os.environ[RESTORE_POINT_ENV] == "authority-pitr-must-not-be-used"
    assert {
        _audit_row(apply_env["control_db"], attempt.audit_id)["backup_path"]
        for attempt in result.modules
    } == {str(archive)}


@pytest.mark.parametrize("failure", ("missing", "empty", "dump-error"))
def test_archive_failure_refuses_before_module_dispatch(apply_env, monkeypatch, failure):
    _seed_apply_item(apply_env["control_db"], item_id=5001)
    archive = apply_env["worktree"] / ".yoke" / "backups" / "failed.sql"
    if failure == "empty":
        archive.touch()
    establish = Mock(return_value=str(archive))
    if failure == "dump-error":
        establish.side_effect = RuntimeError("archive creation failed")
    monkeypatch.setattr(runner, "establish", establish)
    dispatch = Mock()
    monkeypatch.setattr(runner, "dispatch_handle", dispatch)
    leave = Mock(wraps=runner.migration_territory_claim.leave)
    monkeypatch.setattr(runner.migration_territory_claim, "leave", leave)

    with pytest.raises((MigrationApplyError, RuntimeError)):
        _run(apply_env)

    dispatch.assert_not_called()
    leave.assert_called_once()
    assert leave.call_args.args[2] == "rehearsal-backup-failed"


@pytest.mark.parametrize("receipt", ("absent", "wrong-path", "write-error"))
def test_backup_receipt_must_persist_before_apply(apply_env, monkeypatch, receipt):
    _seed_apply_item(apply_env["control_db"], item_id=5001)
    writers = runner.receipt_writers

    def incomplete_writers(conn):
        insert, update = writers(conn)

        def write(audit_id, state, *, extra=None):
            if extra and "backup_path" in extra:
                if receipt == "write-error":
                    raise RuntimeError("receipt unavailable")
                extra = {} if receipt == "absent" else {"backup_path": "different.sql"}
            return update(audit_id, state, extra=extra)

        return insert, write

    monkeypatch.setattr(runner, "receipt_writers", incomplete_writers)
    dispatch = Mock()
    monkeypatch.setattr(runner, "dispatch_handle", dispatch)
    result = _run(apply_env)

    assert not result.all_succeeded
    dispatch.assert_not_called()
    assert len(list((apply_env["worktree"] / ".yoke" / "backups").glob("*.sql"))) == 1
    assert result.modules[0].error in (
        "validation restore-point receipt was not persisted", "receipt unavailable",
    )


def test_author_commands_inherit_the_retained_restore_point(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from yoke_core.domain import migration_apply_verify
    from yoke_core.domain.migration_restore_point import named_restore_point

    archive = tmp_path / "validation.sql"
    archive.write_text("baseline")
    seen = []

    def run(command, **kwargs):
        env = kwargs["env"]
        seen.append((command, env[RESTORE_POINT_ENV], env["YOKE_DB"], env["YOKE_PG_DSN"]))
        return SimpleNamespace(returncode=0, stdout="counts only", stderr="")

    monkeypatch.setattr(migration_apply_verify.subprocess, "run", run)
    monkeypatch.setattr(migration_apply_verify, "_rehearsal_command_timeout_seconds", lambda: 10)
    with named_restore_point(archive):
        outcomes, error = migration_apply_verify.run_rehearsal_commands(
            ["verify-copy"], env_var="YOKE_PG_DSN", validation_db_path="fixture-copy",
            module_identifier="sample_migration",
            cwd=tmp_path,
        )
    assert error is None and outcomes[0]["returncode"] == 0
    assert seen == [("verify-copy", str(archive), "fixture-copy", "fixture-copy")]
    assert archive.is_file()


def test_archive_disappearance_refuses_the_next_module(apply_env, monkeypatch):
    modules = apply_env["modules_dir"]
    (modules / "other_migration.py").write_text((modules / "sample_migration.py").read_text())
    _seed_apply_item(
        apply_env["control_db"], item_id=5001,
        modules=["sample_migration", "other_migration"], rehearsal_commands=["verify-copy"],
    )
    dispatch = Mock(wraps=runner.dispatch_handle)
    monkeypatch.setattr(runner, "dispatch_handle", dispatch)

    def lose_archive(*args, **kwargs):
        Path(os.environ[RESTORE_POINT_ENV]).unlink()
        return [], None

    monkeypatch.setattr(runner, "_run_rehearsal_commands", lose_archive)
    result = _run(apply_env)
    assert not result.all_succeeded
    assert dispatch.call_count == 1
    assert result.modules[1].error == "validation restore-point archive is missing or empty"
