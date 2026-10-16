"""Uninstall pass for ``yoke project uninstall`` (copy strategy only).

Removes manifest-tracked files, de-merges Yoke harness hook entries,
and removes Yoke-marked git hook shims. Source-link checkouts (the
Yoke source repo) refuse entirely: the dev layer there is the repo's
own tracked content, not an installed copy. Split from
:mod:`project_install`, which owns install/refresh and the apply core.
After the removal commit, retire only exclusive installer-owned checkout
registration and folder trust; preserve unresolved ownership for retry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from yoke_cli.config import project_worktrees_ignore
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import uninstall_commit
from yoke_cli.project_install import owned_cleanup
from yoke_cli.project_install import skill_discovery
from yoke_cli.project_install import git_hooks as git_hooks_layer
from yoke_cli.project_install import hooks as hooks_layer
from yoke_cli.project_install import managed_markdown as managed_markdown_layer
from yoke_cli.project_install import (
    cursor_permissions as cursor_permissions_layer,
)
from yoke_cli.project_install import (
    settings_permissions as settings_permissions_layer,
    settings_status_line as settings_status_line_layer,
)
from yoke_cli.project_install.files import (
    DISCARDED_PRIOR_CONTRACT_RECORDS_KEY,
    DISCARDED_PRIOR_STRATEGY_RECORDS_KEY,
    MODE_COPY,
    MODE_KEY,
    MODE_SOURCE_LINK,
    ProjectInstallError,
)
from yoke_cli.project_install.source_dev import (
    is_yoke_source_checkout,
    source_link_uninstall_refusal,
)


def uninstall(
    repo_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> Dict[str, Any]:
    """Remove the installed layer and exclusive owned registration/folder trust.

    Copy-mode only. The source-checkout detection guard backstops the
    manifest mode so a legacy or hand-edited manifest can never
    authorize de-installing the source checkout; manifests without the
    mode key are copy manifests (pre-mode installed state).
    """
    from yoke_cli.project_install.install_recovery import PENDING_REL

    root = files_layer.resolve_repo_root(repo_root)
    manifest = files_layer.load_manifest(root)
    if manifest is None:
        raise ProjectInstallError(
            f"no install manifest at {files_layer.manifest_path(root)}; "
            "nothing to uninstall (run `yoke project install` first)"
        )
    manifest_mode = manifest.get(MODE_KEY, MODE_COPY)
    if manifest_mode == MODE_SOURCE_LINK or is_yoke_source_checkout(root):
        raise source_link_uninstall_refusal(root)
    files_layer.assert_resolved_targets_within(
        root,
        [
            *dict(manifest.get("files", {})),
            *dict(manifest.get("contract_files", {})),
            *dict(manifest.get("strategy_files", {})),
            *dict(manifest.get("git_hook_hashes", {})),
            *list(manifest.get("created_settings_files", [])),
            *dict(manifest.get("hook_entries", {})),
            *dict(manifest.get("managed_markdown", {})),
            *(f".git/hooks/{name}" for name in git_hooks_layer.GIT_HOOK_NAMES),
            files_layer.MANIFEST_REL,
            PENDING_REL,
        ],
        context="project uninstall",
    )
    hooks_layer.preflight_hooks_settings(
        root,
        {key: {} for key in hooks_layer.SETTINGS_FILE_BY_HOOKS_KEY},
        {
            rel: list(records)
            for rel, records in dict(manifest.get("hook_entries", {})).items()
        },
        set(manifest.get("created_settings_files", [])),
    )
    project_worktrees_ignore.report(root, apply=False)
    commit_paths, commit_warnings = uninstall_commit.prepare(
        root, manifest, config_path
    )
    shared_scope = owned_cleanup.scope_reason(root, manifest, config_path)
    file_records = dict(manifest.get("files") or {})
    discovery_removed = skill_discovery.remove(
        root, manifest.get("skill_discovery_links")
    )
    removed, skipped, absent, warnings = remove_manifest_files(root, file_records)
    warnings.extend(commit_warnings)
    # Contract files: remove only installer-created files still byte-equal
    # to their seeded content; edited ones are preserved with a warning and
    # pre-existing files were never recorded, so they are never touched.
    contract_removed, contract_skipped, contract_absent, contract_warnings = (
        remove_manifest_files(root, dict(manifest.get("contract_files") or {}))
    )
    warnings.extend(contract_warnings)
    # Strip the managed permissions region and Markdown blocks first. Removing
    # our permissions keys before the hook de-merge below lets the de-merge's
    # "delete when only an empty hooks block remains" check fire correctly.
    settings_status_line_removed = (
        settings_status_line_layer.remove_settings_status_line(
            root,
            manifest.get(settings_status_line_layer.STATUS_LINE_MANIFEST_KEY),
        )
    )
    settings_permissions_removed = (
        settings_permissions_layer.remove_settings_permissions(
            root,
            manifest.get("settings_permissions"),
        )
    )
    managed_markdown_removed = managed_markdown_layer.remove_managed_markdown(
        root,
        manifest.get("managed_markdown"),
    )
    cursor_permissions_removed = cursor_permissions_layer.remove_cursor_permissions(
        root,
        manifest.get(cursor_permissions_layer.MANIFEST_KEY),
    )
    created = set(manifest.get("created_settings_files") or [])
    hooks_removed: Dict[str, List[Dict[str, Any]]] = {}
    settings_deleted: List[str] = []
    for settings_rel, records in sorted((manifest.get("hook_entries") or {}).items()):
        result = hooks_layer.demerge_hooks_file(
            root,
            settings_rel,
            list(records or []),
            created_by_install=settings_rel in created,
        )
        if result["removed"]:
            hooks_removed[settings_rel] = result["removed"]
        if result["deleted_file"]:
            settings_deleted.append(settings_rel)
    # Strategy files are planning content that outlives the tooling —
    # uninstall never removes them, tracked or not.
    strategy_preserved = sorted(dict(manifest.get("strategy_files") or {}))
    owned_git_hooks = dict(manifest.get("git_hook_hashes") or {})
    git_hooks_removed = (
        []
        if shared_scope
        else git_hooks_layer.remove_yoke_git_hooks(
            root,
            owned_git_hooks,
        )
    )
    worktrees_ignore = (
        project_worktrees_ignore.remove_owned_entry(
            root,
            created_file=bool(manifest.get("worktrees_ignore_created_file")),
        )
        if manifest.get("worktrees_ignore_added") and not shared_scope
        else {"removed": False, "deleted_file": False}
    )
    # A partial cleanup keeps ownership evidence for the same command's retry.
    commit_report = uninstall_commit.commit(root, commit_paths)
    local_cleanup = owned_cleanup.cleanup(root, manifest, config_path)
    if shared_scope:
        local_cleanup["complete"] = False
        warnings.append(
            f"project_uninstall_{shared_scope}: Git hooks and the worktree ignore entry may serve other checkouts; resolve sharing or checkout identity, then rerun project uninstall."
        )
    for row in [local_cleanup["registration"], *local_cleanup["trust"]]:
        if row["status"] in {"preserved", "failed"}:
            warnings.append(f"project_uninstall_{row['reason']}: {row['recovery']}")
    (root / PENDING_REL).unlink(missing_ok=True)
    if local_cleanup["complete"]:
        files_layer.manifest_path(root).unlink()
        files_layer.remove_empty_parents(root, files_layer.MANIFEST_REL)
        manifest_commit = uninstall_commit.commit(root, [files_layer.MANIFEST_REL])
        if manifest_commit["status"] == "created":
            commit_report = manifest_commit
    report = {
        "operation": "uninstall",
        MODE_KEY: MODE_COPY,
        "repo_root": str(root),
        "files_removed": removed,
        "skill_discovery_removed": discovery_removed,
        "files_skipped_modified": skipped,
        "files_already_absent": absent,
        "contract_files_removed": contract_removed,
        "contract_files_preserved_modified": contract_skipped,
        "contract_files_already_absent": contract_absent,
        "prior_contract_records_discarded": list(
            manifest.get(DISCARDED_PRIOR_CONTRACT_RECORDS_KEY) or []
        ),
        "prior_strategy_records_discarded": list(
            manifest.get(DISCARDED_PRIOR_STRATEGY_RECORDS_KEY) or []
        ),
        "strategy_files_preserved": strategy_preserved,
        "hooks_removed": hooks_removed,
        "git_hooks_removed": git_hooks_removed,
        "git_hooks_preserved_reason": shared_scope,
        "settings_permissions_removed": settings_permissions_removed,
        "settings_status_line_removed": settings_status_line_removed,
        "cursor_permissions_removed": cursor_permissions_removed,
        "managed_markdown_removed_files": managed_markdown_removed["removed_files"],
        "managed_markdown_stripped_blocks": (
            managed_markdown_removed["stripped_blocks"]
        ),
        "worktrees_ignore": worktrees_ignore,
        "settings_files_deleted": settings_deleted,
        "local_cleanup": local_cleanup,
        "outcome": "complete" if local_cleanup["complete"] else "partial",
        "manifest_removed": local_cleanup["complete"],
        "warnings": warnings,
    }
    report["commit"] = commit_report
    return report


__all__ = ["uninstall"]


def remove_manifest_files(
    repo_root: Path, files: dict[str, str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Uninstall pass over manifest files.

    Returns (removed, skipped_modified, already_absent, warnings).
    """
    files_layer.assert_resolved_targets_within(
        repo_root,
        files,
        context="manifest-owned file removal",
    )
    removed: list[str] = []
    skipped: list[str] = []
    absent: list[str] = []
    warnings: list[str] = []
    for rel in sorted(files):
        target = repo_root / rel
        if not target.is_file():
            absent.append(rel)
            continue
        try:
            current = target.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            current = None
        if current is None or files_layer.sha256_text(current) != files[rel]:
            skipped.append(rel)
            warnings.append(
                f"{rel} has local modifications; preserved (delete manually "
                "if unwanted)"
            )
            continue
        target.unlink()
        files_layer.remove_empty_parents(repo_root, rel)
        removed.append(rel)
    return removed, skipped, absent, warnings
