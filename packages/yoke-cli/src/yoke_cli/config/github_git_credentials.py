"""Repo-local Git credential helper wiring for GitHub HTTPS remotes."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
import shlex
import sys
import sysconfig
import tempfile
from pathlib import Path
from typing import Any, Iterator, Mapping

from yoke_cli.config import github_git_credential_helper
from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_git_credential_store
from yoke_contracts import github_app_tokens
from yoke_contracts import github_origin
from yoke_cli.config import machine_config
from yoke_cli.config.project_git_transport import run_git
from yoke_contracts.machine_config import schema as contract


GITHUB_CREDENTIAL_HELPER_KEY = "credential.https://github.com.helper"
GIT_CREDENTIAL_HELPER_KEY = "credential.helper"
STABLE_HELPER_FILE_NAME = "_yoke_github_git_credential_helper.py"
STABLE_STORE_FILE_NAME = "_yoke_github_git_credential_store.py"
STABLE_ORIGIN_FILE_NAME = "_yoke_github_origin.py"
STABLE_FILE_IO_NAME = "_yoke_github_git_credential_file.py"
STABLE_TOKEN_CONTRACT_NAME = "_yoke_github_app_tokens.py"


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
    run_git(root, "config", "--local", "--replace-all", helper_key, "")
    run_git(root, "config", "--local", "--add", helper_key, helper)
    return {
        "configured": True,
        "key": helper_key,
        "helper_path": str(helper_path),
    }


def install_stable_helper(site_dir: str | Path | None = None) -> Path:
    """Install the self-contained Git helper outside editable package imports."""
    target_dir = Path(site_dir) if site_dir is not None else _helper_site_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    helper_path = target_dir / STABLE_HELPER_FILE_NAME
    # Leaves first, then the store, then the entrypoint. The bundle lock keeps
    # concurrent installers from publishing files from interleaved releases;
    # publishing the entrypoint last keeps an old entrypoint on a complete old
    # dependency graph if any earlier write fails.
    sources = (
        (Path(github_origin.__file__), target_dir / STABLE_ORIGIN_FILE_NAME),
        (Path(github_app_tokens.__file__), target_dir / STABLE_TOKEN_CONTRACT_NAME),
        (Path(github_git_credential_file.__file__), target_dir / STABLE_FILE_IO_NAME),
        (Path(github_git_credential_store.__file__), target_dir / STABLE_STORE_FILE_NAME),
        (Path(github_git_credential_helper.__file__), helper_path),
    )
    with _bundle_install_lock(target_dir):
        for source, target in sources:
            _atomic_replace_source(source, target)
    return helper_path


@contextmanager
def _bundle_install_lock(target_dir: Path) -> Iterator[None]:
    lock_path = target_dir / ".yoke-github-helper-install.lock"
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_replace_source(source: Path, target: Path) -> None:
    descriptor, raw_tmp = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    tmp_path = Path(raw_tmp)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, target)
        _fsync_directory(target.parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        tmp_path.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
    "STABLE_TOKEN_CONTRACT_NAME",
    "STABLE_STORE_FILE_NAME",
    "configure_repo_helper",
    "credential_helper_key",
    "helper_command",
    "install_stable_helper",
]
