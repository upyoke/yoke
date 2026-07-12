"""Repo-local Git credential helper wiring for GitHub HTTPS remotes."""

from __future__ import annotations

import shlex
import os
import stat
import sys
import sysconfig
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_git_credential_bundle
from yoke_cli.config import github_git_credential_launcher
from yoke_contracts import github_origin
from yoke_cli.config import github_repo_config, machine_config
from yoke_cli.config.project_git_transport import GENERAL_CREDENTIAL_HELPER_KEY
from yoke_contracts.machine_config import schema as contract


GITHUB_CREDENTIAL_HELPER_KEY = "credential.https://github.com.helper"
GIT_CREDENTIAL_HELPER_KEY = GENERAL_CREDENTIAL_HELPER_KEY
STABLE_HELPER_FILE_NAME = github_git_credential_bundle.STABLE_HELPER_FILE_NAME
STABLE_STORE_FILE_NAME = github_git_credential_bundle.STABLE_STORE_FILE_NAME
STABLE_ORIGIN_FILE_NAME = github_git_credential_bundle.STABLE_ORIGIN_FILE_NAME
STABLE_FILE_IO_NAME = github_git_credential_bundle.STABLE_FILE_IO_NAME
STABLE_TOKEN_CONTRACT_NAME = github_git_credential_bundle.STABLE_TOKEN_CONTRACT_NAME
STABLE_RESPONSE_SAFETY_NAME = github_git_credential_bundle.STABLE_RESPONSE_SAFETY_NAME
STABLE_OAUTH_TRANSPORT_NAME = github_git_credential_bundle.STABLE_OAUTH_TRANSPORT_NAME
GitHubCredentialBundleError = github_git_credential_bundle.GitHubCredentialBundleError


def configure_repo_helper(
    root: Path,
    *,
    config_path: str | Path | None,
) -> dict[str, Any]:
    """Configure ``root`` to use the stored machine GitHub credential for pushes.

    The helper reads the owner-only credential file from Yoke machine config at
    git credential-request time. The credential is not embedded in the remote
    URL or persisted in ``.git/config``.
    """
    github = _machine_github_config(config_path)
    authorization = github.get("authorization") if github else None
    authorization = authorization if isinstance(authorization, Mapping) else None
    if not authorization:
        return {"configured": False, "reason": "machine-github-not-configured"}
    credential_ref = str(authorization.get("refresh_credential_ref") or "").strip()
    if not credential_ref:
        return {"configured": False, "reason": "machine-github-credential-ref-missing"}
    helper_path = install_stable_helper()
    helper = helper_command(config_path=config_path, helper_path=helper_path)
    helper_key = credential_helper_key(str(github.get("web_url") or ""))
    # Reset only this URL's helper chain. Global helpers remain available for
    # non-GitHub remotes in a checkout with multiple upstreams.
    try:
        current = github_repo_config.values(root, helper_key)
        if any(
            value and not _is_yoke_helper(value, config_path=config_path)
            for value in current
        ):
            raise RuntimeError(
                "repo-local GitHub helper chain contains a user-managed value"
            )
        github_repo_config.replace_values(
            root, helper_key, expected=current, replacement=["", helper],
        )
    except github_repo_config.GitHubRepoConfigError as exc:
        raise RuntimeError(str(exc)) from exc
    return {
        "configured": True,
        "key": helper_key,
        "helper_path": str(helper_path),
    }


def remove_known_repo_helpers(
    *,
    config_path: str | Path | None,
) -> dict[str, int]:
    """Remove every Yoke URL-scoped helper chain from registered checkouts."""
    removed = 0
    failed = 0
    try:
        checkouts = machine_config.all_registered_checkouts(
            config_path, existing_only=True,
        )
    except (OSError, machine_config.MachineConfigError):
        return {"removed": 0, "failed": 1}
    for root in checkouts:
        result = remove_repo_helpers(root, config_path=config_path)
        removed += result["removed"]
        failed += result["failed"]
    return {"removed": removed, "failed": failed}


def remove_repo_helpers(
    root: Path, *, config_path: str | Path | None,
) -> dict[str, int]:
    """Remove exact Yoke values/resets while preserving the user chain."""

    removed = 0
    failed = 0
    try:
        keys = github_repo_config.helper_keys(root)
    except github_repo_config.GitHubRepoConfigError:
        return {"removed": 0, "failed": 1}
    for key in keys:
        try:
            current = github_repo_config.values(root, key)
            if any(
                _looks_like_yoke_helper(value)
                and not _is_yoke_helper(value, config_path=config_path)
                for value in current
            ):
                failed += 1
                continue
            replacement = _without_owned_helpers(
                current, config_path=config_path,
            )
            if replacement == current:
                continue
            github_repo_config.replace_values(
                root, key, expected=current, replacement=replacement,
            )
            removed += 1
        except github_repo_config.GitHubRepoConfigError:
            failed += 1
    return {"removed": removed, "failed": failed}


def _local_helper_keys(root: Path) -> tuple[list[str], bool]:
    try:
        return github_repo_config.helper_keys(root), False
    except github_repo_config.GitHubRepoConfigError:
        return [], True


def _local_config_values(root: Path, key: str) -> tuple[list[str], bool]:
    try:
        return github_repo_config.values(root, key), False
    except github_repo_config.GitHubRepoConfigError:
        return [], True


