"""Product side of ``yoke project install`` / ``refresh`` / ``uninstall``.

One repo-bootstrap command for external project checkouts, with the product
copy delivery strategy:

* ``copy`` (external project repos, the default) — fetches the rendered
  operating layer from the CLI's active HTTPS env and writes it
  idempotently, tracked by ``.yoke/install-manifest.json`` so refresh
  can prune and uninstall can remove cleanly.
The Yoke source checkout is not a product install target. Its tracked
source-link/admin wiring is owned by the explicit ``yoke dev setup``
branch so normal project installs stay external-project safe.

Never written: credentials, the machine active env, the CLI binary, the
browser runtime, or any ``.yoke/`` path other than the manifest and the
seed-if-missing project contract. The bundle is authority for its own
``files``; contract files are seeded only when absent and become
project-owned the moment they land; project-authored content (including
foreign hook entries) is untouchable.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_cli.config import machine_config
from yoke_cli.config import project_worktrees_ignore
from yoke_cli.config import writer as machine_config_writer
from yoke_cli.commands.adapters.project_snapshot import (
    sync_local_snapshot_for_write,
)
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import git_hooks as git_hooks_layer
from yoke_cli.project_install import hooks as hooks_layer
from yoke_cli.project_install.preflight import preflight_apply
from yoke_cli.project_install import source_dev
from yoke_cli.project_install import strategy as strategy_layer
from yoke_cli.project_install.files import (
    MODE_COPY,
    MODE_KEY,
    MODE_SOURCE_LINK,
    ProjectInstallError,
)
from yoke_cli.project_install.uninstall import uninstall
from yoke_cli.project_install.validate import (
    _validate_bundle,
    validate_bundle_for_project,
)
from yoke_cli.project_install.transport import (
    resolve_bundle as _resolve_bundle,
)

# Top-level manifest keys this CLI version authors; anything else found in
# an existing manifest is carried forward verbatim on rewrite.
_MANIFEST_OWNED_KEYS = frozenset({
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
})


def install(
    repo_root: str | Path | None = None,
    project_id: Optional[int] = None,
    explicit_env: Optional[str] = None,
    config_path: str | Path | None = None,
    *,
    operation: str = "install",
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Install (or refresh — same code path) the project-local layer.

    ``mode`` is retained for compatibility with direct callers; source-link
    setup now routes to ``yoke dev setup``.
    """
    root = files_layer.resolve_repo_root(repo_root)
    resolved_mode, reason = source_dev.resolve_mode(root, mode)
    print(
        f"yoke project {operation}: delivery strategy = {resolved_mode} "
        f"({reason})",
        file=sys.stderr,
    )
    git_hooks_layer.assert_pre_commit_runtime_available()
    resolved_id, explicit_given = _resolve_project_id(
        root, project_id, config_path
    )
    bundle, source = _resolve_bundle(
        resolved_id, explicit_env=explicit_env, config_path=config_path
    )
    validate_bundle_for_project(bundle, resolved_id)
    preflight_apply(root, bundle, files_layer.load_manifest(root) or {}, {})
    # Register between bundle resolution and apply: the fetch has already
    # validated the project id against the env (a 404 aborts before any
    # mapping is recorded), and an unwritable machine config fails fast
    # BEFORE the repo is touched. A mapping left by a later apply failure
    # is the same durable state `yoke project register` produces — a
    # plain rerun completes the install from it.
    registered = _register_in_machine_config(
        root, resolved_id, config_path, explicit_given
    )
    report = apply_bundle(root, bundle, operation=operation, source=source)
    report["snapshot_sync"] = sync_local_snapshot_for_write(
        project=str(resolved_id),
        repo_root=str(root),
        integration_target=None,
        session_id=None,
    )
    report["machine_config_newly_registered"] = registered
    return report


def refresh(
    repo_root: str | Path | None = None,
    project_id: Optional[int] = None,
    explicit_env: Optional[str] = None,
    config_path: str | Path | None = None,
    *,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    return install(repo_root, project_id, explicit_env, config_path,
                   operation="refresh", mode=mode)


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
    contract_files: List[Dict[str, str]] = (
        bundle.get("project_contract_files") or []
    )
    files_layer.assert_safe_contract_paths(e["path"] for e in contract_files)
    strategy_files: List[Dict[str, str]] = bundle.get("strategy_files") or []
    strategy_layer.assert_safe_strategy_paths(
        e["path"] for e in strategy_files
    )
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
        repo_root, bundle, old_manifest, preserved_files,
    )

    hashes, written = files_layer.apply_files(repo_root, bundle_files)
    hashes.update(preserved_files)
    pruned, skipped, warnings = files_layer.prune_files(
        repo_root, dict(old_manifest.get("files") or {}), hashes
    )
    contract_map, contract_written, contract_existing, contract_adopted = (
        files_layer.apply_contract_files(
            repo_root, contract_files,
            dict(old_manifest.get("contract_files") or {}),
        )
    )
    # Seed-if-missing never backfills an existing .yoke/.gitignore, so a
    # project onboarded before an ignore name (e.g. `strategy/`) entered the
    # canonical set would keep tracking those views. Reconcile the existing
    # file up to the canonical ignore set on every install/refresh.
    gitignore_backfilled = files_layer.reconcile_gitignore(
        repo_root, contract_files,
    )
    (
        strategy_map,
        strategy_written,
        strategy_unchanged,
        strategy_preserved,
        strategy_warnings,
    ) = strategy_layer.apply_strategy_files(
        repo_root, strategy_files,
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
        repo_root, preflight["git_hook_specs"],
    )
    worktrees_ignore_added = bool(
        old_manifest.get("worktrees_ignore_added")
        or worktrees_ignore["applied"]
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
    manifest.update({
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
    })
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
        "gitignore_ignores_backfilled": gitignore_backfilled,
        "strategy_files_written": strategy_written,
        "strategy_files_unchanged": strategy_unchanged,
        "strategy_files_preserved_edited": strategy_preserved,
        "project_policy_capabilities": (
            bundle.get("project_policy_capabilities") or {}
        ),
        "hooks_added": hooks_added,
        "hooks_removed": hooks_removed,
        "git_hooks_installed_or_updated": (
            git_hooks.installed + git_hooks.updated
        ),
        "git_hook_actions": git_hooks.actions,
        "worktrees_ignore": worktrees_ignore,
        "created_settings_files": sorted(created_settings),
        "manifest": str(manifest_file),
        "machine_config_newly_registered": False,
        "warnings": warnings,
    }


def _resolve_project_id(
    repo_root: Path,
    explicit: Optional[int],
    config_path: str | Path | None,
) -> Tuple[int, bool]:
    """Resolve project id: explicit flag > machine-config mapping > error."""
    if explicit is not None:
        return int(explicit), True
    mapped = machine_config.project_id(repo_root, config_path)
    if mapped is not None:
        return mapped, False
    raise ProjectInstallError(
        f"no project id for {repo_root}: pass --project-id N (the install "
        "will register the checkout mapping in machine config), or run "
        "`yoke project register` first"
    )


def _register_in_machine_config(
    repo_root: Path,
    project_id: int,
    config_path: str | Path | None,
    explicit_given: bool,
) -> bool:
    """Register the checkout->project mapping when install introduced it."""
    if not explicit_given:
        return False
    if machine_config.project_id(repo_root, config_path) is not None:
        return False
    machine_config_writer.register_project(
        repo_root, project_id, path=config_path
    )
    return True


__all__ = ["MODE_COPY", "MODE_KEY", "MODE_SOURCE_LINK",
           "ProjectInstallError", "apply_bundle", "install", "refresh",
           "uninstall"]
