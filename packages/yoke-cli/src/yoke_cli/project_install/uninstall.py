"""Uninstall pass for ``yoke project uninstall`` (copy strategy only).

Removes manifest-tracked files, de-merges Yoke harness hook entries,
and removes Yoke-marked git hook shims. Source-link checkouts (the
Yoke source repo) refuse entirely: the dev layer there is the repo's
own tracked content, not an installed copy. Split from
:mod:`project_install`, which owns install/refresh and the apply core.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import git_hooks as git_hooks_layer
from yoke_cli.project_install import hooks as hooks_layer
from yoke_cli.project_install.files import (
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
    """Remove manifest-tracked files and de-merge Yoke hook entries.

    Copy-mode only. The source-checkout detection guard backstops the
    manifest mode so a legacy or hand-edited manifest can never
    authorize de-installing the source checkout; manifests without the
    mode key are copy manifests (pre-mode installed state).
    """
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
    removed, skipped, absent, warnings = files_layer.remove_manifest_files(
        root, dict(manifest.get("files") or {})
    )
    # Contract files: remove only installer-created files still byte-equal
    # to their seeded content; edited ones are preserved with a warning and
    # pre-existing files were never recorded, so they are never touched.
    contract_removed, contract_skipped, contract_absent, contract_warnings = (
        files_layer.remove_manifest_files(
            root, dict(manifest.get("contract_files") or {})
        )
    )
    warnings.extend(contract_warnings)
    created = set(manifest.get("created_settings_files") or [])
    hooks_removed: Dict[str, List[Dict[str, Any]]] = {}
    settings_deleted: List[str] = []
    for settings_rel, records in sorted(
        (manifest.get("hook_entries") or {}).items()
    ):
        result = hooks_layer.demerge_hooks_file(
            root, settings_rel, list(records or []),
            created_by_install=settings_rel in created,
        )
        if result["removed"]:
            hooks_removed[settings_rel] = result["removed"]
        if result["deleted_file"]:
            settings_deleted.append(settings_rel)
    # Strategy files are planning content that outlives the tooling —
    # uninstall never removes them, tracked or not.
    strategy_preserved = sorted(dict(manifest.get("strategy_files") or {}))
    git_hooks_removed = git_hooks_layer.remove_yoke_git_hooks(root)
    files_layer.manifest_path(root).unlink()
    files_layer.remove_empty_parents(root, files_layer.MANIFEST_REL)
    return {
        "operation": "uninstall",
        MODE_KEY: MODE_COPY,
        "repo_root": str(root),
        "files_removed": removed,
        "files_skipped_modified": skipped,
        "files_already_absent": absent,
        "contract_files_removed": contract_removed,
        "contract_files_preserved_modified": contract_skipped,
        "contract_files_already_absent": contract_absent,
        "strategy_files_preserved": strategy_preserved,
        "hooks_removed": hooks_removed,
        "git_hooks_removed": git_hooks_removed,
        "settings_files_deleted": settings_deleted,
        "manifest_removed": True,
        "warnings": warnings,
    }


__all__ = ["uninstall"]
