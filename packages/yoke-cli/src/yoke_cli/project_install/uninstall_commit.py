"""Record project removal through the existing installer commit owner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.project_install import checkout_gate, installed_output_paths
from yoke_cli.project_install.files import ProjectInstallError


def prepare(root: Path, manifest: dict[str, Any]) -> list[str]:
    # A clean tree also means a clean index; the shared commit helper must never
    # incorporate an operator's already-staged changes into an uninstall commit.
    if checkout_gate.is_git_checkout(root):
        dirty = checkout_gate.porcelain(root)
        if dirty:
            raise ProjectInstallError(
                "project_uninstall_dirty_tree: commit or stash your changes in "
                f"{root}, then retry project uninstall. Dirty paths:\n"
                + "\n".join(dirty)
            )
    return installed_output_paths.normalized(
        [
            *installed_output_paths.manifest_owned_paths(manifest),
            *installed_output_paths.shared_paths(manifest),
            *installed_output_paths.managed_region_paths(manifest),
        ]
    )


def commit(root: Path, paths: list[str]) -> dict[str, Any]:
    try:
        return checkout_gate.commit_paths(
            root,
            paths,
            message="Uninstall Yoke operating layer",
        )
    except ProjectInstallError as exc:
        raise ProjectInstallError(
            f"project_uninstall_commit_failed: removal in {root} is uncommitted. "
            "Repair git, then stage and commit the removed Yoke layer before "
            f"retrying machine uninstall. {exc}"
        ) from exc
