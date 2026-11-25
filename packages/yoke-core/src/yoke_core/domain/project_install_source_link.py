"""Source-link delivery strategy for ``yoke dev setup``.

The Yoke source checkout IS the bundle source, so its harnesses read the
live rendered tree (edit a canonical file, run ``yoke agents render``, every
consumer sees the change). Project configuration files that Cursor discovers
are tracked regular files because Cursor refuses config paths containing
symlinks; the renderer and this setup path keep them byte-identical to their
canonical runtime files. ``source-link`` owns that wiring:

1. Materialized configs — ``.claude/settings.json`` and
   ``.cursor/hooks.json`` copied from their canonical runtime files so
   Cursor's symlink refusal cannot disable either native or
   Claude-compatible hooks; install/refresh repairs drift idempotently.
2. Cursor permission regions — the same
   :mod:`yoke_cli.project_install.cursor_permissions` merge copy mode
   runs, unioning Yoke's command approvals and control-plane network
   origins into ``.cursor/cli.json`` and ``.cursor/sandbox.json``
   without disturbing operator entries.
3. Contract seeding — the seed-if-missing pass copy mode uses; the Yoke
   repo tracks its own contract files, so this is normally a no-op.
4. Generated views — the gitignored ``.yoke/docs`` and
   ``.yoke/harness/*/manifest.json`` copies and the native harness views
   (``.claude/agents``, ``.codex/hooks.json`` ...) through
   ``refresh_source_installed_views``, which lane preparation also runs.
5. Manifest — ``.yoke/install-manifest.json`` with ``"mode": "source-link"``.
   ``refresh`` re-runs the same repair; ``uninstall`` REFUSES entirely (the
   materialized configs are tracked files).

No bundle fetch ever happens in source-link mode, and normal ``yoke project
install`` does not enter this branch. Detection marker: ``pyproject.toml``
declaring ``name = "yoke"`` plus a ``runtime/harness/`` tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from yoke_contracts.runtime_ports.github_project_setup import get_github_project_setup
from yoke_contracts.runtime_ports.cursor_permissions import get_cursor_permissions
from yoke_contracts.filesystem_safety import (
    atomic_replace_bytes,
    first_symlink_component,
)
from yoke_contracts.cursor_permissions import CURSOR_PERMISSIONS_MANIFEST_KEY
from yoke_contracts.project_contract.source_installed_views import refresh_source_installed_views
from yoke_contracts.project_contract.install_error import ProjectInstallError
from yoke_contracts.runtime_ports.project_install_files import get_project_install_files

github_project_setup = get_github_project_setup()
apply_cursor_permissions = get_cursor_permissions().apply_cursor_permissions
files_layer = get_project_install_files()
MODE_COPY = files_layer.MODE_COPY
MODE_KEY = files_layer.MODE_KEY
MODE_SOURCE_LINK = files_layer.MODE_SOURCE_LINK

DEV_MATERIALIZED_FILES: Tuple[Tuple[str, str], ...] = (
    (".claude/settings.json", "runtime/harness/claude/settings.json"),
    (".cursor/hooks.json", "runtime/harness/cursor/hooks.json"),
)

# Display name used for in-checkout contract rendering; the detection
# guard already pins the package name to "yoke".
SOURCE_DISPLAY_NAME = "Yoke"

# Manifest keys the source-link writer owns; anything else found in an
# existing manifest is carried forward verbatim on rewrite.
_SOURCE_LINK_OWNED_KEYS = frozenset(
    {
        "manifest_schema",
        "yoke_version",
        MODE_KEY,
        "symlinks",  # retired link inventory; dropped from older manifests
        "materialized_files",
        "contract_files",
        CURSOR_PERMISSIONS_MANIFEST_KEY,
    }
)


def is_yoke_source_checkout(root: Path) -> bool:
    """True iff *root* is a Yoke source checkout (or linked worktree)."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return 'name = "yoke"' in text and (root / "runtime" / "harness").is_dir()


def resolve_mode(root: Path, explicit: Optional[str]) -> Tuple[str, str]:
    """Resolve product install mode while handing source checkouts to dev setup."""
    is_source = is_yoke_source_checkout(root)
    if explicit == MODE_SOURCE_LINK or is_source:
        target = "this Yoke source checkout" if is_source else str(root)
        raise ProjectInstallError(
            f"source-link setup for {target} is owned by `yoke dev setup`; "
            "normal `yoke project install` always uses the product copy "
            "strategy for external project repos"
        )
    if explicit == MODE_COPY:
        return MODE_COPY, "explicit --copy"
    return MODE_COPY, "external project repo"


def _assert_no_symlinked_parent(target_root: Path, rel: str) -> None:
    symlink = first_symlink_component(target_root, target_root / rel)
    if symlink is not None:
        raise ProjectInstallError(
            f"source-link materialized file {rel!r} crosses symlinked parent "
            f"{symlink}; replace that directory link with a real directory"
        )


