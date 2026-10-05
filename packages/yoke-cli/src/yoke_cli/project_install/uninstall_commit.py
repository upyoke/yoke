"""Record project removal through the existing installer commit owner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.project_install import checkout_gate, installed_output_paths
from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.config.project_onboard_support import dispatch


def prepare(
    root: Path, manifest: dict[str, Any], config_path: str | Path | None = None
) -> list[str]:
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
        try:
            result = dispatch(
                "projects.get",
                {"project": str(manifest["project_id"]), "field": "default_branch"},
                config_path,
            )
        except (KeyError, RuntimeError) as exc:
            raise ProjectInstallError(
                f"project_uninstall_default_branch_unavailable: {exc}. "
                "Check yoke env list and the project's default branch, then retry."
            ) from exc
        branch = str(result.get("value") or "").strip()
        try:
            checkout_gate.assert_ready_for_write(
                root, default_branch=branch, require_default_branch=bool(branch)
            )
        except ProjectInstallError as exc:
            raise ProjectInstallError(
                "project_uninstall_checkout_refused: "
                + str(exc).replace(" or pass --force", "")
            ) from exc
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
