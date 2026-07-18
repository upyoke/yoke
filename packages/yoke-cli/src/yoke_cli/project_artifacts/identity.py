"""Bind a rendered artifact bundle to the exact managed checkout."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import existing_project_lookup
from yoke_cli.config import onboard_local_checkout_identity
from yoke_cli.config import project_clone_resume
from yoke_cli.project_install import files as install_files

from .validate import ProjectArtifactError


def assert_checkout_identity(
    repo_root: Path,
    bundle: Mapping[str, Any],
) -> None:
    """Refuse cross-project or wrong-origin planning before any mutation."""

    try:
        reference = existing_project_lookup.find_local_project_reference(
            repo_root,
            config_path=None,
        )
    except existing_project_lookup.ExistingProjectLookupError as exc:
        raise ProjectArtifactError(str(exc)) from exc
    if reference is None:
        raise ProjectArtifactError(
            "artifact refresh requires this checkout to be bound to a Yoke "
            "project by its install manifest or machine config"
        )
    expected_project_id = int(bundle["project_id"])
    if reference.project_id != expected_project_id:
        raise ProjectArtifactError(
            "checkout project binding does not match the rendered artifact "
            f"bundle ({reference.project_id} != {expected_project_id}); no "
            "artifact planning or mutation was attempted"
        )
    install_manifest = install_files.load_manifest(repo_root)
    expected_slug = str(bundle["project_slug"])
    installed_slug = (
        str(install_manifest.get("project_slug") or "")
        if install_manifest is not None
        else ""
    )
    if installed_slug and installed_slug != expected_slug:
        raise ProjectArtifactError(
            "checkout install manifest project slug does not match the "
            f"rendered artifact bundle ({installed_slug} != {expected_slug})"
        )
    checkout_identity = bundle["checkout_identity"]
    github_repo = checkout_identity["github_repo"]
    github_web_url = checkout_identity["github_web_url"]
    if github_repo is None:
        return
    if not project_clone_resume.is_exact_worktree_root(repo_root):
        raise ProjectArtifactError(
            "artifact refresh requires the exact Git worktree root when the "
            "project has a verified repository binding"
        )
    try:
        onboard_local_checkout_identity.require_matching_origin(
            repo_root,
            github_repo=str(github_repo),
            web_url=str(github_web_url),
        )
    except RuntimeError as exc:
        raise ProjectArtifactError(str(exc)) from exc


__all__ = ["assert_checkout_identity"]