@dataclass
class MaterializedFiles:
    installed: int = 0
    updated: int = 0
    skipped: int = 0
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ensure_dev_materialized_file(
    target_root: Path,
    rel: str,
    source_rel: str,
    result: MaterializedFiles,
) -> None:
    """Materialize a tracked source-dev file from its canonical source.

    Cursor rejects discovered configuration paths containing symlinks. A
    previous source-link setup may still have created one, so migration
    removes the old link before writing the canonical bytes. Regular-file
    edits are repaired; directories and other obstructions remain
    operator-owned.
    """
    files_layer.assert_resolved_targets_within(
        target_root,
        [rel, source_rel],
        context="source-link materialized file mutation",
    )
    _assert_no_symlinked_parent(target_root, rel)
    source = target_root / source_rel
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise ProjectInstallError(
            f"canonical source-link file {source_rel!r} is unreadable: {exc}"
        ) from exc

    target = target_root / rel
    was_link = target.is_symlink()
    had_file = target.is_file() and not was_link
    if not was_link and target.exists() and not target.is_file():
        result.warnings.append(
            f"{rel} exists as a regular file/dir. Move or remove it and "
            "re-run `yoke dev setup` so the materialized file can be created."
        )
        return
    if had_file:
        try:
            if target.read_bytes() == content:
                result.actions.append(f"Exists: {rel} (materialized from {source_rel})")
                result.skipped += 1
                return
        except OSError:
            pass

    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_replace_bytes(target, content)
    action = "Updated" if was_link or had_file else "Created"
    result.actions.append(f"{action}: {rel} (materialized from {source_rel})")
    if action == "Updated":
        result.updated += 1
    else:
        result.installed += 1


def source_link_uninstall_refusal(root: Path) -> ProjectInstallError:
    return ProjectInstallError(
        f"refusing to uninstall: {root} uses the source-link strategy — "
        "the source-dev materialized configs are git-tracked parts of the "
        "repo itself and its native harness views are generated from it, "
        "not an installed copy."
    )


def install_source_link(
    repo_root: Path,
    *,
    operation: str = "install",
    config_path: str | Path | None = None,
) -> Dict[str, Any]:
    """Apply the source-link strategy to *repo_root* (no bundle, no fetch)."""
    from yoke_core.domain import project_contract
    from yoke_core.domain.install_bundle import yoke_version

    git_credentials = github_project_setup.converge(repo_root, config_path=config_path)
    old_manifest = files_layer.load_manifest(repo_root) or {}
    for rel, source_rel in DEV_MATERIALIZED_FILES:
        files_layer.assert_resolved_targets_within(
            repo_root,
            [rel, source_rel],
            context="source-link materialized file mutation",
        )
        _assert_no_symlinked_parent(repo_root, rel)
    materialized = MaterializedFiles()
    git_hooks_removed = files_layer.remove_retired_git_hooks(
        repo_root, manifest=old_manifest, warnings=materialized.warnings
    )
    for rel, source_rel in DEV_MATERIALIZED_FILES:
        ensure_dev_materialized_file(repo_root, rel, source_rel, materialized)
    # Source and installed checkouts share Cursor permissions policy.
    cursor_permissions_records, cursor_permissions_report = apply_cursor_permissions(
        repo_root,
        prior_records=old_manifest.get(CURSOR_PERMISSIONS_MANIFEST_KEY),
    )

    # Same seed-if-missing pass copy-mode runs — the Yoke repo tracks
    # its own contract files, so this normally reports them all existing.
    contract_entries = project_contract.bundle_contract_files(SOURCE_DISPLAY_NAME)
    files_layer.assert_safe_contract_paths(entry["path"] for entry in contract_entries)
    contract_map, contract_written, contract_existing, contract_adopted = (
        files_layer.apply_contract_files(
            repo_root,
            contract_entries,
            dict(old_manifest.get("contract_files") or {}),
        )
    )

    manifest = {
        key: value
        for key, value in old_manifest.items()
        if key not in _SOURCE_LINK_OWNED_KEYS
    }
    manifest.update(
        {
            "manifest_schema": files_layer.MANIFEST_SCHEMA,
            "yoke_version": yoke_version(),
            MODE_KEY: MODE_SOURCE_LINK,
            "materialized_files": {
                rel: source_rel for rel, source_rel in DEV_MATERIALIZED_FILES
            },
            "contract_files": contract_map,
            CURSOR_PERMISSIONS_MANIFEST_KEY: cursor_permissions_records,
        }
    )
    manifest_file = files_layer.write_manifest(repo_root, manifest)
    return {
        "operation": operation,
        "git_credentials": git_credentials,
        MODE_KEY: MODE_SOURCE_LINK,
        "repo_root": str(repo_root),
        "yoke_version": manifest["yoke_version"],
        "source": "in-checkout",
        "materialized_files_created": materialized.installed,
        "materialized_files_updated": materialized.updated,
        "materialized_files_ok": materialized.skipped,
        "git_hooks_removed": git_hooks_removed,
        "actions": materialized.actions + cursor_permissions_report["actions"],
        "contract_files_written": contract_written,
        "contract_files_existing": contract_existing,
        "contract_files_adopted": contract_adopted,
        "source_views_refreshed": refresh_source_installed_views(repo_root),
        "manifest": str(manifest_file),
        "machine_config_newly_registered": False,
        "warnings": materialized.warnings,
    }


__all__ = [
    "DEV_MATERIALIZED_FILES",
    "SOURCE_DISPLAY_NAME",
    "ensure_dev_materialized_file",
    "install_source_link",
    "is_yoke_source_checkout",
    "resolve_mode",
    "source_link_uninstall_refusal",
]