def _without_owned_helpers(
    values: list[str], *, config_path: str | Path | None,
) -> list[str]:
    remove: set[int] = set()
    for index, value in enumerate(values):
        if not _is_yoke_helper(value, config_path=config_path):
            continue
        remove.add(index)
        preceding = index - 1
        if preceding >= 0 and values[preceding] == "":
            remove.add(preceding)
    return [value for index, value in enumerate(values) if index not in remove]


def _is_yoke_helper(
    value: str,
    *,
    config_path: str | Path | None,
) -> bool:
    """Recognize only the exact helper command shape installed by Yoke."""
    if not value.startswith("!"):
        return False
    try:
        command = shlex.split(value[1:])
    except ValueError:
        return False
    if len(command) != 4 or command[2] != "--config":
        return False
    expected = (
        Path(sys.executable).expanduser().resolve(strict=False),
        (_helper_site_dir() / STABLE_HELPER_FILE_NAME).resolve(strict=False),
        machine_config.config_path(config_path).resolve(strict=False),
    )
    actual = (
        Path(command[0]).expanduser().resolve(strict=False),
        Path(command[1]).expanduser().resolve(strict=False),
        Path(command[3]).expanduser().resolve(strict=False),
    )
    if actual == expected:
        return True
    return (
        actual[2] == expected[2]
        and actual[1].name == STABLE_HELPER_FILE_NAME
        and _verified_prior_runtime_helper(actual[0], actual[1])
    )


def _verified_prior_runtime_helper(python: Path, helper: Path) -> bool:
    """Recognize a safe prior-runtime launcher without trusting its path."""

    try:
        python_info = python.stat()
        if (
            not stat.S_ISREG(python_info.st_mode)
            or stat.S_IMODE(python_info.st_mode) & 0o022
            or not os.access(python, os.X_OK)
        ):
            return False
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(
            os, "O_NONBLOCK", 0,
        )
        descriptor = os.open(helper, flags)
    except OSError:
        return False
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_size > 256 * 1024
        ):
            return False
        source = os.read(descriptor, 256 * 1024 + 1)
    except OSError:
        return False
    finally:
        os.close(descriptor)
    if not all(marker in source for marker in (
        b'BUNDLE_POINTER_NAME = "_yoke_github_helper_current"',
        b'BUNDLE_HELPER_NAME = "_yoke_github_git_credential_helper.py"',
        b"def selected_bundle(",
    )):
        return False
    try:
        # The stable launcher is meaningful only beside a content-addressed,
        # integrity-checked bundle.  Marker-shaped files on their own remain
        # user-managed lookalikes and must never be removed automatically.
        github_git_credential_launcher.selected_bundle(helper.parent)
    except (OSError, github_git_credential_launcher.GitHubCredentialLauncherError):
        return False
    return True


def _looks_like_yoke_helper(value: str) -> bool:
    return value.startswith("!") and STABLE_HELPER_FILE_NAME in value


def install_stable_helper(site_dir: str | Path | None = None) -> Path:
    """Install the helper under the selected Python runtime."""
    target_dir = Path(site_dir) if site_dir is not None else _helper_site_dir()
    return github_git_credential_bundle.install(target_dir)


def refresh_installed_helper() -> bool:
    """Republish the current bundle only when a prior helper is installed."""
    target_dir = _helper_site_dir()
    if not (target_dir / STABLE_HELPER_FILE_NAME).is_file():
        return False
    install_stable_helper(target_dir)
    return True


def helper_command(
    *,
    config_path: str | Path | None,
    helper_path: str | Path | None = None,
) -> str:
    """Return the git ``credential.helper`` command for this Python runtime."""
    selected_helper = (
        Path(helper_path)
        if helper_path is not None
        else install_stable_helper()
    )
    command = [
        shlex.quote(sys.executable),
        shlex.quote(str(selected_helper)),
    ]
    command.extend([
        "--config", shlex.quote(str(machine_config.config_path(config_path))),
    ])
    return "!" + " ".join(command)


def _helper_site_dir() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def credential_helper_key(web_url: str) -> str:
    endpoint = github_origin.validate_github_web_endpoint(web_url)
    return f"credential.{endpoint.origin}.helper"


def _machine_github_config(
    config_path: str | Path | None,
) -> dict[str, Any]:
    try:
        github = machine_config.github_config(config_path)
    except machine_config.MachineConfigError:
        return {}
    authorization = github.get("authorization") if isinstance(github, Mapping) else None
    if not isinstance(authorization, Mapping):
        return {}
    if authorization.get("kind") != contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION:
        return {}
    if authorization.get("status") != "authorized":
        return {}
    return dict(github)


__all__ = [
    "GIT_CREDENTIAL_HELPER_KEY",
    "GITHUB_CREDENTIAL_HELPER_KEY",
    "STABLE_HELPER_FILE_NAME",
    "STABLE_FILE_IO_NAME",
    "STABLE_ORIGIN_FILE_NAME",
    "STABLE_RESPONSE_SAFETY_NAME",
    "STABLE_TOKEN_CONTRACT_NAME",
    "STABLE_STORE_FILE_NAME",
    "configure_repo_helper",
    "credential_helper_key",
    "helper_command",
    "install_stable_helper",
    "remove_known_repo_helpers",
    "refresh_installed_helper",
]
