"""Network-free application of a resolved project install bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from yoke_cli.config import project_worktrees_ignore
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import git_hooks as git_hooks_layer
from yoke_cli.project_install import hooks as hooks_layer
from yoke_cli.project_install import strategy as strategy_layer
from yoke_cli.project_install.files import (
    DISCARDED_PRIOR_CONTRACT_RECORDS_KEY,
    DISCARDED_PRIOR_STRATEGY_RECORDS_KEY,
    MODE_COPY,
    MODE_KEY,
    ProjectInstallError,
)
from yoke_cli.project_install.preflight import preflight_apply
from yoke_cli.project_install.validate import _validate_bundle

_MANIFEST_OWNED_KEYS = frozenset(
    {
        "manifest_schema",
        "yoke_version",
        "project_id",
        "project_slug",
        MODE_KEY,
        "files",
        "contract_files",
        "strategy_files",
        "created_settings_files",
        "hook_entries",
        "git_hook_hashes",
        "worktrees_ignore_added",
        "worktrees_ignore_created_file",
        DISCARDED_PRIOR_CONTRACT_RECORDS_KEY,
        DISCARDED_PRIOR_STRATEGY_RECORDS_KEY,
    }
)


def apply_bundle(
    repo_root: Path,
    bundle: Dict[str, Any],
    *,
    operation: str = "install",
    source: str = "in-process",
    prior_manifest: Dict[str, Any] | None = None,
    preserved_manifest_files: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Apply a resolved bundle to ``repo_root`` (the network-free core)."""
    _validate_bundle(bundle)
    git_hooks_layer.assert_pre_commit_runtime_available()
    old_manifest = (
        prior_manifest
        if prior_manifest is not None
        else files_layer.load_manifest(repo_root) or {}
    )
    bundle_files: List[Dict[str, str]] = bundle["files"]
    files_layer.assert_safe_bundle_paths(e["path"] for e in bundle_files)
    contract_files: List[Dict[str, str]] = bundle.get("project_contract_files") or []
    files_layer.assert_safe_contract_paths(e["path"] for e in contract_files)
    strategy_files: List[Dict[str, str]] = bundle.get("strategy_files") or []
    strategy_layer.assert_safe_strategy_paths(e["path"] for e in strategy_files)
    preserved_files = dict(preserved_manifest_files or {})
    files_layer.assert_safe_bundle_paths(preserved_files)
    rendered_paths = {entry["path"] for entry in bundle_files}
    overlap = sorted(rendered_paths & set(preserved_files))
    if overlap:
        raise ProjectInstallError(
            "preserved manifest files overlap rendered bundle paths: "
            + ", ".join(overlap)
        )

    preflight = preflight_apply(
        repo_root,
        bundle,
        old_manifest,
        preserved_files,
    )

    hashes, written = files_layer.apply_files(repo_root, bundle_files)
    hashes.update(preserved_files)
    pruned, skipped, warnings = files_layer.prune_files(
        repo_root, dict(old_manifest.get("files") or {}), hashes
    )
    contract_map, contract_written, contract_existing, contract_adopted = (
        files_layer.apply_contract_files(
            repo_root,
            contract_files,
            dict(old_manifest.get("contract_files") or {}),
        )
    )
    # Seed-if-missing never backfills an existing .yoke/.gitignore, so a
    # project onboarded before an ignore name (e.g. `strategy/`) entered the
    # canonical set would keep tracking those views. Reconcile the existing
    # file up to the canonical ignore set on every install/refresh.
    gitignore_backfilled = files_layer.reconcile_gitignore(
        repo_root,
        contract_files,
    )
    (
        strategy_map,
        strategy_written,
        strategy_unchanged,
        strategy_preserved,
        strategy_warnings,
    ) = strategy_layer.apply_strategy_files(
        repo_root,
        strategy_files,
        dict(old_manifest.get("strategy_files") or {}),
    )
    warnings.extend(strategy_warnings)

    created_settings = set(old_manifest.get("created_settings_files") or [])
    prior_hook_entries: Dict[str, List[Dict[str, Any]]] = {
        rel: list(records or [])
        for rel, records in (old_manifest.get("hook_entries") or {}).items()
    }
    hook_entries: Dict[str, List[Dict[str, Any]]] = {}
    hooks_added: Dict[str, List[Dict[str, Any]]] = {}
    hooks_removed: Dict[str, List[Dict[str, Any]]] = {}
    for hooks_key, settings_rel in sorted(
        hooks_layer.SETTINGS_FILE_BY_HOOKS_KEY.items()
    ):
        subtree = bundle["hooks"][hooks_key]
        result = hooks_layer.reconcile_hooks_file(
            repo_root,
            settings_rel,
            subtree,
            prior_hook_entries.get(settings_rel, []),
            created_by_install=settings_rel in created_settings,
        )
        if result["created"]:
            created_settings.add(settings_rel)
        if result["deleted_file"]:
            created_settings.discard(settings_rel)
        if result["added"]:
            hooks_added[settings_rel] = result["added"]
        if result["removed"]:
            hooks_removed[settings_rel] = result["removed"]
        hook_entries[settings_rel] = hooks_layer.provided_records(subtree)

    # Git hook shims (§2.K guardrail mandate): same pre/post-commit
    # install as source-link mode; skips gracefully without .git/hooks/
    # (linked worktree or not a git repo) and warns on foreign hooks.
    git_hooks = git_hooks_layer.BootstrapResult()
    git_hooks_layer.install_git_hooks(
        repo_root,
        git_hooks,
        preflight["git_hook_specs"],
        preflight["owned_git_hook_hashes"],
    )
    warnings.extend(git_hooks.warnings)
    worktrees_ignore = project_worktrees_ignore.report(repo_root, apply=True)
    git_hook_hashes = git_hooks_layer.managed_git_hook_hashes(
        repo_root,
        preflight["git_hook_specs"],
    )
    worktrees_ignore_added = bool(
        old_manifest.get("worktrees_ignore_added") or worktrees_ignore["applied"]
    )
    worktrees_ignore_created_file = bool(
        old_manifest.get("worktrees_ignore_created_file")
        or worktrees_ignore.get("created_file")
    )

    # Carry unknown top-level manifest keys forward: a field written by a
    # newer CLI must survive this version's whole-object rewrite (the
    # contract_files key was demonstrably dropped this way by older CLIs).
    manifest = {
        key: value
        for key, value in old_manifest.items()
        if key not in _MANIFEST_OWNED_KEYS
    }
    manifest.update(
        {
            "manifest_schema": files_layer.MANIFEST_SCHEMA,
            "yoke_version": bundle["yoke_version"],
            "project_id": bundle["project_id"],
            "project_slug": bundle["project_slug"],
            MODE_KEY: MODE_COPY,
            "files": hashes,
            "contract_files": contract_map,
            "strategy_files": strategy_map,
            "created_settings_files": sorted(created_settings),
            "hook_entries": hook_entries,
            "git_hook_hashes": git_hook_hashes,
            "worktrees_ignore_added": worktrees_ignore_added,
            "worktrees_ignore_created_file": worktrees_ignore_created_file,
        }
    )
    manifest_file = files_layer.write_manifest(repo_root, manifest)
    return {
        "operation": operation,
        MODE_KEY: MODE_COPY,
        "repo_root": str(repo_root),
        "project_id": bundle["project_id"],
        "project_slug": bundle["project_slug"],
        "yoke_version": bundle["yoke_version"],
        "source": source,
        "files_written": written,
        "files_unchanged": len(hashes) - len(written),
        "files_pruned": pruned,
        "files_skipped_modified": skipped,
        "files_preserved_unrendered": sorted(preserved_files),
        "contract_files_written": contract_written,
        "contract_files_existing": contract_existing,
        "contract_files_adopted": contract_adopted,
        "prior_contract_records_discarded": list(
            old_manifest.get(DISCARDED_PRIOR_CONTRACT_RECORDS_KEY) or []
        ),
        "prior_strategy_records_discarded": list(
            old_manifest.get(DISCARDED_PRIOR_STRATEGY_RECORDS_KEY) or []
        ),
        "gitignore_ignores_backfilled": gitignore_backfilled,
        "strategy_files_written": strategy_written,
        "strategy_files_unchanged": strategy_unchanged,
        "strategy_files_preserved_edited": strategy_preserved,
        "project_policy_capabilities": (
            bundle.get("project_policy_capabilities") or {}
        ),
        "hooks_added": hooks_added,
        "hooks_removed": hooks_removed,
        "git_hooks_installed_or_updated": (git_hooks.installed + git_hooks.updated),
        "git_hook_actions": git_hooks.actions,
        "worktrees_ignore": worktrees_ignore,
        "created_settings_files": sorted(created_settings),
        "manifest": str(manifest_file),
        "machine_config_newly_registered": False,
        "warnings": warnings,
    }


__all__ = ["apply_bundle"]
