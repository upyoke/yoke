"""Resolve one CLI release to its immutable published server image."""

from __future__ import annotations

from yoke_contracts import distribution_target

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_contracts.api_urls import (
    RELEASE_CHANNEL_ENV,
)
from yoke_cli.config.cli_release_runtime import operator_launcher_path
from yoke_contracts.engine_version import local_handshake_version
from yoke_contracts.install_binding import source_checkout_root
from yoke_cli.config.server_image_repository import image_for_release
from yoke_contracts.release_version import commit_version
from yoke_contracts.shell_path_state import tool_bin_dir
from yoke_contracts.terminal_detached_process import run as _RUN

DEFAULT_RELEASE_CHANNEL = "stable"
FETCH_TIMEOUT_SECONDS = 60.0
INSTALLER_RUN_TIMEOUT_SECONDS = 600.0

_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ReleaseTarget:
    """The lockstep client/server identity selected for self-hosting."""

    version: str
    source_commit: str
    image: str
    base_url: str
    channel: str = ""
    installer_url: str = ""


def current_release_target(
    *, base_url: str, image_repository: str | None = None
) -> ReleaseTarget:
    """Resolve the running CLI build to its release image.

    Installed clients resolve their wheel manifest; source checkouts use Git HEAD.
    """
    selected_base = distribution_target.distribution_base_url(base_url)
    version = local_handshake_version().strip()
    if not version:
        return _source_checkout_target(selected_base, image_repository)
    encoded_version = urllib.parse.quote(version, safe="")
    manifest_url = (
        f"{selected_base}/dist/releases/{encoded_version}/migration-history.json"
    )
    payload = fetch_json(manifest_url, f"Yoke {version} release manifest")
    artifact = payload.get("artifact")
    if not isinstance(artifact, dict):
        raise distribution_target.ReleaseTargetError(
            f"Yoke {version} release manifest has no artifact identity; "
            "retry after the release channel is healthy"
        )
    recorded_version = str(artifact.get("engine_version") or "").strip()
    if recorded_version != version:
        raise distribution_target.ReleaseTargetError(
            f"Yoke {version} release manifest names engine {recorded_version or '<missing>'}; "
            "refusing to select a mismatched server image"
        )
    source_commit = _require_source_commit(
        artifact.get("source_commit"), f"Yoke {version} release manifest"
    )
    return _target(
        version=version,
        source_commit=source_commit,
        base_url=selected_base,
        image_repository=image_repository,
    )


def channel_release_target(
    *, channel: str | None = None, base_url: str
) -> ReleaseTarget:
    """Resolve one distribution channel to its lockstep upgrade target."""
    selected_channel = distribution_target.release_channel(
        str(
            channel or os.environ.get(RELEASE_CHANNEL_ENV) or DEFAULT_RELEASE_CHANNEL
        ).strip()
    )
    selected_base = distribution_target.distribution_base_url(base_url)
    channel_url = f"{selected_base}/dist/channels/{selected_channel}.json"
    payload = fetch_json(channel_url, f"{selected_channel} release channel")
    if payload.get("schema_version") != 3:
        raise distribution_target.ReleaseTargetError(
            f"{selected_channel} release channel does not carry source-commit evidence; "
            "retry after the channel publishes schema version 3"
        )
    recorded_channel = str(payload.get("channel") or "").strip()
    if recorded_channel != selected_channel:
        raise distribution_target.ReleaseTargetError(
            f"requested release channel {selected_channel!r} returned "
            f"{recorded_channel or '<missing>'!r}"
        )
    version = str(payload.get("version") or "").strip()
    if not version:
        raise distribution_target.ReleaseTargetError(
            f"{selected_channel} release channel has no version pin"
        )
    migration = payload.get("migration_history")
    if not isinstance(migration, dict):
        raise distribution_target.ReleaseTargetError(
            f"{selected_channel} release channel has no migration-history evidence"
        )
    source_commit = _require_source_commit(
        migration.get("source_commit"), f"{selected_channel} release channel"
    )
    installer = payload.get("installer")
    installer_url = (
        str(installer.get("python_url") or "").strip()
        if isinstance(installer, dict)
        else ""
    )
    expected_installer_url = f"{selected_base}/dist/install.py"
    if installer_url != expected_installer_url:
        raise distribution_target.ReleaseTargetError(
            f"{selected_channel} release channel named an unexpected installer "
            f"endpoint; expected {expected_installer_url}"
        )
    return _target(
        version=version,
        source_commit=source_commit,
        base_url=selected_base,
        channel=selected_channel,
        installer_url=installer_url,
    )


