"""Source-link delivery strategy for ``yoke dev setup``.

The Yoke source checkout IS the bundle source, so its harness surfaces
are git-tracked symlinks into the live tree (edit a canonical file, run
``agents.render.run``, every consumer sees the change instantly).
``source-link`` owns that wiring:

1. Dev symlinks — ``.claude/`` + ``.codex/`` surfaces pointing at the
   canonical ``runtime/harness/...`` targets, the
   ``.claude/skills/yoke`` compatibility link, and the tester-browser
   reference link. The links are git-tracked, so a fresh clone already
   has them; install/refresh repairs drift (deleted/replaced links)
   idempotently.
2. Git hooks — the pre-commit + post-commit shims via
   :mod:`project_install_git_hooks` (same refuse/refresh/create
   semantics as copy mode; linked worktrees skip gracefully).
3. Contract seeding — the same seed-if-missing pass copy-mode uses
   (:func:`project_install_files.apply_contract_files`); the Yoke
   repo tracks its own contract files, so this is normally a no-op.
4. Manifest — ``.yoke/install-manifest.json`` with
   ``"mode": "source-link"`` and the link inventory. ``refresh``
   re-runs the same repair; ``uninstall`` REFUSES entirely (the links
   are tracked files — you do not uninstall the source repo's dev
   layer).

No bundle fetch ever happens in source-link mode, and normal
``yoke project install`` does not enter this branch. Detection marker:
``pyproject.toml`` declaring ``name = "yoke"`` plus a
``runtime/harness/`` tree.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from yoke_core.domain import project_install_files as files_layer
from yoke_core.domain.project_install_files import (
    MODE_COPY,
    MODE_KEY,
    MODE_SOURCE_LINK,
    ProjectInstallError,
)
from yoke_core.domain.project_install_git_hooks import (
    GIT_HOOK_NAMES,
    BootstrapResult,
    install_git_hooks,
)

# Relative symlinks the Yoke source checkout carries so that harness
# runtimes read the live canonical tree instead of stale copies.
DEV_SYMLINKS: Tuple[Tuple[str, str], ...] = (
    (".claude/agents", "../runtime/harness/claude/agents"),
    (".claude/rules", "../runtime/harness/claude/rules"),
    (".claude/settings.json", "../runtime/harness/claude/settings.json"),
    (".claude/skills/yoke", "../../.agents/skills/yoke"),
    (".codex/agents", "../runtime/harness/codex/agents"),
    (".codex/hooks.json", "../runtime/harness/codex/hooks.json"),
    (
        "runtime/harness/claude/agents/references/yoke-tester-browser.md",
        "../../../../agents/tester-browser.md",
    ),
)

# Display name used for in-checkout contract rendering; the detection
# guard already pins the package name to "yoke".
SOURCE_DISPLAY_NAME = "Yoke"

# Manifest keys the source-link writer owns; anything else found in an
# existing manifest is carried forward verbatim on rewrite.
_SOURCE_LINK_OWNED_KEYS = frozenset({
    "manifest_schema",
    "yoke_version",
    MODE_KEY,
    "symlinks",
    "git_hooks",
    "contract_files",
})


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


def ensure_dev_symlink(
    target_root: Path, rel: str, link_target: str, result: BootstrapResult,
) -> None:
    """Create *rel* -> *link_target* under *target_root*; repair-safe.

    Correct existing link: counted skipped. Wrong-target link or a
    regular file/dir squatting on the path: warn and leave in place
    (never silently replace operator state). Missing: create.
    """
    path = target_root / rel
    if path.is_symlink():
        current = os.readlink(path)
        if current == link_target:
            result.note(f"Exists: {rel} -> {link_target}")
            result.skipped += 1
        else:
            result.warn(
                f"{rel} is a symlink to {current} (expected {link_target}). "
                "Leaving in place; reconcile manually if intended."
            )
        return
    if path.exists():
        result.warn(
            f"{rel} exists as a regular file/dir. Move or remove it and "
            "re-run `yoke dev setup` so the symlink can be created."
        )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(link_target)
    result.note(f"Created: {rel} -> {link_target}")
    result.installed += 1


def source_link_uninstall_refusal(root: Path) -> ProjectInstallError:
    return ProjectInstallError(
        f"refusing to uninstall: {root} uses the source-link strategy — "
        "the .claude/.codex surfaces are git-tracked symlinks into "
        "runtime/harness/ and the dev layer is part of the repo itself, "
        "not an installed copy. There is nothing to de-install; remove "
        ".git/hooks/ shims manually if you must"
    )


def install_source_link(
    repo_root: Path, *, operation: str = "install",
) -> Dict[str, Any]:
    """Apply the source-link strategy to *repo_root* (no bundle, no fetch)."""
    from yoke_core.domain import project_contract
    from yoke_core.domain.install_bundle import yoke_version

    old_manifest = files_layer.load_manifest(repo_root) or {}
    links = BootstrapResult()
    for rel, link_target in DEV_SYMLINKS:
        ensure_dev_symlink(repo_root, rel, link_target, links)
    hooks = BootstrapResult()
    install_git_hooks(repo_root, hooks)

    # Same seed-if-missing pass copy-mode runs — the Yoke repo tracks
    # its own contract files, so this normally reports them all existing.
    contract_entries = project_contract.bundle_contract_files(
        SOURCE_DISPLAY_NAME
    )
    files_layer.assert_safe_contract_paths(
        entry["path"] for entry in contract_entries
    )
    contract_map, contract_written, contract_existing, contract_adopted = (
        files_layer.apply_contract_files(
            repo_root, contract_entries,
            dict(old_manifest.get("contract_files") or {}),
        )
    )

    manifest = {
        key: value
        for key, value in old_manifest.items()
        if key not in _SOURCE_LINK_OWNED_KEYS
    }
    manifest.update({
        "manifest_schema": files_layer.MANIFEST_SCHEMA,
        "yoke_version": yoke_version(),
        MODE_KEY: MODE_SOURCE_LINK,
        "symlinks": {rel: target for rel, target in DEV_SYMLINKS},
        "git_hooks": list(GIT_HOOK_NAMES),
        "contract_files": contract_map,
    })
    manifest_file = files_layer.write_manifest(repo_root, manifest)
    return {
        "operation": operation,
        MODE_KEY: MODE_SOURCE_LINK,
        "repo_root": str(repo_root),
        "yoke_version": manifest["yoke_version"],
        "source": "in-checkout",
        "symlinks_created": links.installed,
        "symlinks_ok": links.skipped,
        "hooks_installed_or_updated": hooks.installed + hooks.updated,
        "actions": links.actions + hooks.actions,
        "contract_files_written": contract_written,
        "contract_files_existing": contract_existing,
        "contract_files_adopted": contract_adopted,
        "manifest": str(manifest_file),
        "machine_config_newly_registered": False,
        "warnings": links.warnings + hooks.warnings,
    }


__all__ = [
    "DEV_SYMLINKS",
    "SOURCE_DISPLAY_NAME",
    "ensure_dev_symlink",
    "install_source_link",
    "is_yoke_source_checkout",
    "resolve_mode",
    "source_link_uninstall_refusal",
]
