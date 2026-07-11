"""Committed-manifest coverage for itemless governed migration apply."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401
from yoke_core.domain import db_backend, json_helper, migration_apply_live
from yoke_core.domain.migration_apply import main
from yoke_core.domain.migration_apply_manifest import (
    MigrationManifestError,
    assert_rehearsal_subject_consistent,
    resolve_manifest_subject,
)
from yoke_core.domain.migration_apply_manifest_units import (
    live_apply_manifest,
    rehearse_manifest,
)
from yoke_core.domain.migration_apply_test_helpers import (  # noqa: F401
    _audit_row,
    apply_env,
)
from yoke_core.domain.schema_common import _table_exists


_MANIFEST_REL = Path("runtime/api/domain/migrations/sample_migration.migration.json")


def _manifest() -> dict:
    return {
        "version": 1,
        "project": "yoke",
        "profile": {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["sample_migration"],
            "compatibility_class": "pre_merge_safe",
            "migration_strategy": "additive_only",
            "schema_kinds": ["additive"],
            "data_kinds": [],
            "affected_surfaces": [
                {"table": "widgets", "columns": ["id", "name"]}
            ],
            "count_preserving": True,
        },
        "attestation": {
            "pre_merge_readers_writers": [
                {
                    "path": "runtime/api/domain/migrations/sample_migration.py",
                    "symbol": "apply",
                    "role": "writer",
                }
            ],
            "invariants": ["widgets exists after apply"],
            "rehearsal_commands": ["python3 -c 'print(\"manifest-rehearsal\")'"],
            "residual_risk_notes": "Synthetic manifest fixture.",
        },
    }


@pytest.fixture
def manifest_env(apply_env):
    root = apply_env["worktree"]
    (root / ".gitignore").write_text(
        ".yoke/\n__pycache__/\n", encoding="utf-8"
    )
    manifest = root / _MANIFEST_REL
    json_helper.dump_path(manifest, _manifest())
    _git(root, "init")
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Yoke Test",
        "-c",
        "user.email=yoke-test@example.com",
        "commit",
        "-m",
        "Seed governed migration manifest",
    )
    apply_env["manifest"] = manifest
    return apply_env


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_manifest_rehearse_and_live_apply_without_item(manifest_env) -> None:
    control = _conn(manifest_env["control_db"])
    try:
        before_items = control.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        control.close()

    rehearsed = rehearse_manifest(
        _MANIFEST_REL,
        worktree_path=manifest_env["worktree"],
        session_id="manifest-rehearse",
        control_db_path=manifest_env["control_db"],
    )
    assert rehearsed.item_id is None
    assert rehearsed.all_succeeded
    audit_id = rehearsed.modules[0].audit_id
    row = _audit_row(manifest_env["authoritative_db"], audit_id)
    assert "manifest_source_commit=" in row["description"]
    assert "manifest_sha256=" in row["description"]

    applied = live_apply_manifest(
        _MANIFEST_REL,
        worktree_path=manifest_env["worktree"],
        session_id="manifest-live",
        control_db_path=manifest_env["control_db"],
    )
    assert applied.item_id is None
    assert applied.all_succeeded
    with db_backend.connect_psycopg(manifest_env["authoritative_db"]) as conn:
        assert _table_exists(conn, "widgets")

    control = _conn(manifest_env["control_db"])
    try:
        after_items = control.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        control.close()
    assert after_items == before_items
    assert (manifest_env["worktree"] / "runtime/api/domain/migrations/sample_migration.py").is_file()


def test_live_apply_refuses_changed_manifest_source(manifest_env) -> None:
    rehearse_manifest(
        _MANIFEST_REL,
        worktree_path=manifest_env["worktree"],
        control_db_path=manifest_env["control_db"],
    )
    changed = _manifest()
    changed["attestation"]["residual_risk_notes"] = "Changed after rehearsal."
    json_helper.dump_path(manifest_env["manifest"], changed)
    _git(manifest_env["worktree"], "add", _MANIFEST_REL.as_posix())
    _git(
        manifest_env["worktree"],
        "-c",
        "user.name=Yoke Test",
        "-c",
        "user.email=yoke-test@example.com",
        "commit",
        "-m",
        "Change governed migration manifest",
    )

    with pytest.raises(MigrationManifestError, match="differs from rehearsal"):
        live_apply_manifest(
            _MANIFEST_REL,
            worktree_path=manifest_env["worktree"],
            control_db_path=manifest_env["control_db"],
        )


def test_manifest_resolution_refuses_dirty_worktree(manifest_env) -> None:
    manifest_env["manifest"].write_text("{}\n", encoding="utf-8")
    control = _conn(manifest_env["control_db"])
    try:
        with pytest.raises(MigrationManifestError, match="clean source worktree"):
            resolve_manifest_subject(
                control,
                manifest_path=_MANIFEST_REL,
                worktree_path=manifest_env["worktree"],
            )
    finally:
        control.close()


def test_manifest_resolution_refuses_untracked_source(manifest_env) -> None:
    untracked = manifest_env["worktree"] / "untracked.migration.json"
    json_helper.dump_path(untracked, _manifest())
    _git(manifest_env["worktree"], "add", "untracked.migration.json")
    _git(
        manifest_env["worktree"],
        "-c",
        "user.name=Yoke Test",
        "-c",
        "user.email=yoke-test@example.com",
        "commit",
        "-m",
        "Track alternate manifest",
    )
    _git(manifest_env["worktree"], "rm", "--cached", "untracked.migration.json")
    _git(
        manifest_env["worktree"],
        "-c",
        "user.name=Yoke Test",
        "-c",
        "user.email=yoke-test@example.com",
        "commit",
        "-m",
        "Untrack alternate manifest",
    )
    (manifest_env["worktree"] / ".git/info/exclude").write_text(
        "untracked.migration.json\n", encoding="utf-8"
    )
    control = _conn(manifest_env["control_db"])
    try:
        with pytest.raises(MigrationManifestError, match="not tracked at HEAD"):
            resolve_manifest_subject(
                control,
                manifest_path=Path("untracked.migration.json"),
                worktree_path=manifest_env["worktree"],
            )
    finally:
        control.close()


def test_manifest_resolution_refuses_tracked_module_symlink(manifest_env) -> None:
    module = (
        manifest_env["worktree"]
        / "runtime/api/domain/migrations/sample_migration.py"
    )
    target = module.with_name("sample_migration_target.py")
    target.write_text(module.read_text(encoding="utf-8"), encoding="utf-8")
    module.unlink()
    module.symlink_to(target.name)
    _git(manifest_env["worktree"], "add", "-A")
    _git(
        manifest_env["worktree"],
        "-c",
        "user.name=Yoke Test",
        "-c",
        "user.email=yoke-test@example.com",
        "commit",
        "-m",
        "Replace migration source with a symlink",
    )

    control = _conn(manifest_env["control_db"])
    try:
        with pytest.raises(MigrationManifestError, match="must not be a symlink"):
            resolve_manifest_subject(
                control,
                manifest_path=_MANIFEST_REL,
                worktree_path=manifest_env["worktree"],
            )
    finally:
        control.close()


def test_live_revalidates_source_after_backup(manifest_env, monkeypatch) -> None:
    rehearse_manifest(
        _MANIFEST_REL,
        worktree_path=manifest_env["worktree"],
        control_db_path=manifest_env["control_db"],
    )
    module = (
        manifest_env["worktree"]
        / "runtime/api/domain/migrations/sample_migration.py"
    )

    def mutate_source_during_backup(*args, **kwargs) -> str:
        module.write_text(
            module.read_text(encoding="utf-8") + "\nSOURCE_CHANGED = True\n",
            encoding="utf-8",
        )
        _git(
            manifest_env["worktree"],
            "add",
            "runtime/api/domain/migrations/sample_migration.py",
        )
        _git(
            manifest_env["worktree"],
            "-c",
            "user.name=Yoke Test",
            "-c",
            "user.email=yoke-test@example.com",
            "commit",
            "-m",
            "Change migration source during backup",
        )
        return str(manifest_env["worktree"] / ".yoke/backups/test.dump")

    monkeypatch.setattr(
        migration_apply_live, "create_rollback_backup", mutate_source_during_backup
    )
    result = live_apply_manifest(
        _MANIFEST_REL,
        worktree_path=manifest_env["worktree"],
        control_db_path=manifest_env["control_db"],
    )

    assert not result.all_succeeded
    assert "changed after subject resolution" in (result.modules[0].error or "")


def test_cli_help_lists_manifest_units(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "rehearse-manifest" in output
    assert "live-apply-manifest" in output


def test_item_live_cannot_consume_manifest_rehearsal() -> None:
    with pytest.raises(MigrationManifestError, match="item-backed live apply"):
        assert_rehearsal_subject_consistent(
            identifier="sample_migration",
            audit_description=(
                "two-unit apply contract (governed); "
                "manifest_source_commit=0123456789012345678901234567890123456789"
            ),
            subject=None,
        )
