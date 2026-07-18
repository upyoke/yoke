"""Complete, read-only preflight for project bundle application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import project_worktrees_ignore
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import git_hooks as git_hooks_layer
from yoke_cli.project_install import hooks as hooks_layer
from yoke_cli.project_install import strategy as strategy_layer


def preflight_apply(
    repo_root: Path,
    bundle: dict[str, Any],
    old_manifest: dict[str, Any],
    preserved_files: dict[str, str],
) -> dict[str, Any]:
    """Validate every predictable apply failure without touching the repo."""
    if old_manifest:
        files_layer.validate_manifest(old_manifest, source="prior install manifest")
    files_layer.validate_manifest(
        {"manifest_schema": files_layer.MANIFEST_SCHEMA, "files": preserved_files},
        source="preserved manifest files",
    )

    bundle_files = bundle["files"]
    contracts = bundle.get("project_contract_files") or []
    strategies = bundle.get("strategy_files") or []
    files_layer.assert_safe_bundle_paths(entry["path"] for entry in bundle_files)
    files_layer.assert_safe_contract_paths(entry["path"] for entry in contracts)
    strategy_layer.assert_safe_strategy_paths(entry["path"] for entry in strategies)

    write_targets = [
        *(entry["path"] for entry in bundle_files),
        *(entry["path"] for entry in contracts),
        *strategy_layer.strategy_mutation_paths(strategies),
        *hooks_layer.SETTINGS_FILE_BY_HOOKS_KEY.values(),
        files_layer.MANIFEST_REL,
        ".gitignore",
    ]
    files_layer.assert_file_targets_plannable(
        repo_root, write_targets, context="project install apply",
    )
    prior_targets = [
        *dict(old_manifest.get("files", {})),
        *dict(old_manifest.get("contract_files", {})),
        *dict(old_manifest.get("strategy_files", {})),
        *dict(old_manifest.get("git_hook_hashes", {})),
    ]
    files_layer.assert_resolved_targets_within(
        repo_root, prior_targets, context="prior manifest mutation",
    )

    created_settings = set(old_manifest.get("created_settings_files", []))
    prior_hooks = {
        rel: list(records)
        for rel, records in dict(old_manifest.get("hook_entries", {})).items()
    }
    hook_plans = hooks_layer.preflight_hooks_settings(
        repo_root, bundle["hooks"], prior_hooks, created_settings,
    )
    git_hook_specs = git_hooks_layer.git_hook_specs_from_bundle(bundle)
    owned_git_hook_hashes = (
        dict(old_manifest["git_hook_hashes"])
        if "git_hook_hashes" in old_manifest
        else None
    )
    git_hook_preview = git_hooks_layer.preview_git_hooks(
        repo_root, git_hook_specs, owned_git_hook_hashes,
    )
    worktrees_ignore = project_worktrees_ignore.report(repo_root, apply=False)
    return {
        "hook_plans": hook_plans,
        "git_hook_specs": git_hook_specs,
        "git_hook_preview": git_hook_preview,
        "owned_git_hook_hashes": owned_git_hook_hashes,
        "worktrees_ignore": worktrees_ignore,
    }


__all__ = ["preflight_apply"]
