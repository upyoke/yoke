"""Retire an unpinned legacy relay without disturbing a pinned prod relay."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
import plistlib
import subprocess

from yoke_cli.config import machine_config
from yoke_cli.config.session_relay_instance import (
    PROD_RELAY_LABEL,
    RelayInstance,
    prod_https_environments,
)


class LegacyRelayError(RuntimeError):
    """The obsolete relay instance could not be retired safely."""


Runner = Callable[..., subprocess.CompletedProcess[str]]

# Serving verbs a pinned prod relay plist may end with.
PINNED_PROD_RELAY_VERBS: frozenset[str] = frozenset({"serve", "serve-once"})


def _canonical(raw: object) -> Path:
    return Path(str(raw or "")).expanduser().resolve(strict=False)


def _is_pinned_prod(path: Path, instance: RelayInstance) -> bool:
    try:
        with path.open("rb") as handle:
            document = plistlib.load(handle)
        arguments = document.get("ProgramArguments")
        environment = document.get("EnvironmentVariables")
        if not isinstance(arguments, Sequence) or isinstance(arguments, str):
            return False
        if not isinstance(environment, Mapping) or len(arguments) < 5:
            return False
        selected = str(arguments[-3])
        # A pinned prod relay is recognized by either serving verb: the
        # standing `serve` this machine installs today, and the `serve-once`
        # an older install still runs. Recognizing only one would let this
        # sweep retire the very relay it is meant to protect.
        if list(arguments[-4:-1]) != ["--env", selected, "relay"]:
            return False
        if str(arguments[-1]) not in PINNED_PROD_RELAY_VERBS:
            return False
        if document.get("Label") != PROD_RELAY_LABEL:
            return False
        if (
            _canonical(environment.get(machine_config.CONFIG_FILE_ENV))
            != instance.config_path
        ):
            return False
        if _canonical(environment.get(machine_config.HOME_ENV)) != instance.yoke_home:
            return False
        payload = machine_config.load_config(instance.config_path)
        return prod_https_environments(payload) == (selected,)
    except (OSError, TypeError, ValueError, plistlib.InvalidFileException):
        return False


def _run(command: list[str], *, runner: Runner) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise LegacyRelayError(f"launchctl is unavailable: {exc}") from exc


def retire_unpinned_legacy_relay(
    *,
    instance: RelayInstance,
    home: Path | None,
    runner: Runner,
    uid: int | None = None,
) -> bool:
    """Remove the old active-env-following job before installing non-prod."""
    if instance.prod:
        return False
    user_home = (home or Path.home()).expanduser()
    legacy_path = user_home / "Library" / "LaunchAgents" / f"{PROD_RELAY_LABEL}.plist"
    if _is_pinned_prod(legacy_path, instance):
        return False

    target = f"gui/{os.getuid() if uid is None else uid}/{PROD_RELAY_LABEL}"
    _run(["launchctl", "bootout", target], runner=runner)
    probe = _run(["launchctl", "print", target], runner=runner)
    if probe.returncode == 0:
        raise LegacyRelayError(
            "launchctl kept the unpinned legacy machine relay loaded"
        )
    try:
        legacy_path.unlink()
    except FileNotFoundError:
        pass
    return True


__all__ = [
    "LegacyRelayError",
    "retire_unpinned_legacy_relay",
]
