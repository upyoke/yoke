"""Transactional local upstream tracking for direct-URL authenticated pushes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yoke_cli.config import github_repo_config
from yoke_cli.config.project_onboard_support import ProjectOnboardError


@dataclass(frozen=True)
class UpstreamSnapshot:
    remote_key: str
    remote_values: list[str]
    configured_remote_values: list[str]
    merge_key: str
    merge_values: list[str]
    configured_merge_values: list[str]


def configure(root: Path, *, remote: str, branch: str) -> UpstreamSnapshot:
    """Set both branch keys before push, rolling back any partial write."""

    remote_key = f"branch.{branch}.remote"
    merge_key = f"branch.{branch}.merge"
    try:
        snapshot = UpstreamSnapshot(
            remote_key=remote_key,
            remote_values=github_repo_config.values(root, remote_key),
            configured_remote_values=[remote],
            merge_key=merge_key,
            merge_values=github_repo_config.values(root, merge_key),
            configured_merge_values=[f"refs/heads/{branch}"],
        )
        github_repo_config.replace_values(
            root, remote_key,
            expected=snapshot.remote_values,
            replacement=snapshot.configured_remote_values,
        )
        try:
            github_repo_config.replace_values(
                root, merge_key,
                expected=snapshot.merge_values,
                replacement=snapshot.configured_merge_values,
            )
        except github_repo_config.GitHubRepoConfigError:
            github_repo_config.replace_values(
                root, remote_key,
                expected=[remote], replacement=snapshot.remote_values,
            )
            raise
        return snapshot
    except github_repo_config.GitHubRepoConfigError as exc:
        raise ProjectOnboardError(
            "GitHub push did not start because upstream tracking could not be "
            "configured safely"
        ) from exc


def restore(root: Path, snapshot: UpstreamSnapshot) -> None:
    """Restore pre-push tracking after a failed/ambiguous push attempt."""

    try:
        github_repo_config.replace_values(
            root, snapshot.merge_key,
            expected=snapshot.configured_merge_values,
            replacement=snapshot.merge_values,
        )
        github_repo_config.replace_values(
            root, snapshot.remote_key,
            expected=snapshot.configured_remote_values,
            replacement=snapshot.remote_values,
        )
    except github_repo_config.GitHubRepoConfigError as exc:
        raise ProjectOnboardError(
            "GitHub push failed and local upstream tracking needs manual repair"
        ) from exc


__all__ = ["UpstreamSnapshot", "configure", "restore"]
