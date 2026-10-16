"""Record project removal through the existing installer commit owner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.project_install import checkout_gate, installed_output_paths
from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.config.project_onboard_support import dispatch


def prepare(
    root: Path, manifest: dict[str, Any], config_path: str | Path | None = None
) -> tuple[list[str], list[str]]:
    """Return the paths the removal commit owns, plus warnings to report.

    The owning install names the default branch the removal must land on.
    When that install cannot answer — it was replaced, deleted, or never
    reachable from this machine — the checkout is the only remaining
    authority, so removal proceeds on the current branch and says so.
    """
    warnings: list[str] = []
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
        project_id = manifest["project_id"]
        try:
            result = dispatch(
                "projects.get",
                {"project": str(project_id), "field": "default_branch"},
                config_path,
            )
        except Exception as exc:  # noqa: BLE001 — any unanswered lookup orphans the checkout
            current = checkout_gate.current_branch(root) or "detached HEAD"
            warnings.append(
                "project_uninstall_branch_unverified: the Yoke install that owns "
                f"project {project_id} did not answer ({exc}), so the removal "
                f"was committed on {current!r}. Merge that commit into your "
                "default branch."
            )
        else:
            _require_default_branch(root, str(result.get("value") or "").strip())
    return (
        installed_output_paths.normalized(
            [
                *installed_output_paths.manifest_owned_paths(manifest),
                *installed_output_paths.shared_paths(manifest),
                *installed_output_paths.managed_region_paths(manifest),
            ]
        ),
        warnings,
    )


def _require_default_branch(root: Path, branch: str) -> None:
    try:
        if not branch:
            raise ProjectInstallError(
                "project default_branch is empty; configure the project's "
                "default branch, then retry project uninstall"
            )
        checkout_gate.assert_ready_for_write(
            root, default_branch=branch, require_default_branch=True
        )
    except ProjectInstallError as exc:
        raise ProjectInstallError(
            "project_uninstall_checkout_refused: "
            + str(exc).replace(" or pass --force", "")
        ) from exc


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
            f"retrying project uninstall if its manifest remains. {exc}"
        ) from exc
