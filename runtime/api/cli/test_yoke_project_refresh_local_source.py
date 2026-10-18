"""Clean-room proofs for explicit source-dev/admin project refresh."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from yoke_cli.project_install.managed_git_hooks import GIT_HOOK_NAMES
from yoke_cli.main import main as cli_main
from yoke_cli.project_install import git_hooks as git_hooks_layer


from runtime.api.cli.project_refresh_test_support import (
    REPO_ROOT,
    _git_init,
    _project_tree,
    _seed_manifest,
)


def test_preview_reports_changes_without_target_writes(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    before = _project_tree(target)

    rc = cli_main(
        [
            "project",
            "refresh",
            str(target),
            "--source-checkout",
            str(REPO_ROOT),
            "--project-id",
            "41",
            "--project-slug",
            "preview-project",
            "--json",
        ]
    )

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["preview"] is True
    assert report["source_dev_admin"] is True
    assert report["target_writes"] is False
    assert report["server_state_writes"] is False
    assert report["snapshot_sync"]["status"] == "skipped"
    assert report["files_would_write"]
    assert report["git_hooks_would_install_or_update"] == len(GIT_HOOK_NAMES)
    assert report["worktrees_ignore"]["would_add"] is True
    assert _project_tree(target) == before
    assert not (target / ".yoke/install-manifest.json").exists()


def test_preview_reports_discarded_inert_legacy_records(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    _seed_manifest(target, 50)
    manifest_path = target / ".yoke/install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract_path = ".legacy/project.config"
    strategy_path = ".legacy/planning/MISSION.md"
    manifest["contract_files"][contract_path] = "4" * 64
    manifest["strategy_files"][strategy_path] = "5" * 64
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    before = _project_tree(target)

    rc = cli_main(
        [
            "project",
            "refresh",
            str(target),
            "--source-checkout",
            str(REPO_ROOT),
            "--project-id",
            "50",
            "--json",
        ]
    )

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["prior_contract_records_discarded"] == [contract_path]
    assert report["prior_strategy_records_discarded"] == [strategy_path]
    assert report["target_writes"] is False
    assert _project_tree(target) == before


def test_source_preview_rejects_malformed_settings_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    settings = target / ".claude/settings.json"
    settings.parent.mkdir()
    settings.write_text("{not json", encoding="utf-8")
    before = _project_tree(target)

    rc = cli_main(
        [
            "project",
            "refresh",
            str(target),
            "--source-checkout",
            str(REPO_ROOT),
            "--project-id",
            "48",
            "--project-slug",
            "malformed-settings",
            "--json",
        ]
    )

    assert rc == 1
    # Which preflight refuses first depends on the harness CLIs on PATH;
    # every refusal names the malformed file.
    assert str(settings) in capsys.readouterr().err
    assert _project_tree(target) == before


def test_apply_then_second_run_is_idempotent(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    _seed_manifest(target, 42)
    args = [
        "project",
        "refresh",
        str(target),
        "--source-checkout",
        str(REPO_ROOT),
        "--project-id",
        "42",
        "--force",
        "--no-commit",
        "--apply",
        "--json",
    ]

    assert cli_main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["preview"] is False
    assert first["files_written"]
    assert first["machine_config_newly_registered"] is False
    assert first["snapshot_sync"]["status"] == "skipped"
    assert (target / ".yoke/install-manifest.json").is_file()
    assert (target / ".claude/skills/yoke/SKILL.md").is_file()
    first_tree = _project_tree(target)

    assert cli_main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["files_written"] == []
    assert second["files_pruned"] == []
    assert second["hooks_added"] == {}
    assert _project_tree(target) == first_tree


def test_preview_reports_non_file_convergence_when_source_files_unchanged(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    _seed_manifest(target, 49)
    base = [
        "project",
        "refresh",
        str(target),
        "--source-checkout",
        str(REPO_ROOT),
        "--project-id",
        "49",
        "--json",
    ]
    assert cli_main([*base[:-1], "--force", "--no-commit", "--apply", "--json"]) == 0
    capsys.readouterr()

    settings_path = target / ".claude/settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["hooks"]["PreToolUse"].pop()
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    pre_commit = target / ".git/hooks/pre-commit"
    stale_shim = git_hooks_layer.PRE_COMMIT_SHIM.replace(
        "# Hard-fails",
        "# stale source copy\n# Hard-fails",
    )
    pre_commit.write_text(stale_shim, encoding="utf-8")
    manifest_path = target / ".yoke/install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["git_hook_hashes"][".git/hooks/pre-commit"] = hashlib.sha256(
        stale_shim.encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (target / ".gitignore").write_text("", encoding="utf-8")

    assert cli_main(base) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["files_would_write"] == []
    assert preview["hooks_would_add"][".claude/settings.json"]
    assert preview["git_hooks_would_install_or_update"] == 1
    assert preview["worktrees_ignore"]["would_add"] is True

    assert cli_main([*base[:-1], "--force", "--no-commit", "--apply", "--json"]) == 0
    capsys.readouterr()
    assert pre_commit.read_text(encoding="utf-8") == (git_hooks_layer.PRE_COMMIT_SHIM)
    assert ".worktrees/" in (target / ".gitignore").read_text(encoding="utf-8")


def test_apply_requires_manifest_lineage_before_writes(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    before = _project_tree(target)

    rc = cli_main(
        [
            "project",
            "refresh",
            str(target),
            "--source-checkout",
            str(REPO_ROOT),
            "--project-id",
            "45",
            "--force",
            "--no-commit",
            "--apply",
            "--json",
        ]
    )

    assert rc == 1
    assert "requires install-manifest lineage" in capsys.readouterr().err
    assert _project_tree(target) == before
