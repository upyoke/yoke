"""Convergent launchd plist operations for the one-shot machine relay."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from typing import Callable, Mapping, Sequence

from yoke_cli.config import machine_config
from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_core.tools.install_yoke_launcher_core import TARGET_PRIORITY
from yoke_core.tools.install_yoke_launcher_sweep import canonical_shim_path


RELAY_LAUNCHD_LABEL = "com.upyoke.relay"
RELAY_PLIST_NAME = f"{RELAY_LAUNCHD_LABEL}.plist"
_RELAY_POLL_POLICY = FLEET_KEY_SPECS["fleet.relay_poll_seconds"]
# launchd must wake frequently enough to honor every valid server cadence. The
# relay's disk-backed due time still prevents calls before the server asks.
RELAY_START_INTERVAL_SECONDS = int(
    _RELAY_POLL_POLICY.minimum or _RELAY_POLL_POLICY.default
)
_RELAY_CLI_EXECUTABLES = ("claude", "codex", "cursor-agent")


class RelayInstallError(RuntimeError):
    """The machine relay could not be converged safely."""


@dataclass(frozen=True)
class RelayLaunchdPaths:
    plist: Path
    state_dir: Path
    stdout_log: Path
    stderr_log: Path


@dataclass(frozen=True)
class RelayLaunchdStatus:
    supported: bool
    plist_present: bool
    plist_current: bool
    loaded: bool
    plist_path: Path


Runner = Callable[..., subprocess.CompletedProcess[str]]


def relay_launchd_paths(
    *,
    home: Path | None = None,
    yoke_home: Path | None = None,
) -> RelayLaunchdPaths:
    user_home = (home or Path.home()).expanduser()
    state = (yoke_home or machine_config.yoke_home()) / "relay"
    return RelayLaunchdPaths(
        plist=user_home / "Library" / "LaunchAgents" / RELAY_PLIST_NAME,
        state_dir=state,
        stdout_log=state / "relay.stdout.log",
        stderr_log=state / "relay.stderr.log",
    )


def relay_plist_document(
    *,
    executable: Path | None = None,
    paths: RelayLaunchdPaths | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    resolved = paths or relay_launchd_paths()
    source_env = os.environ if environ is None else environ
    launcher = executable or canonical_shim_path(source_env)
    return {
        "Label": RELAY_LAUNCHD_LABEL,
        "ProgramArguments": [str(launcher), "relay", "serve-once"],
        "EnvironmentVariables": {
            "PATH": relay_executable_search_path(
                executable=launcher,
                environ=source_env,
            )
        },
        "ProcessType": "Background",
        "RunAtLoad": True,
        "StartInterval": RELAY_START_INTERVAL_SECONDS,
        "StandardOutPath": str(resolved.stdout_log),
        "StandardErrorPath": str(resolved.stderr_log),
    }


def relay_executable_search_path(
    *,
    executable: Path,
    environ: Mapping[str, str],
) -> str:
    """Build a stable, bounded launchd path for Yoke and native CLIs."""
    candidates = [executable.expanduser().parent]
    ambient_path = environ.get("PATH", "")
    for command in _RELAY_CLI_EXECUTABLES:
        resolved = shutil.which(command, path=ambient_path)
        if resolved:
            candidates.append(Path(resolved).expanduser().parent)
    candidates.extend(Path(raw).expanduser() for raw, _label in TARGET_PRIORITY)
    candidates.extend(Path(raw) for raw in os.defpath.split(os.pathsep) if raw)
    unique: list[str] = []
    for candidate in candidates:
        value = str(candidate)
        if candidate.is_absolute() and value not in unique:
            unique.append(value)
    return os.pathsep.join(unique)


def _launchd_target(uid: int | None = None) -> str:
    return f"gui/{os.getuid() if uid is None else uid}/{RELAY_LAUNCHD_LABEL}"


def _launchd_domain(uid: int | None = None) -> str:
    return f"gui/{os.getuid() if uid is None else uid}"


def _run(
    command: Sequence[str],
    *,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise RelayInstallError(f"launchctl is unavailable: {exc}") from exc


def _write_plist(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(plistlib.dumps(document, sort_keys=True))
    temporary.chmod(0o600)
    temporary.replace(path)


def _document_is_current(
    path: Path,
    expected: dict[str, object],
) -> bool:
    try:
        with path.open("rb") as handle:
            observed = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False
    return observed == expected and "KeepAlive" not in observed


def relay_launchd_status(
    *,
    home: Path | None = None,
    yoke_home: Path | None = None,
    executable: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner = subprocess.run,
    platform: str = sys.platform,
    uid: int | None = None,
) -> RelayLaunchdStatus:
    paths = relay_launchd_paths(home=home, yoke_home=yoke_home)
    expected = relay_plist_document(
        executable=executable,
        paths=paths,
        environ=environ,
    )
    present = paths.plist.is_file()
    loaded = False
    if platform == "darwin":
        loaded = (
            _run(
                ["launchctl", "print", _launchd_target(uid)],
                runner=runner,
            ).returncode
            == 0
        )
    return RelayLaunchdStatus(
        supported=platform == "darwin",
        plist_present=present,
        plist_current=present and _document_is_current(paths.plist, expected),
        loaded=loaded,
        plist_path=paths.plist,
    )


def install_relay_launchd(
    *,
    home: Path | None = None,
    yoke_home: Path | None = None,
    executable: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner = subprocess.run,
    platform: str = sys.platform,
    uid: int | None = None,
) -> RelayLaunchdStatus:
    if platform != "darwin":
        raise RelayInstallError("machine relay launchd install requires macOS")
    paths = relay_launchd_paths(home=home, yoke_home=yoke_home)
    source_env = os.environ if environ is None else environ
    launcher = executable or canonical_shim_path(source_env)
    if not launcher.is_file():
        raise RelayInstallError(
            f"canonical yoke launcher is missing at {launcher}; repair it first"
        )
    paths.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _run(["launchctl", "bootout", _launchd_target(uid)], runner=runner)
    _write_plist(
        paths.plist,
        relay_plist_document(
            executable=launcher,
            paths=paths,
            environ=source_env,
        ),
    )
    result = _run(
        ["launchctl", "bootstrap", _launchd_domain(uid), str(paths.plist)],
        runner=runner,
    )
    if result.returncode != 0:
        raise RelayInstallError(
            "launchctl bootstrap refused the machine relay plist: "
            + (result.stderr or result.stdout or "unknown launchd error").strip()
        )
    return relay_launchd_status(
        home=home,
        yoke_home=yoke_home,
        executable=launcher,
        environ=source_env,
        runner=runner,
        platform=platform,
        uid=uid,
    )


def uninstall_relay_launchd(
    *,
    home: Path | None = None,
    yoke_home: Path | None = None,
    runner: Runner = subprocess.run,
    platform: str = sys.platform,
    uid: int | None = None,
) -> RelayLaunchdStatus:
    if platform != "darwin":
        raise RelayInstallError("machine relay launchd uninstall requires macOS")
    paths = relay_launchd_paths(home=home, yoke_home=yoke_home)
    _run(["launchctl", "bootout", _launchd_target(uid)], runner=runner)
    try:
        paths.plist.unlink()
    except FileNotFoundError:
        pass
    return relay_launchd_status(
        home=home,
        yoke_home=yoke_home,
        runner=runner,
        platform=platform,
        uid=uid,
    )


__all__ = [
    "RELAY_LAUNCHD_LABEL",
    "RELAY_PLIST_NAME",
    "RELAY_START_INTERVAL_SECONDS",
    "RelayInstallError",
    "RelayLaunchdPaths",
    "RelayLaunchdStatus",
    "install_relay_launchd",
    "relay_launchd_paths",
    "relay_launchd_status",
    "relay_executable_search_path",
    "relay_plist_document",
    "uninstall_relay_launchd",
]
