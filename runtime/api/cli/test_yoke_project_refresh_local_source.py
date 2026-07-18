"""Clean-room proofs for explicit source-dev/admin project refresh."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from yoke_cli.main import main as cli_main
from yoke_cli.project_install import git_hooks as git_hooks_layer


REPO_ROOT = Path(__file__).resolve().parents[3]


def _git_init(root: Path) -> None:
    root.mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(root), "init", "-q"],
        capture_output=True,
        text=True,
        check=True,
    )


def _project_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def _seed_manifest(
    root: Path, project_id: int, project_slug: str = "external-project",
) -> None:
    path = root / ".yoke/install-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "manifest_schema": 1,
            "yoke_version": "packaged-baseline",
            "project_id": project_id,
            "project_slug": project_slug,
            "mode": "copy",
            "files": {},
            "contract_files": {},
            "strategy_files": {},
            "created_settings_files": [],
            "hook_entries": {},
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_preview_reports_changes_without_target_writes(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    before = _project_tree(target)

    rc = cli_main([
        "project", "refresh", str(target),
        "--source-checkout", str(REPO_ROOT),
        "--project-id", "41", "--project-slug", "preview-project", "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["preview"] is True
    assert report["source_dev_admin"] is True
    assert report["target_writes"] is False
    assert report["server_state_writes"] is False
    assert report["snapshot_sync"]["status"] == "skipped"
    assert report["files_would_write"]
    assert report["git_hooks_would_install_or_update"] == 2
    assert report["worktrees_ignore"]["would_add"] is True
    assert _project_tree(target) == before
    assert not (target / ".yoke/install-manifest.json").exists()


def test_preview_reports_discarded_inert_legacy_records(
    tmp_path: Path, capsys,
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

    rc = cli_main([
        "project", "refresh", str(target),
        "--source-checkout", str(REPO_ROOT),
        "--project-id", "50", "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["prior_contract_records_discarded"] == [contract_path]
    assert report["prior_strategy_records_discarded"] == [strategy_path]
    assert report["target_writes"] is False
    assert _project_tree(target) == before


def test_source_preview_rejects_malformed_settings_without_mutation(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    settings = target / ".claude/settings.json"
    settings.parent.mkdir()
    settings.write_text("{not json", encoding="utf-8")
    before = _project_tree(target)

    rc = cli_main([
        "project", "refresh", str(target),
        "--source-checkout", str(REPO_ROOT),
        "--project-id", "48", "--project-slug", "malformed-settings",
        "--json",
    ])

    assert rc == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert _project_tree(target) == before


def test_apply_then_second_run_is_idempotent(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    _seed_manifest(target, 42)
    args = [
        "project", "refresh", str(target),
        "--source-checkout", str(REPO_ROOT),
        "--project-id", "42", "--apply", "--json",
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
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    _seed_manifest(target, 49)
    base = [
        "project", "refresh", str(target),
        "--source-checkout", str(REPO_ROOT),
        "--project-id", "49", "--json",
    ]
    assert cli_main([*base[:-1], "--apply", "--json"]) == 0
    capsys.readouterr()

    settings_path = target / ".claude/settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["hooks"]["PreToolUse"].pop()
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    pre_commit = target / ".git/hooks/pre-commit"
    stale_shim = git_hooks_layer.PRE_COMMIT_SHIM.replace(
        "# Hard-fails", "# stale source copy\n# Hard-fails",
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

    assert cli_main([*base[:-1], "--apply", "--json"]) == 0
    capsys.readouterr()
    assert pre_commit.read_text(encoding="utf-8") == (
        git_hooks_layer.PRE_COMMIT_SHIM
    )
    assert ".worktrees/" in (target / ".gitignore").read_text(encoding="utf-8")


def test_apply_requires_manifest_lineage_before_writes(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    before = _project_tree(target)

    rc = cli_main([
        "project", "refresh", str(target),
        "--source-checkout", str(REPO_ROOT),
        "--project-id", "45", "--apply", "--json",
    ])

    assert rc == 1
    assert "requires install-manifest lineage" in capsys.readouterr().err
    assert _project_tree(target) == before


def test_manifest_transfer_prunes_dropped_file_in_linked_checkout(
    tmp_path: Path, capsys,
) -> None:
    main_checkout = tmp_path / "project-main"
    linked_checkout = tmp_path / "project-worktree"
    _git_init(main_checkout)
    _git_init(linked_checkout)
    _seed_manifest(main_checkout, 43)
    base_args = [
        "project", "refresh", str(main_checkout),
        "--source-checkout", str(REPO_ROOT),
        "--project-id", "43", "--apply", "--json",
    ]
    assert cli_main(base_args) == 0
    capsys.readouterr()

    obsolete_content = "old generated content\n"
    obsolete_hash = hashlib.sha256(obsolete_content.encode("utf-8")).hexdigest()
    manifest_path = main_checkout / ".yoke/install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    obsolete_rel = ".claude/skills/yoke/obsolete/SKILL.md"
    manifest["files"][obsolete_rel] = obsolete_hash
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    obsolete_path = linked_checkout / obsolete_rel
    obsolete_path.parent.mkdir(parents=True)
    obsolete_path.write_text(obsolete_content, encoding="utf-8")
    assert not (linked_checkout / ".yoke/install-manifest.json").exists()

    rc = cli_main([
        "project", "refresh", str(linked_checkout),
        "--source-checkout", str(REPO_ROOT),
        "--manifest-from", str(manifest_path),
        "--apply", "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["manifest_source"] == str(manifest_path.resolve())
    assert report["files_pruned"] == [obsolete_rel]
    assert not obsolete_path.exists()
    assert (linked_checkout / ".yoke/install-manifest.json").is_file()


def test_full_manifest_preserves_unrendered_workflow_and_contract(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    workflow_rel = ".github/workflows/deploy.yml"
    workflow_content = "name: deploy\non: workflow_dispatch\n"
    removed_source_rel = ".claude/skills/yoke/removed/SKILL.md"
    removed_source_content = "# removed source skill\n"
    contract_rel = ".yoke/lint-config"
    contract_content = "lint_main_commit=deny\n"
    for rel, content in (
        (workflow_rel, workflow_content),
        (removed_source_rel, removed_source_content),
        (contract_rel, contract_content),
    ):
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    manifest_path = target / ".yoke/install-manifest.json"
    initial_manifest = {
        "manifest_schema": 1,
        "yoke_version": "packaged-baseline",
        "project_id": 46,
        "project_slug": "workflow-project",
        "mode": "copy",
        "files": {
            workflow_rel: hashlib.sha256(
                workflow_content.encode("utf-8")
            ).hexdigest(),
            removed_source_rel: hashlib.sha256(
                removed_source_content.encode("utf-8")
            ).hexdigest(),
        },
        "contract_files": {
            contract_rel: hashlib.sha256(
                contract_content.encode("utf-8")
            ).hexdigest(),
        },
        "strategy_files": {},
        "created_settings_files": [],
        "hook_entries": {},
    }
    manifest_path.write_text(
        json.dumps(initial_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args = [
        "project", "refresh", str(target),
        "--source-checkout", str(REPO_ROOT), "--json",
    ]

    assert cli_main(args) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["project_slug"] == "workflow-project"
    assert preview["files_preserved_unrendered"] == [workflow_rel]
    assert preview["files_would_prune"] == [removed_source_rel]
    assert (target / workflow_rel).read_text(encoding="utf-8") == workflow_content
    assert (target / contract_rel).read_text(encoding="utf-8") == contract_content

    assert cli_main([*args[:-1], "--apply", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files_preserved_unrendered"] == [workflow_rel]
    assert report["files_pruned"] == [removed_source_rel]
    assert (target / workflow_rel).read_text(encoding="utf-8") == workflow_content
    assert (target / contract_rel).read_text(encoding="utf-8") == contract_content
    refreshed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert refreshed["project_slug"] == "workflow-project"
    assert refreshed["files"][workflow_rel] == (
        initial_manifest["files"][workflow_rel]
    )
    assert refreshed["contract_files"][contract_rel] == (
        initial_manifest["contract_files"][contract_rel]
    )
