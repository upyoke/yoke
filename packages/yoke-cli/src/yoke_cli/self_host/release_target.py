"""Resolve one CLI release to its immutable published server image."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from yoke_contracts.api_urls import (
    DISTRIBUTION_BASE_URL_ENV,
    DISTRIBUTION_PROD_URL,
)
from yoke_contracts.engine_version import local_handshake_version
from yoke_contracts.install_binding import source_checkout_root
from yoke_contracts.server_image import pinned_server_image

DEFAULT_RELEASE_CHANNEL = "stable"
FETCH_TIMEOUT_SECONDS = 60.0

_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_CHANNEL = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_RUN = subprocess.run
_FETCH_BYTES: Callable[[str], bytes]


class ReleaseTargetError(RuntimeError):
    """A release cannot be bound to one immutable server image."""


@dataclass(frozen=True)
class ReleaseTarget:
    """The lockstep client/server identity selected for self-hosting."""

    version: str
    source_commit: str
    image: str
    base_url: str
    channel: str = ""
    installer_url: str = ""


def current_release_target(*, base_url: str | None = None) -> ReleaseTarget:
    """Resolve the running CLI build to its release image.

    Installed clients use the immutable migration manifest published beside
    their exact wheel version. A source checkout has no owning wheel version,
    so development runs derive the same image tag directly from Git HEAD.
    """
    selected_base = _distribution_base_url(base_url)
    version = local_handshake_version().strip()
    if not version:
        return _source_checkout_target(selected_base)
    encoded_version = urllib.parse.quote(version, safe="")
    manifest_url = (
        f"{selected_base}/dist/releases/{encoded_version}/migration-history.json"
    )
    payload = _fetch_json(manifest_url, f"Yoke {version} release manifest")
    artifact = payload.get("artifact")
    if not isinstance(artifact, dict):
        raise ReleaseTargetError(
            f"Yoke {version} release manifest has no artifact identity; "
            "retry after the release channel is healthy"
        )
    recorded_version = str(artifact.get("engine_version") or "").strip()
    if recorded_version != version:
        raise ReleaseTargetError(
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
    )


def channel_release_target(
    *, channel: str | None = None, base_url: str | None = None
) -> ReleaseTarget:
    """Resolve one distribution channel to its lockstep upgrade target."""
    selected_channel = str(
        channel or os.environ.get("YOKE_CHANNEL") or DEFAULT_RELEASE_CHANNEL
    ).strip()
    if not _CHANNEL.fullmatch(selected_channel):
        raise ReleaseTargetError(
            f"invalid release channel {selected_channel!r}; use a published channel name"
        )
    selected_base = _distribution_base_url(base_url)
    channel_url = f"{selected_base}/dist/channels/{selected_channel}.json"
    payload = _fetch_json(channel_url, f"{selected_channel} release channel")
    if payload.get("schema_version") != 3:
        raise ReleaseTargetError(
            f"{selected_channel} release channel does not carry source-commit evidence; "
            "retry after the channel publishes schema version 3"
        )
    recorded_channel = str(payload.get("channel") or "").strip()
    if recorded_channel != selected_channel:
        raise ReleaseTargetError(
            f"requested release channel {selected_channel!r} returned "
            f"{recorded_channel or '<missing>'!r}"
        )
    version = str(payload.get("version") or "").strip()
    if not version:
        raise ReleaseTargetError(
            f"{selected_channel} release channel has no version pin"
        )
    migration = payload.get("migration_history")
    if not isinstance(migration, dict):
        raise ReleaseTargetError(
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
        raise ReleaseTargetError(
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
        raise ReleaseTargetError("release target has no installer endpoint")
    return _FETCH_BYTES(target.installer_url)


def _source_checkout_target(base_url: str) -> ReleaseTarget:
    root = source_checkout_root(__file__)
    if root is None:
        raise ReleaseTargetError(
            "this CLI has neither installed release metadata nor a source checkout; "
            "repair the CLI with the public installer, then retry"
        )
    completed = _RUN(
        ("git", "-C", str(root), "rev-parse", "HEAD"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15.0,
    )
    source_commit = str(completed.stdout or "").strip()
    if completed.returncode != 0 or not _SOURCE_COMMIT.fullmatch(source_commit):
        diagnostic = str(completed.stderr or completed.stdout or "").strip()[-1000:]
        raise ReleaseTargetError(
            "source-checkout CLI could not resolve Git HEAD for an exact server "
            f"image; repair the checkout or pass --image explicitly ({diagnostic})"
        )
    return _target(
        version=f"source-{source_commit[:12]}",
        source_commit=source_commit,
        base_url=base_url,
    )


def _target(
    *,
    version: str,
    source_commit: str,
    base_url: str,
    channel: str = "",
    installer_url: str = "",
) -> ReleaseTarget:
    return ReleaseTarget(
        version=version,
        source_commit=source_commit,
        image=pinned_server_image(source_commit),
        base_url=base_url,
        channel=channel,
        installer_url=installer_url,
    )


def _require_source_commit(value: object, label: str) -> str:
    source_commit = str(value or "").strip()
    if not _SOURCE_COMMIT.fullmatch(source_commit):
        raise ReleaseTargetError(
            f"{label} has no valid full source commit; refusing a mutable server image"
        )
    return source_commit


def _distribution_base_url(override: str | None) -> str:
    selected = (
        str(
            override
            or os.environ.get(DISTRIBUTION_BASE_URL_ENV)
            or DISTRIBUTION_PROD_URL
        )
        .strip()
        .rstrip("/")
    )
    parsed = urllib.parse.urlparse(selected)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
    ):
        raise ReleaseTargetError(
            f"invalid Yoke distribution base URL {selected!r}; set "
            f"{DISTRIBUTION_BASE_URL_ENV} to an HTTP(S) origin"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ReleaseTargetError(
            "Yoke distribution base URL must be a credential-free origin"
        )
    return selected


def _fetch_json(url: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(_FETCH_BYTES(url).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseTargetError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseTargetError(f"{label} must be a JSON object")
    return value


def _fetch_bytes(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ReleaseTargetError(f"could not fetch {url}: {exc}") from exc


_FETCH_BYTES = _fetch_bytes


__all__ = [
    "DEFAULT_RELEASE_CHANNEL",
    "ReleaseTarget",
    "ReleaseTargetError",
    "channel_release_target",
    "current_release_target",
    "fetch_installer",
]