def fetch_installer(target: ReleaseTarget) -> bytes:
    """Fetch the installer bound to a previously validated channel target."""
    if not target.installer_url:
        raise distribution_target.ReleaseTargetError("release target has no installer endpoint")
    return _FETCH_BYTES(target.installer_url)


def installed_cli_version() -> str | None:
    """Probe the active launcher, which may differ from the running CLI."""
    launcher = operator_launcher_path(Path(tool_bin_dir()))
    try:
        completed = _RUN(
            (str(launcher), "--version"),
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None
    return (completed.stdout.strip() or None) if completed.returncode == 0 else None


def installer_command(
    target: ReleaseTarget, path: str, *, extra_args: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """The argv that runs the installer at *path*, pinned to *target*."""
    return (
        sys.executable,
        path,
        "--version",
        target.version,
        "--yes",
        "--no-setup",
        "--base-url",
        target.base_url,
        "--channel",
        target.channel or DEFAULT_RELEASE_CHANNEL,
        *extra_args,
    )


def run_installer(
    target: ReleaseTarget,
    installer_bytes: bytes,
    *,
    extra_args: tuple[str, ...] = (),
    timeout: float = INSTALLER_RUN_TIMEOUT_SECONDS,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a previously fetched installer, pinned to *target*'s exact version.

    The exact version and ``--yes --no-setup`` prevent channel drift.
    Fetching and executing stay separate so their failures remain distinct.
    """
    path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix="yoke-installer-", suffix=".py", delete=False
        ) as handle:
            handle.write(installer_bytes)
            path = handle.name
        return _RUN(
            installer_command(target, path, extra_args=extra_args),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=None if env is None else dict(env),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise distribution_target.ReleaseTargetError(f"the Yoke installer could not run: {exc}") from exc
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _source_checkout_target(
    base_url: str, image_repository: str | None
) -> ReleaseTarget:
    root = source_checkout_root(__file__)
    if root is None:
        raise distribution_target.ReleaseTargetError(
            "this CLI has neither installed release metadata nor a source checkout; "
            "repair the CLI with the public installer, then retry"
        )
    completed = _RUN(
        ("git", "-C", str(root), "show", "-s", "--format=%H %cI", "HEAD"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15.0,
    )
    source_commit, _, clock = str(completed.stdout or "").strip().partition(" ")
    if completed.returncode != 0 or not _SOURCE_COMMIT.fullmatch(source_commit):
        diagnostic = str(completed.stderr or completed.stdout or "").strip()[-1000:]
        raise distribution_target.ReleaseTargetError(
            "source-checkout CLI could not resolve Git HEAD for an exact server "
            f"image; repair the checkout or pass --image explicitly ({diagnostic})"
        )
    try:
        version = commit_version(datetime.fromisoformat(clock))
    except ValueError as exc:
        raise distribution_target.ReleaseTargetError(
            "source release clock invalid: repair Git HEAD metadata and retry"
        ) from exc
    return _target(
        version=version,
        source_commit=source_commit,
        base_url=base_url,
        image_repository=image_repository,
    )


def _target(
    *,
    version: str,
    source_commit: str,
    base_url: str,
    channel: str = "",
    installer_url: str = "",
    image_repository: str | None = None,
) -> ReleaseTarget:
    try:
        image = image_for_release(version, repository=image_repository)
    except ValueError as exc:
        raise distribution_target.ReleaseTargetError(str(exc)) from exc
    return ReleaseTarget(
        version=version,
        source_commit=source_commit,
        image=image,
        base_url=base_url,
        channel=channel,
        installer_url=installer_url,
    )


def _require_source_commit(value: object, label: str) -> str:
    source_commit = str(value or "").strip()
    if not _SOURCE_COMMIT.fullmatch(source_commit):
        raise distribution_target.ReleaseTargetError(
            f"{label} has no valid full source commit; refusing a mutable server image"
        )
    return source_commit


def fetch_json(url: str, label: str, shape: type = dict) -> Any:
    try:
        value = json.loads(_FETCH_BYTES(url).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise distribution_target.ReleaseTargetError(f"{label} is not valid JSON") from exc
    if not isinstance(value, shape):
        raise distribution_target.ReleaseTargetError(f"{label} is not a JSON {shape.__name__}")
    return value


def _fetch_bytes(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise distribution_target.ReleaseTargetError(f"could not fetch {url}: {exc}") from exc


_FETCH_BYTES: Callable[[str], bytes] = _fetch_bytes


__all__ = [
    "DEFAULT_RELEASE_CHANNEL",
    "ReleaseTarget",
    "channel_release_target",
    "current_release_target",
    "fetch_installer",
    "fetch_json",
    "installer_command",
    "run_installer",
]
