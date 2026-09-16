"""Write every repository-content part of the installed operating layer.

The bundle write, the Codex hook-trust mint, and the file-line exception
bookkeeping are one unit because they are exactly what lands in the project's
git tree. Publication re-runs this unit when the remote advanced mid-install,
so the replacement commit carries content regenerated on the new revision
rather than content merged onto it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.file_line_config_migration import (
    migrate_file_line_exceptions,
)
from yoke_cli.project_install.file_line_managed_exceptions import (
    ensure_managed_file_line_exceptions,
)
from yoke_cli.project_install.files import MODE_COPY, ProjectInstallError
from yoke_cli.project_install.hooks_path_check import (
    collect_hooks_path_warnings,
)


def write_repository_layer(
    repo_root: Path,
    bundle: Dict[str, Any],
    *,
    operation: str,
    source: str,
    mode: str,
) -> Dict[str, Any]:
    """Write every repository-content part of the layer, and report it.

    Publication re-runs exactly this when the remote advanced mid-run, so
    the replacement commit carries content regenerated on the new base
    rather than content merged onto it.
    """
    report = apply_bundle(repo_root, bundle, operation=operation, source=source)
    report["codex_hook_trust"] = mint_codex_hook_trust(repo_root)
    # A clean copy install can still be shadowed at commit time: a
    # core.hooksPath override sends git elsewhere, or a missing `yoke`
    # launcher leaves the shims unable to exec. Surface both loudly.
    if mode == MODE_COPY:
        report.setdefault("warnings", []).extend(
            collect_hooks_path_warnings(repo_root)
        )
    # Runs after apply so the seeded .yoke/project.config exists to move into.
    report["file_line_config_migration"] = migrate_file_line_exceptions(repo_root)
    # The install writes the managed rules files AND the gate that measures
    # them, so it also owns exempting them — otherwise a project's first
    # commit fails on the install's own output.
    report["file_line_managed_exceptions"] = ensure_managed_file_line_exceptions(
        repo_root,
        managed_markdown_paths(bundle),
    )
    return report


def mint_codex_hook_trust(root: Path) -> Dict[str, object]:
    """Trust only the Codex hooks file the completed install just authored."""
    from yoke_contracts.codex_hook_trust_store import (
        CodexHookTrustStoreError,
        hooks_file_for,
        mint_installed_checkout_trust,
        retrust_recovery,
    )

    try:
        return mint_installed_checkout_trust(root).payload()
    except CodexHookTrustStoreError as exc:
        raise ProjectInstallError(
            f"Codex hook trust mint failed for {hooks_file_for(root)}: {exc}. "
            f"Recovery: {retrust_recovery(root)}"
        ) from exc


def managed_markdown_paths(bundle: dict) -> list[str]:
    """Repo-relative paths of the rules files this bundle manages.

    Read from the bundle rather than hardcoded so the exemption set tracks
    whatever the server declares as managed-markdown targets. A bundle from
    an older server carries no targets and yields nothing to exempt.
    """
    managed = bundle.get("managed_markdown")
    if not isinstance(managed, dict):
        return []
    targets = managed.get("targets")
    if not isinstance(targets, list):
        return []
    paths: list[str] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        rel = target.get("path")
        if isinstance(rel, str) and rel:
            paths.append(rel)
    return paths


__all__ = [
    "managed_markdown_paths",
    "mint_codex_hook_trust",
    "write_repository_layer",
]
