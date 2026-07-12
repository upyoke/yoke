"""Bounded, transactional repo-local Git config operations for Yoke helpers."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
from typing import Iterator

from yoke_cli.config.project_git_environment import git_config_env
from yoke_cli.config.project_git_process import (
    NetworkGitBoundaryError,
    run_network_git,
)


REPO_CONFIG_TIMEOUT_SECONDS = 5.0
REPO_CONFIG_OUTPUT_MAX_BYTES = 1024 * 1024


class GitHubRepoConfigError(RuntimeError):
    """A checkout's local Git config could not be read or changed safely."""


def values(root: Path, key: str) -> list[str]:
    result = _run(root, "config", "--local", "--get-all", key)
    if result.returncode not in (0, 1):
        raise GitHubRepoConfigError("repo-local Git config could not be read")
    return result.stdout.splitlines()


def helper_keys(root: Path) -> list[str]:
    result = _run(
        root, "config", "--local", "--name-only", "--get-regexp",
        r"^credential\..*\.helper$",
    )
    if result.returncode not in (0, 1):
        raise GitHubRepoConfigError("repo-local helper config could not be read")
    return list(dict.fromkeys(result.stdout.splitlines()))


def matching_remote_urls(root: Path) -> list[str]:
    result = _run(
        root, "config", "--local", "--get-regexp", r"^remote\..*\.url$",
    )
    if result.returncode not in (0, 1):
        raise GitHubRepoConfigError("repo-local remote config could not be read")
    urls: list[str] = []
    for line in result.stdout.splitlines():
        _key, separator, raw_url = line.partition(" ")
        if separator:
            urls.append(raw_url)
    return urls


def replace_values(
    root: Path,
    key: str,
    *,
    expected: list[str],
    replacement: list[str],
) -> None:
    """CAS-rewrite one multivalue key and roll back a partial write."""

    with _repo_lock(root):
        if values(root, key) != expected:
            raise GitHubRepoConfigError(
                "repo-local helper config changed during maintenance"
            )
        try:
            _write_values(root, key, replacement)
            if values(root, key) != replacement:
                raise GitHubRepoConfigError(
                    "repo-local helper config did not match the requested chain"
                )
        except (OSError, GitHubRepoConfigError) as exc:
            try:
                _write_values(root, key, expected)
            except (OSError, GitHubRepoConfigError) as rollback_exc:
                raise GitHubRepoConfigError(
                    "repo-local helper config write and rollback both failed"
                ) from rollback_exc
            raise GitHubRepoConfigError(
                "repo-local helper config could not be updated"
            ) from exc


def _write_values(root: Path, key: str, selected: list[str]) -> None:
    unset = _run(root, "config", "--local", "--unset-all", key)
    if unset.returncode not in (0, 5):
        raise GitHubRepoConfigError("repo-local helper config could not be reset")
    for value in selected:
        added = _run(root, "config", "--local", "--add", key, value)
        if added.returncode != 0:
            raise GitHubRepoConfigError("repo-local helper config could not be written")


def _run(root: Path, *args: str):
    try:
        return run_network_git(
            ["git", *args], cwd=root, env=git_config_env(()),
            timeout_seconds=REPO_CONFIG_TIMEOUT_SECONDS,
            maximum_output_bytes=REPO_CONFIG_OUTPUT_MAX_BYTES,
        )
    except (OSError, NetworkGitBoundaryError) as exc:
        raise GitHubRepoConfigError(
            "repo-local Git config operation exceeded its safety boundary"
        ) from exc


@contextmanager
def _repo_lock(root: Path) -> Iterator[None]:
    git_dir = _run(root, "rev-parse", "--absolute-git-dir")
    if git_dir.returncode != 0:
        raise GitHubRepoConfigError("checkout Git directory could not be resolved")
    directory = Path(git_dir.stdout.strip())
    try:
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or directory.is_symlink():
            raise GitHubRepoConfigError("checkout Git directory is unsafe")
        path = directory / "yoke-helper-config.lock"
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise GitHubRepoConfigError("checkout helper lock is unavailable") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise GitHubRepoConfigError("checkout helper lock is unsafe")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


__all__ = [
    "GitHubRepoConfigError",
    "REPO_CONFIG_OUTPUT_MAX_BYTES",
    "REPO_CONFIG_TIMEOUT_SECONDS",
    "helper_keys",
    "matching_remote_urls",
    "replace_values",
    "values",
]
