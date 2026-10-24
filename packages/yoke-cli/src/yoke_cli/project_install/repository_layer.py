"""Write every repository-content part of the installed operating layer.

The bundle write and the Codex hook-trust mint are one unit because they are exactly what lands in the project's
git tree. Publication re-runs this unit when the remote advanced mid-install,
so the replacement commit carries content regenerated on the new revision
rather than content merged onto it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_cli.project_install.bundle_apply import apply_bundle
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
    report = apply_bundle(
        repo_root, bundle, operation=operation, source=source, retain_pending=True
    )
    report["codex_hook_trust"] = mint_codex_hook_trust(repo_root)
    # A clean copy install can still be shadowed at commit time: a
    # core.hooksPath override sends git elsewhere, or a missing `yoke`
    # launcher leaves the shims unable to exec. Surface both loudly.
    if mode == MODE_COPY:
        report.setdefault("warnings", []).extend(collect_hooks_path_warnings(repo_root))
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
            compose_refusal(
                f"Codex hook trust mint failed for {hooks_file_for(root)}: {exc}.",
                recovery=f"{retrust_recovery(root)}",
            )
        ) from exc


__all__ = [
    "mint_codex_hook_trust",
    "write_repository_layer",
]
