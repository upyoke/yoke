"""Install the machine relay from the release served by its environment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import uuid

from packaging.version import InvalidVersion, Version
from yoke_cli import manifest
from yoke_cli.config import machine_config
from yoke_cli.config.session_relay_instance import (
    RelayInstance,
    resolve_relay_instance,
)
from yoke_contracts.api_urls import (
    DISTRIBUTION_PROD_URL,
    DISTRIBUTION_STAGE_URL,
    HOSTED_PROD_API_URL,
    HOSTED_STAGE_API_URL,
)


RELAY_VENV_NAME = "venv"
RELAY_RELEASE_RECEIPT_NAME = ".yoke-relay-release.json"
RELAY_RELEASE_ERROR_NAME = "release-pin-error.json"
RELAY_RELEASE_FETCH_FAILED = "relay_release_fetch_failed"
RELAY_RELEASE_INSTALL_FAILED = "relay_release_install_failed"


class RelayReleaseError(RuntimeError):
    """A served relay release could not be installed without losing fallback."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RelayReleaseStatus:
    """Installed and served identities for one environment's daemon."""

    pinned_release: str
    served_build: str
    distribution_index: str
    executable: Path
    python: Path
    current: bool
    error_code: str = ""
    error_message: str = ""


ManifestFetcher = Callable[[str], Mapping[str, Any] | None]


def relay_venv_path(state_dir: Path) -> Path:
    return Path(state_dir) / RELAY_VENV_NAME


def relay_release_executable(state_dir: Path) -> Path:
    return relay_venv_path(state_dir) / "bin" / "yoke"


def relay_release_python(state_dir: Path) -> Path:
    return relay_venv_path(state_dir) / "bin" / "python"


def release_version_from_build(build: str) -> str:
    """Normalize a handshake build into the exact PEP 440 wheel version."""
    raw = str(build or "").strip()
    if raw.startswith("v"):
        raw = raw[1:]
    try:
        version = Version(raw)
    except InvalidVersion as exc:
        raise RelayReleaseError(
            RELAY_RELEASE_FETCH_FAILED,
            f"served build {build!r} is not a valid Yoke release version",
        ) from exc
    if version.local is None:
        raise RelayReleaseError(
            RELAY_RELEASE_FETCH_FAILED,
            f"served build {build!r} has no immutable release segment",
        )
    return str(version)


def distribution_index_for_instance(instance: RelayInstance) -> str:
    """Resolve the wheel index belonging to the selected environment."""
    try:
        connection = machine_config.active_connection(
            instance.config_path,
            explicit_env=instance.environment,
        )
    except Exception as exc:  # noqa: BLE001 - normalize config refusal
        raise RelayReleaseError(
            RELAY_RELEASE_FETCH_FAILED,
            f"could not resolve environment {instance.environment!r}: {exc}",
        ) from exc
    api_url = str(connection.get("api_url") or "").strip().rstrip("/")
    parsed = urlsplit(api_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RelayReleaseError(
            RELAY_RELEASE_FETCH_FAILED,
            f"environment {instance.environment!r} has no valid HTTP(S) API origin",
        )
    hosted_prod = urlsplit(HOSTED_PROD_API_URL).hostname
    hosted_stage = urlsplit(HOSTED_STAGE_API_URL).hostname
    if parsed.hostname == hosted_prod:
        base = DISTRIBUTION_PROD_URL
    elif parsed.hostname == hosted_stage:
        base = DISTRIBUTION_STAGE_URL
    else:
        try:
            port = parsed.port
        except ValueError as exc:
            raise RelayReleaseError(
                RELAY_RELEASE_FETCH_FAILED,
                f"environment {instance.environment!r} has an invalid API port",
            ) from exc
        hostname = str(parsed.hostname or "")
        host = f"[{hostname}]" if ":" in hostname else hostname
        netloc = f"{host}:{port}" if port else host
        base = urlunsplit((parsed.scheme, netloc, "", "", "")).rstrip("/")
    return f"{base}/simple/"


def fetch_served_build(
    instance: RelayInstance,
    *,
    fetch_manifest: ManifestFetcher = manifest.fetch_env_manifest,
) -> str:
    """Read the release header from the environment's authenticated manifest."""
    try:
        payload = fetch_manifest(instance.environment)
    except Exception as exc:  # noqa: BLE001 - normalize transport refusal
        raise RelayReleaseError(
            RELAY_RELEASE_FETCH_FAILED,
            f"environment {instance.environment!r} handshake failed: {exc}",
        ) from exc
    build = (
        str(payload.get("server_engine_version") or "").strip()
        if isinstance(payload, Mapping)
        else ""
    )
    if not build:
        raise RelayReleaseError(
            RELAY_RELEASE_FETCH_FAILED,
            f"environment {instance.environment!r} did not return its served build",
        )
    release_version_from_build(build)
    return build if build.startswith("v") else f"v{build}"


def relay_release_status(
    *,
    instance: RelayInstance | None = None,
    refresh_served: bool = True,
    fetch_manifest: ManifestFetcher = manifest.fetch_env_manifest,
) -> RelayReleaseStatus:
    """Inspect the current venv receipt and optionally refresh the served build."""
    selected = instance or resolve_relay_instance()
    receipt = _read_json(
        relay_venv_path(selected.state_dir) / RELAY_RELEASE_RECEIPT_NAME
    )
    pinned = str(receipt.get("pinned_release") or "")
    index = str(receipt.get("distribution_index") or "")
    served = str(receipt.get("served_build") or "")
    observed_error: RelayReleaseError | None = None
    if refresh_served:
        try:
            served = fetch_served_build(selected, fetch_manifest=fetch_manifest)
            if not index:
                index = distribution_index_for_instance(selected)
        except RelayReleaseError as exc:
            served = ""
            observed_error = exc
    recorded_error = _read_json(selected.state_dir / RELAY_RELEASE_ERROR_NAME)
    error_code = str(recorded_error.get("code") or "")
    error_message = str(recorded_error.get("message") or "")
    if observed_error is not None:
        error_code = observed_error.code
        error_message = str(observed_error)
    executable = relay_release_executable(selected.state_dir)
    python = relay_release_python(selected.state_dir)
    current = bool(executable.is_file() and python.is_file() and pinned and served)
    if current:
        try:
            current = pinned == release_version_from_build(served)
        except RelayReleaseError as exc:
            current = False
            if not error_code:
                error_code = RELAY_RELEASE_INSTALL_FAILED
                error_message = f"installed relay receipt is invalid: {exc}"
    return RelayReleaseStatus(
        pinned_release=pinned,
        served_build=served,
        distribution_index=index,
        executable=executable,
        python=python,
        current=current,
        error_code=error_code,
        error_message=error_message,
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def write_release_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(dict(value), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "RELAY_RELEASE_FETCH_FAILED",
    "RELAY_RELEASE_INSTALL_FAILED",
    "RelayReleaseError",
    "RelayReleaseStatus",
    "distribution_index_for_instance",
    "fetch_served_build",
    "relay_release_executable",
    "relay_release_python",
    "relay_release_status",
    "relay_venv_path",
    "release_version_from_build",
    "write_release_json",
]
