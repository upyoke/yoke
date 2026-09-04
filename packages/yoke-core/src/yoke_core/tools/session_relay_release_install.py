"""Atomic installer for the environment-pinned machine-relay venv."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterator
import uuid
import venv

from yoke_cli import manifest
from yoke_cli.config.session_relay_instance import RelayInstance, resolve_relay_instance
from yoke_core.tools.session_relay_release import (
    ManifestFetcher,
    RELAY_RELEASE_ERROR_NAME,
    RELAY_RELEASE_FETCH_FAILED,
    RELAY_RELEASE_INSTALL_FAILED,
    RELAY_RELEASE_RECEIPT_NAME,
    RELAY_VENV_NAME,
    RelayReleaseError,
    RelayReleaseStatus,
    distribution_index_for_instance,
    fetch_served_build,
    relay_release_executable,
    relay_release_python,
    relay_release_status,
    relay_venv_path,
    release_version_from_build,
    write_release_json,
)


RELAY_RELEASES_DIR_NAME = "releases"
RELAY_RELEASE_LOCK_NAME = "release-pin.lock"
PRODUCT_REQUIREMENT = "yoke-core"

Runner = Callable[..., subprocess.CompletedProcess[str]]
VenvCreator = Callable[[Path], None]


def pin_relay_release(
    *,
    instance: RelayInstance | None = None,
    served_build: str | None = None,
    fetch_manifest: ManifestFetcher = manifest.fetch_env_manifest,
    create_venv: VenvCreator | None = None,
    runner: Runner = subprocess.run,
) -> RelayReleaseStatus:
    """Converge the stable venv symlink without replacing a good pin on failure."""
    selected = instance or resolve_relay_instance()
    try:
        observed = served_build or fetch_served_build(
            selected, fetch_manifest=fetch_manifest
        )
        observed = str(observed)
        if not observed.startswith("v"):
            observed = f"v{observed}"
        release = release_version_from_build(observed)
        index = distribution_index_for_instance(selected)
    except RelayReleaseError as exc:
        refusal = _with_recovery(selected, exc.code, str(exc))
        _record_failure(selected, refusal.code, str(refusal), str(served_build or ""))
        raise refusal from exc

    try:
        selected.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with _release_lock(selected.state_dir):
            existing = relay_release_status(instance=selected, refresh_served=False)
            if existing.current and existing.pinned_release == release:
                _clear_failure(selected.state_dir)
                return _status(selected, release, observed, index)
            _install_candidate(
                selected,
                release=release,
                served_build=observed,
                index=index,
                create_venv=create_venv or _create_venv,
                runner=runner,
            )
            _clear_failure(selected.state_dir)
    except RelayReleaseError as exc:
        refusal = _with_recovery(selected, exc.code, str(exc))
        _record_failure(selected, refusal.code, str(refusal), observed)
        raise refusal from exc
    except Exception as exc:  # noqa: BLE001 - preserve the working pin
        refusal = _with_recovery(
            selected,
            RELAY_RELEASE_INSTALL_FAILED,
            f"relay venv install failed: {type(exc).__name__}: {exc}",
        )
        _record_failure(selected, refusal.code, str(refusal), observed)
        raise refusal from exc
    return _status(selected, release, observed, index)


def _status(
    instance: RelayInstance, release: str, served_build: str, index: str
) -> RelayReleaseStatus:
    return RelayReleaseStatus(
        pinned_release=release,
        served_build=served_build,
        distribution_index=index,
        executable=relay_release_executable(instance.state_dir),
        python=relay_release_python(instance.state_dir),
        current=True,
    )


def _install_candidate(
    instance: RelayInstance,
    *,
    release: str,
    served_build: str,
    index: str,
    create_venv: VenvCreator,
    runner: Runner,
) -> None:
    releases = instance.state_dir / RELAY_RELEASES_DIR_NAME
    releases.mkdir(mode=0o700, parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    candidate = releases / token
    link = instance.state_dir / f".{RELAY_VENV_NAME}-{token}"
    activated = False
    try:
        create_venv(candidate)
        python = candidate / "bin" / "python"
        result = runner(
            [
                str(python),
                "-m",
                "pip",
                "--isolated",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "--only-binary",
                ":all:",
                "--extra-index-url",
                index,
                f"{PRODUCT_REQUIREMENT}=={release}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RelayReleaseError(
                RELAY_RELEASE_FETCH_FAILED,
                f"could not fetch {PRODUCT_REQUIREMENT}=={release} from "
                f"{index}: {_command_detail(result)}",
            )
        verified = runner(
            [
                str(python),
                "-c",
                "from importlib.metadata import version; print(version('yoke-core'))",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        executable = candidate / "bin" / "yoke"
        if verified.returncode != 0 or verified.stdout.strip() != release:
            raise RelayReleaseError(
                RELAY_RELEASE_INSTALL_FAILED,
                f"installed relay release did not verify as {release}: "
                f"{_command_detail(verified)}",
            )
        if not executable.is_file():
            raise RelayReleaseError(
                RELAY_RELEASE_INSTALL_FAILED,
                f"installed relay release {release} has no yoke executable",
            )
        write_release_json(
            candidate / RELAY_RELEASE_RECEIPT_NAME,
            {
                "schema": 1,
                "pinned_release": release,
                "served_build": served_build,
                "distribution_index": index,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        link.symlink_to(candidate, target_is_directory=True)
        os.replace(link, relay_venv_path(instance.state_dir))
        activated = True
    finally:
        if not activated:
            try:
                link.unlink()
            except OSError:
                pass
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)


def _create_venv(path: Path) -> None:
    venv.EnvBuilder(with_pip=True).create(path)


@contextmanager
def _release_lock(state_dir: Path) -> Iterator[None]:
    with (state_dir / RELAY_RELEASE_LOCK_NAME).open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _with_recovery(
    instance: RelayInstance, code: str, detail: str
) -> RelayReleaseError:
    pinned = relay_release_status(
        instance=instance, refresh_served=False
    ).pinned_release
    preservation = (
        f"kept pinned release {pinned}"
        if pinned
        else "did not replace any prior relay release"
    )
    return RelayReleaseError(
        code,
        f"{code}: {detail}; {preservation}. Recovery: verify `yoke --env "
        f"{instance.environment} status`, then retry `yoke --env "
        f"{instance.environment} relay install`.",
    )


def _record_failure(
    instance: RelayInstance, code: str, message: str, served_build: str
) -> None:
    try:
        instance.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_release_json(
            instance.state_dir / RELAY_RELEASE_ERROR_NAME,
            {
                "code": code,
                "message": message,
                "served_build": served_build,
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except OSError:
        pass


def _clear_failure(state_dir: Path) -> None:
    try:
        (state_dir / RELAY_RELEASE_ERROR_NAME).unlink()
    except FileNotFoundError:
        pass


def _command_detail(result: subprocess.CompletedProcess[str]) -> str:
    value = str(result.stderr or result.stdout or f"exit {result.returncode}").strip()
    return value[-1200:]


__all__ = ["pin_relay_release"]
