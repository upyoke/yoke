"""Convergent launchd operations for the environment-pinned machine relay."""

from __future__ import annotations

from yoke_core.domain.relay_launchd_status import (
    RELAY_KEEP_ALIVE,
    RELAY_LAUNCHD_LABEL,
    RelayInstallError,
    RelayLaunchdPaths,
    RelayLaunchdStatus,
    Runner,
    _run,
    relay_launchd_paths,
    relay_launchd_status,
    relay_plist_document,
)

from yoke_contracts.machine_config.directories import create_private_directory

import os
from pathlib import Path
import plistlib
import subprocess
import sys
from typing import Callable, Mapping, Sequence

from yoke_contracts.direct_database_access import USE_HTTPS_ENV
from yoke_contracts.machine_config.relay_instance import (
    door_relay_refusal,
    RelayInstance,
    resolve_relay_instance,
)
from yoke_core.domain.launchctl_boundary import (
    bootstrap_launchd_job,
    launchd_target,
    run_launchctl,
    wait_for_launchd_unload,
)
from yoke_core.tools import session_relay_release as relay_release
from yoke_core.domain.session_relay_executable import relay_executable_search_path
from yoke_core.tools import session_relay_release_install as relay_install


# launchd restarts a crash; exit 0 is the daemon's own stop (rejected credential).


def _write_plist(path: Path, document: dict[str, object]) -> None:
    create_private_directory(path.parent)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(plistlib.dumps(document, sort_keys=True))
    temporary.chmod(0o600)
    temporary.replace(path)


def install_relay_launchd(
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
    pin_release: Callable[..., object] = relay_install.pin_relay_release,
) -> RelayLaunchdStatus:
    if platform != "darwin":
        raise RelayInstallError("machine relay launchd install requires macOS")
    selected = instance or resolve_relay_instance(
        config_path=config_path,
        environment=environment,
        yoke_home=yoke_home,
    )
    if refusal := door_relay_refusal(selected):
        raise RelayInstallError(refusal, code=USE_HTTPS_ENV)
    paths = relay_launchd_paths(home=home, instance=selected)
    source_env = os.environ if environ is None else environ
    try:
        relay_install.converge_relay_launcher(selected, pin_release=pin_release)
    except relay_release.RelayReleaseError as exc:
        raise RelayInstallError(str(exc), code=exc.code) from exc
    from yoke_core.tools.session_relay_shared_retirement import retire_shared_launchd

    retire_shared_launchd(selected, home=home, runner=runner, uid=uid)
    create_private_directory(paths.state_dir)
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
    from yoke_core.tools.session_relay_shared_retirement import retire_shared_launchd

    retire_shared_launchd(selected, home=home, runner=runner, uid=uid)
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
