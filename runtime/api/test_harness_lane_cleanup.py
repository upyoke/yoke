"""Lane settings are owned by managed paths, without a provenance ledger."""

from yoke_contracts.testing.real_home_isolation import set_home

import json
from pathlib import Path

import pytest

from yoke_contracts.harness_lane_cleanup import cleanup_lane_configs


@pytest.mark.parametrize("format", ["toml", "json"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_cleanup_receipts_count_exact_utf8_bytes(tmp_path, format, newline):
    from yoke_contracts.harness_lane_config_edit import edit_codex, edit_json

    config = tmp_path / f"config.{format}"
    if format == "toml":
        text = '# café\n[projects."/retired"]\ntrust_level = "trusted"\n[projects."/live"]\ntrust_level = "trusted"\n'
        edit = edit_codex
        expected = '# café\n[projects."/live"]\ntrust_level = "trusted"\n'.replace("\n", newline).encode("utf-8")
    else:
        document = {"projects": {"/retired": {}, "/live": {}}, "note": "café"}
        text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        edit = edit_json
        del document["projects"]["/retired"]
        expected = (json.dumps(document, indent=2) + "\n").encode("utf-8")
    before = text.replace("\n", newline).encode("utf-8")
    config.write_bytes(before)

    preview = edit(config, lambda key: key == "/retired", dry_run=True, keep_backup=True)
    assert config.read_bytes() == before
    assert preview["before_bytes"] == len(before)
    assert preview["after_bytes"] == len(expected)
    result = edit(config, lambda key: key == "/retired", dry_run=False, keep_backup=True)
    assert config.read_bytes() == expected
    assert Path(result["backup"]).read_bytes() == before
    assert result["before_bytes"] == len(before)
    assert result["after_bytes"] == len(expected)


def test_codex_atomic_edit_detects_line_ending_only_external_change(tmp_path):
    from yoke_contracts.codex_hook_trust_toml import CodexHookTrustStoreError, mutate

    config = tmp_path / "config.toml"
    original = b'model = "original"\r\n'
    config.write_bytes(original)

    def concurrent_writer(text, document):
        assert text.encode("utf-8") == original
        config.write_bytes(b'model = "original"\n')
        return 'model = "stale-writer"\n', None

    with pytest.raises(CodexHookTrustStoreError, match="codex_config_changed"):
        mutate(config, concurrent_writer)
    assert config.read_bytes() == b'model = "original"\n'


@pytest.fixture
def configs(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    lane = root / ".worktrees" / "retired"
    codex = tmp_path / "home/.codex/config.toml"
    codex.parent.mkdir(parents=True)
    set_home(monkeypatch, str(codex.parent.parent))
    monkeypatch.setenv("CODEX_HOME", str(codex.parent))
    claude = codex.parent.parent / ".claude.json"
    cursor = codex.parent.parent / ".cursor/projects/lane/.workspace-trusted"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(json.dumps({"workspacePath": str(lane), "trustedAt": "then"}), encoding="utf-8", newline="\n")
    claude.write_text(
        json.dumps(
            {
                "projects": {
                    str(lane): {"hasTrustDialogAccepted": True, "metadata": "lane"},
                    str(root): {"hasTrustDialogAccepted": True},
                    "unrelated": {"keep": True},
                }
            }
        ), encoding="utf-8", newline="\n"
    )
    codex.write_text(f'''# preserve comments
[projects.{json.dumps(str(lane))}]
trust_level = "trusted"
[projects.{json.dumps(str(lane))}.settings]
custom = true
[projects.{json.dumps(str(root))}]
trust_level = "trusted"
[hooks.state.{json.dumps(str(lane) + "/.codex/hooks.json:SessionStart:0:0")}]
trusted_hash = "lane"
[hooks.state.{json.dumps(str(root) + "/.codex/hooks.json:SessionStart:0:0")}]
trusted_hash = "main"
''', encoding="utf-8", newline="\n")
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
    assert json.dumps(str(lane))[1:-1] not in claude.read_text(encoding="utf-8")
    assert json.dumps(str(root))[1:-1] in claude.read_text(encoding="utf-8")
    assert json.dumps(str(lane))[1:-1] not in codex.read_text(encoding="utf-8")
    assert f'[projects.{json.dumps(str(root))}]' in codex.read_text(encoding="utf-8")
    assert "# preserve comments" in codex.read_text(encoding="utf-8")
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
    assert json.dumps(str(lane))[1:-1] not in codex.read_text(encoding="utf-8")
    assert json.dumps(str(lane))[1:-1] not in claude.read_text(encoding="utf-8")


def test_retired_path_settings_are_owned_without_a_ledger(configs):
    root, lane, codex, claude, cursor = configs
    codex.write_text(
        codex.read_text(encoding="utf-8").replace(
            'trust_level = "trusted"', 'trust_level = "untrusted"'
        ), encoding="utf-8", newline="\n"
    )
    result = cleanup_lane_configs(managed_roots=(root / ".worktrees",))
    assert result["ok"]
    assert json.dumps(str(lane))[1:-1] not in codex.read_text(encoding="utf-8")
    assert json.dumps(str(lane))[1:-1] not in claude.read_text(encoding="utf-8")
    assert f'[projects.{json.dumps(str(root))}]\ntrust_level = "untrusted"' in codex.read_text(encoding="utf-8")


def test_failure_preserves_config_but_other_harnesses_continue(configs):
    root, lane, codex, claude, cursor = configs
    codex.write_text("invalid TOML [", encoding="utf-8", newline="\n")
    before = codex.read_bytes()
    result = cleanup_lane_configs(checkout=lane)
    assert not result["ok"]
    failures = [row for row in result["files"] if "error" in row]
    assert len(failures) == 1
    assert failures[0]["error"] == "harness_lane_config_cleanup_failed"
    assert "yoke harness lane-config sweep" in failures[0]["recovery"]
    assert codex.read_bytes() == before
    assert json.dumps(str(lane))[1:-1] not in claude.read_text(encoding="utf-8")
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
        codex.read_text(encoding="utf-8")
        + f'''\n[projects.{json.dumps(str(fixture))}]
trust_level = "trusted"
[projects.{json.dumps(str(outside))}]
trust_level = "trusted"
''', encoding="utf-8", newline="\n"
    )
    result = cleanup_lane_configs(managed_roots=(fixture_root,))
    assert result["ok"]
    assert json.dumps(str(fixture))[1:-1] not in codex.read_text(encoding="utf-8")
    assert json.dumps(str(outside))[1:-1] in codex.read_text(encoding="utf-8")
    assert json.dumps(str(lane))[1:-1] in codex.read_text(encoding="utf-8")


def test_atomic_codex_edit_does_not_overwrite_external_writer(tmp_path):
    from yoke_contracts.codex_hook_trust_toml import CodexHookTrustStoreError, mutate

    config = tmp_path / "config.toml"
    config.write_text('model = "original"\n', encoding="utf-8", newline="\n")

    def concurrent_writer(text, document):
        config.write_text('model = "operator"\n', encoding="utf-8", newline="\n")
        return 'model = "stale-writer"\n', None

    with pytest.raises(CodexHookTrustStoreError, match="codex_config_changed"):
        mutate(config, concurrent_writer)
    assert config.read_text(encoding="utf-8") == 'model = "operator"\n'


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
    assert json.dumps(str(lane))[1:-1] not in codex.read_text(encoding="utf-8")
    assert json.dumps(str(lane))[1:-1] not in claude.read_text(encoding="utf-8")
    assert not cursor.exists()


def test_shared_json_config_symlink_is_preserved(configs):
    root, lane, codex, claude, cursor = configs
    physical = claude.with_name("physical-claude.json")
    claude.rename(physical)
    claude.symlink_to(physical.name)
    result = cleanup_lane_configs(
        managed_roots=(root / ".worktrees",), keep_backup=True
    )
    assert result["ok"]
    assert claude.is_symlink()
    assert json.dumps(str(lane))[1:-1] not in physical.read_text(encoding="utf-8")
    row = next(row for row in result["files"] if row["harness"] == "claude-code")
    assert Path(row["backup"]).parent == physical.parent
    assert json.dumps(str(lane))[1:-1] in Path(row["backup"]).read_text(encoding="utf-8")


def test_json_edit_records_a_left_lock_sidecar_and_revert_removes_it(
    tmp_path, monkeypatch
):
    from yoke_contracts import harness_settings_ledger, harness_settings_revert
    from yoke_contracts.harness_lane_config_edit import edit_json

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({"projects": {"/retired": {}, "/live": {}}}))
    lock_path = tmp_path.resolve() / "..claude.json.yoke.lock"
    original_unlink = Path.unlink

    def keep_lock(self, *args, **kwargs):
        if self.name == lock_path.name:
            raise PermissionError("simulated unremovable lock")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", keep_lock)
    edit_json(config, lambda key: key == "/retired", dry_run=False, keep_backup=False)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert lock_path.exists()
    assert harness_settings_ledger.read() == [
        harness_settings_ledger.created_file_entry(lock_path)
    ]
    harness_settings_revert.revert_recorded()
    assert not lock_path.exists()
