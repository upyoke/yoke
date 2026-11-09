"""Paths, launchd document and observation of one machine relay."""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from typing import Callable, Mapping, Sequence
from yoke_contracts.machine_config import paths as machine_config
from yoke_contracts.machine_config.relay_instance import RELAY_BASE_LABEL, RelayInstance, resolve_relay_instance
from yoke_core.domain.launchctl_boundary import launch_agents_dir, launch_agents_home, launchd_target, run_launchctl
from yoke_core.domain.session_relay_executable import relay_executable_search_path
from yoke_core.domain import relay_launcher_path as relay_install

RELAY_LAUNCHD_LABEL = RELAY_BASE_LABEL



RELAY_KEEP_ALIVE = {"SuccessfulExit": False}



class RelayInstallError(RuntimeError):
    """The machine relay could not be converged safely."""

    def __init__(self, message: str, *, code: str = "relay_lifecycle_failed") -> None:
        super().__init__(message)
        self.code = code



@dataclass(frozen=True)
class RelayLaunchdPaths:
    plist: Path
    state_dir: Path
    stdout_log: Path
    stderr_log: Path
    environment: str = ""
    label: str = RELAY_LAUNCHD_LABEL
    config_path: Path | None = None
    yoke_home: Path | None = None
    follows_served_release: bool = True



@dataclass(frozen=True)
class RelayLaunchdStatus:
    supported: bool
    plist_present: bool
    plist_current: bool
    loaded: bool
    plist_path: Path
    environment: str = ""
    label: str = RELAY_LAUNCHD_LABEL
    state_dir: Path | None = None
    follows_served_release: bool = True



Runner = Callable[..., subprocess.CompletedProcess[str]]



def relay_launchd_paths(
    *,
    home: Path | None = None,
    yoke_home: Path | None = None,
    config_path: str | Path | None = None,
    environment: str | None = None,
    instance: RelayInstance | None = None,
) -> RelayLaunchdPaths:
    selected = instance or resolve_relay_instance(
        config_path=config_path,
        environment=environment,
        yoke_home=yoke_home,
    )
    user_home = launch_agents_home(home, yoke_home=selected.yoke_home)
    state = selected.state_dir
    return RelayLaunchdPaths(
        plist=launch_agents_dir(user_home) / f"{selected.label}.plist",
        state_dir=state,
        stdout_log=selected.stdout_log,
        stderr_log=selected.stderr_log,
        environment=selected.environment,
        label=selected.label,
        config_path=selected.config_path,
        yoke_home=selected.yoke_home,
        follows_served_release=selected.follows_served_release,
    )



def relay_plist_document(
    *,
    paths: RelayLaunchdPaths | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    resolved = paths or relay_launchd_paths()
    source_env = os.environ if environ is None else environ
    launcher = relay_install.relay_launcher_path(
        resolved.state_dir,
        follows_served_release=resolved.follows_served_release,
    )
    return {
        "Label": resolved.label,
        "ProgramArguments": [
            str(launcher),
            "--env",
            resolved.environment,
            "relay",
            "serve",
        ],
        "EnvironmentVariables": {
            "PATH": relay_executable_search_path(
                executable=launcher,
                environ=source_env,
            ),
            machine_config.CONFIG_FILE_ENV: str(resolved.config_path),
            machine_config.HOME_ENV: str(resolved.yoke_home),
        },
        "RunAtLoad": True,
        "KeepAlive": RELAY_KEEP_ALIVE,
        "StandardOutPath": str(resolved.stdout_log),
        "StandardErrorPath": str(resolved.stderr_log),
    }



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



def _document_is_current(
    path: Path,
    expected: dict[str, object],
) -> bool:
    try:
        with path.open("rb") as handle:
            observed = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False
    return observed == expected and "StartInterval" not in observed



def relay_launchd_status(
    *,
    home: Path | None = None,
    yoke_home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner = run_launchctl,
    platform: str = sys.platform,
    uid: int | None = None,
    config_path: str | Path | None = None,
    environment: str | None = None,
    instance: RelayInstance | None = None,
) -> RelayLaunchdStatus:
    selected = instance or resolve_relay_instance(
        config_path=config_path,
        environment=environment,
        yoke_home=yoke_home,
    )
    paths = relay_launchd_paths(home=home, instance=selected)
    expected = relay_plist_document(
        paths=paths,
        environ=environ,
    )
    present = paths.plist.is_file()
    loaded = False
    if platform == "darwin":
        loaded = (
            _run(
                ["launchctl", "print", launchd_target(paths.label, uid)],
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
        environment=paths.environment,
        label=paths.label,
        state_dir=paths.state_dir,
        follows_served_release=paths.follows_served_release,
    )

