"""Repo-local Git credential helper wiring for GitHub HTTPS remotes."""

from __future__ import annotations

import shlex
import sys
import sysconfig
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_git_credential_helper
from yoke_cli.config import machine_config
from yoke_cli.config.project_git_transport import run_git
from yoke_contracts.machine_config import schema as contract


GITHUB_CREDENTIAL_HELPER_KEY = "credential.https://github.com.helper"
GIT_CREDENTIAL_HELPER_KEY = "credential.helper"
STABLE_HELPER_FILE_NAME = "_yoke_github_git_credential_helper.py"


def configure_repo_helper(
    root: Path,
    *,
    config_path: str | Path | None,
) -> dict[str, Any]:
    """Configure ``root`` to use the stored machine GitHub token for pushes.

    The helper reads the owner-only token file from Yoke machine config at git
    credential-request time. The token is not embedded in the remote URL or
    persisted in ``.git/config``.
    """
    source = _machine_github_credential_source(config_path)
    if not source:
        return {"configured": False, "reason": "machine-github-not-configured"}
    source_path = str(source.get("path") or "").strip()
    if not source_path:
        return {"configured": False, "reason": "machine-github-token-path-missing"}
    helper_path = install_stable_helper()
    helper = helper_command(config_path=config_path, helper_path=helper_path)
    # An empty helper resets inherited/global helpers for this checkout; the
    # GitHub-specific helper below then serves only github.com HTTPS remotes.
    run_git(root, "config", "--local", GIT_CREDENTIAL_HELPER_KEY, "")
    run_git(root, "config", "--local", GITHUB_CREDENTIAL_HELPER_KEY, helper)
    return {
        "configured": True,
        "key": GITHUB_CREDENTIAL_HELPER_KEY,
        "helper_path": str(helper_path),
        "credential_source": {
            "kind": contract.CREDENTIAL_KIND_TOKEN_FILE,
            "path": str(Path(source_path).expanduser()),
        },
    }


def install_stable_helper(site_dir: str | Path | None = None) -> Path:
    """Install the self-contained Git helper outside editable package imports."""
    target_dir = Path(site_dir) if site_dir is not None else _helper_site_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    helper_path = target_dir / STABLE_HELPER_FILE_NAME
    helper_path.write_text(
        Path(github_git_credential_helper.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return helper_path


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
        "--config",
        shlex.quote(str(machine_config.config_path(config_path))),
        "--token-kind",
        shlex.quote(contract.CREDENTIAL_KIND_TOKEN_FILE),
    ])
    return "!" + " ".join(command)


def _helper_site_dir() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def _machine_github_credential_source(
    config_path: str | Path | None,
) -> Mapping[str, Any] | None:
    try:
        github = machine_config.github_config(config_path)
    except machine_config.MachineConfigError:
        return None
    source = github.get("credential_source") if isinstance(github, Mapping) else None
    if not isinstance(source, Mapping):
        return None
    if str(source.get("kind") or "") != contract.CREDENTIAL_KIND_TOKEN_FILE:
        return None
    return source


__all__ = [
    "GIT_CREDENTIAL_HELPER_KEY",
    "GITHUB_CREDENTIAL_HELPER_KEY",
    "STABLE_HELPER_FILE_NAME",
    "configure_repo_helper",
    "helper_command",
    "install_stable_helper",
]
