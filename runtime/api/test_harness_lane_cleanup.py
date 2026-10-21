"""Lane settings are owned by managed paths, without a provenance ledger."""

import json
from pathlib import Path

import pytest

from yoke_contracts.harness_lane_cleanup import cleanup_lane_configs


@pytest.fixture
def configs(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    lane = root / ".worktrees" / "retired"
    codex = tmp_path / "home/.codex/config.toml"
    codex.parent.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(codex.parent.parent))
    monkeypatch.setenv("CODEX_HOME", str(codex.parent))
    claude = codex.parent.parent / ".claude.json"
    cursor = codex.parent.parent / ".cursor/projects/lane/.workspace-trusted"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(json.dumps({"workspacePath": str(lane), "trustedAt": "then"}))
    claude.write_text(
        json.dumps(
            {
                "projects": {
                    str(lane): {"hasTrustDialogAccepted": True, "metadata": "lane"},
                    str(root): {"hasTrustDialogAccepted": True},
                    "unrelated": {"keep": True},
                }
            }
        )
    )
    codex.write_text(f'''# preserve comments
[projects."{lane}"]
trust_level = "trusted"
[projects."{lane}".settings]
custom = true
[projects."{root}"]
trust_level = "trusted"
[hooks.state."{lane}/.codex/hooks.json:SessionStart:0:0"]
trusted_hash = "lane"
[hooks.state."{root}/.codex/hooks.json:SessionStart:0:0"]
trusted_hash = "main"
''')
    return root, lane, codex, claude, cursor


def test_sweep_backups_preserves_live_and_outside_paths_and_is_idempotent(configs):
    root, lane, codex, claude, cursor = configs
    before = {path: path.read_bytes() for path in (codex, claude, cursor)}
    preview = cleanup_lane_configs(
        managed_roots=(root / ".worktrees",), dry_run=True, keep_backup=True
    )
    assert preview["ok"]
    assert len(preview["files"]) == 3
    assert all(path.read_bytes() == body for path, body in before.items())
    assert not list(root.parent.rglob("*.yoke-backup-*"))
    applied = cleanup_lane_configs(
        managed_roots=(root / ".worktrees",), keep_backup=True
    )
    assert applied["ok"]
    assert len(applied["files"]) == 3
    for row in applied["files"]:
        target = Path(row["file"])
        assert Path(row["backup"]).read_bytes() == before[target]
        assert row["before_bytes"] == len(before[target])
    assert not cursor.exists()
    assert str(lane) not in claude.read_text()
    assert str(root) in claude.read_text()
    assert str(lane) not in codex.read_text()
    assert f'[projects."{root}"]' in codex.read_text()
    assert "# preserve comments" in codex.read_text()
    assert (
        cleanup_lane_configs(managed_roots=(root / ".worktrees",), keep_backup=True)[
            "files"
        ]
        == []
    )


def test_live_lane_is_preserved_until_exact_retirement(configs):
    root, lane, codex, claude, cursor = configs
    lane.mkdir(parents=True)
    assert cleanup_lane_configs(managed_roots=(root / ".worktrees",))["files"] == []
    assert cleanup_lane_configs(checkout=lane)["ok"]
    assert not cursor.exists()
    assert str(lane) not in codex.read_text()
    assert str(lane) not in claude.read_text()


def test_retired_path_settings_are_owned_without_a_ledger(configs):
    root, lane, codex, claude, cursor = configs
    codex.write_text(
        codex.read_text().replace(
            'trust_level = "trusted"', 'trust_level = "untrusted"'
        )
    )
    result = cleanup_lane_configs(managed_roots=(root / ".worktrees",))
    assert result["ok"]
    assert str(lane) not in codex.read_text()
    assert str(lane) not in claude.read_text()
    assert f'[projects."{root}"]\ntrust_level = "untrusted"' in codex.read_text()


def test_failure_preserves_config_but_other_harnesses_continue(configs):
    root, lane, codex, claude, cursor = configs
    codex.write_text("invalid TOML [")
    before = codex.read_bytes()
    result = cleanup_lane_configs(checkout=lane)
    assert not result["ok"]
    failures = [row for row in result["files"] if "error" in row]
    assert len(failures) == 1
    assert failures[0]["error"] == "harness_lane_config_cleanup_failed"
    assert "yoke harness lane-config sweep" in failures[0]["recovery"]
    assert codex.read_bytes() == before
    assert str(lane) not in claude.read_text()
    assert not cursor.exists()


def test_backup_failure_does_not_edit_config(configs, monkeypatch):
    from yoke_contracts import harness_lane_config_edit as edit

    root, lane, codex, claude, cursor = configs
    before = {path: path.read_bytes() for path in (codex, claude, cursor)}
    monkeypatch.setattr(
        edit, "backup", lambda path: (_ for _ in ()).throw(OSError("read-only"))
    )
    result = cleanup_lane_configs(
        managed_roots=(root / ".worktrees",), keep_backup=True
    )
    assert not result["ok"]
    assert all(path.read_bytes() == body for path, body in before.items())


def test_fixture_roots_and_sibling_prefix_boundary(configs, tmp_path):
    root, lane, codex, claude, cursor = configs
    fixture_root = tmp_path / "fixtures"
    fixture = fixture_root / "run/project"
    outside = tmp_path / "fixtures-operator/project"
    codex.write_text(
        codex.read_text()
        + f'''\n[projects."{fixture}"]
trust_level = "trusted"
[projects."{outside}"]
trust_level = "trusted"
'''
    )
    result = cleanup_lane_configs(managed_roots=(fixture_root,))
    assert result["ok"]
    assert str(fixture) not in codex.read_text()
    assert str(outside) in codex.read_text()
    assert str(lane) in codex.read_text()


def test_atomic_codex_edit_does_not_overwrite_external_writer(tmp_path):
    from yoke_contracts.codex_hook_trust_toml import CodexHookTrustStoreError, mutate

    config = tmp_path / "config.toml"
    config.write_text('model = "original"\n')

    def concurrent_writer(text, document):
        config.write_text('model = "operator"\n')
        return 'model = "stale-writer"\n', None

    with pytest.raises(CodexHookTrustStoreError, match="codex_config_changed"):
        mutate(config, concurrent_writer)
    assert config.read_text() == 'model = "operator"\n'


def test_registered_worktree_retirement_cleans_every_harness(configs):
    import subprocess
    from yoke_core.engines.worktree_removal import remove_worktree

    root, lane, codex, claude, cursor = configs
    for args in [
        ["init", "-q", "-b", "main"],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "initial",
        ],
        ["worktree", "add", "-q", "-b", "retired", str(lane)],
    ]:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    result = remove_worktree(root, lane)
    assert result.removed, result.reason
    assert not lane.exists()
    assert str(lane) not in codex.read_text()
    assert str(lane) not in claude.read_text()
    assert not cursor.exists()
