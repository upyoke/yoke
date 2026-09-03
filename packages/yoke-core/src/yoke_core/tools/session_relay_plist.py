"""Convergent launchd plist operations for the one-shot machine relay."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from typing import Callable, Mapping, Sequence

from yoke_cli.config import machine_config
from yoke_cli.config.session_relay_instance import (
    PROD_RELAY_LABEL,
    RelayInstance,
    resolve_relay_instance,
)
from yoke_core.tools.install_yoke_launcher_sweep import canonical_shim_path
from yoke_core.tools.launchctl_boundary import (
    bootstrap_launchd_job,
    launch_agents_dir,
    launch_agents_home,
    launchd_target,
    run_launchctl,
    wait_for_launchd_unload,
)
from yoke_core.tools.session_relay_executable import relay_executable_search_path
from yoke_core.tools.session_relay_legacy import (
    LegacyRelayError,
    retire_unpinned_legacy_relay,
)


RELAY_LAUNCHD_LABEL = PROD_RELAY_LABEL
# The relay polls on its own internal cadence, so launchd's job is custody,
# not scheduling: keep the one process alive and restart it if it dies.
# Scheduling from launchd would recreate the cost this daemon exists to
# remove — a fresh interpreter per poll, and a job whose lifetime ends with
# the spawn that leased it.
RELAY_KEEP_ALIVE = True


class RelayInstallError(RuntimeError):
    """The machine relay could not be converged safely."""


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
        "ProcessType": "Background",
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
    return observed == expected and "StartInterval" not in observed


def relay_launchd_status(
    *,
    home: Path | None = None,
    yoke_home: Path | None = None,
    executable: Path | None = None,
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
        executable=executable,
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
    )


def install_relay_launchd(
    *,
    home: Path | None = None,
    yoke_home: Path | None = None,
    executable: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner = run_launchctl,
    platform: str = sys.platform,
    uid: int | None = None,
    config_path: str | Path | None = None,
    environment: str | None = None,
    instance: RelayInstance | None = None,
) -> RelayLaunchdStatus:
    if platform != "darwin":
        raise RelayInstallError("machine relay launchd install requires macOS")
    selected = instance or resolve_relay_instance(
        config_path=config_path,
        environment=environment,
        yoke_home=yoke_home,
    )
    paths = relay_launchd_paths(home=home, instance=selected)
    source_env = os.environ if environ is None else environ
    launcher = executable or canonical_shim_path(source_env)
    if not launcher.is_file():
        raise RelayInstallError(
            f"canonical yoke launcher is missing at {launcher}; repair it first"
        )
    try:
        retire_unpinned_legacy_relay(
            instance=selected,
            home=launch_agents_home(home, yoke_home=selected.yoke_home),
            runner=runner,
            uid=uid,
        )
    except LegacyRelayError as exc:
        raise RelayInstallError(str(exc)) from exc
    paths.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = launchd_target(paths.label, uid)

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _run(command, runner=runner)

    run(["launchctl", "bootout", target])
    if not wait_for_launchd_unload(target, run=run):
        raise RelayInstallError(
            "launchctl kept the machine relay loaded after bootout; wait for "
            f"teardown, then run `yoke --env {paths.environment} relay install`"
        )
    _write_plist(
        paths.plist,
        relay_plist_document(
            executable=launcher,
            paths=paths,
            environ=source_env,
        ),
    )
    domain = f"gui/{os.getuid() if uid is None else uid}"
    result = bootstrap_launchd_job(domain, paths.plist, run=run)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown launchd error").strip()
        raise RelayInstallError(
            "launchctl could not restart the machine relay; the relay is now "
            f"stopped. Run `yoke --env {paths.environment} relay install` to "
            f"bring it back. launchd: {detail}"
        )
    return relay_launchd_status(
        home=home,
        executable=launcher,
        environ=source_env,
        runner=runner,
        platform=platform,
        uid=uid,
        instance=selected,
    )


def uninstall_relay_launchd(
    *,
    home: Path | None = None,
    yoke_home: Path | None = None,
    runner: Runner = run_launchctl,
    platform: str = sys.platform,
    uid: int | None = None,
    config_path: str | Path | None = None,
    environment: str | None = None,
    instance: RelayInstance | None = None,
) -> RelayLaunchdStatus:
    if platform != "darwin":
        raise RelayInstallError("machine relay launchd uninstall requires macOS")
    selected = instance or resolve_relay_instance(
        config_path=config_path,
        environment=environment,
        yoke_home=yoke_home,
    )
    paths = relay_launchd_paths(home=home, instance=selected)
    target = launchd_target(paths.label, uid)

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _run(command, runner=runner)

    run(["launchctl", "bootout", target])
    if not wait_for_launchd_unload(target, run=run):
        raise RelayInstallError(
            "launchctl kept the exact machine relay loaded after bootout; retry "
            f"`yoke --env {paths.environment} relay uninstall` after teardown"
        )
    try:
        paths.plist.unlink()
    except FileNotFoundError:
        pass
    return relay_launchd_status(
        home=home,
        runner=runner,
        platform=platform,
        uid=uid,
        instance=selected,
    )


__all__ = [
    "RELAY_LAUNCHD_LABEL",
    "RELAY_KEEP_ALIVE",
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
