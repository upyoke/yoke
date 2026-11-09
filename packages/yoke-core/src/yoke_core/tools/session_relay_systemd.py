"""Convergent systemd user service for the environment-pinned machine relay."""

from __future__ import annotations

from yoke_core.domain.relay_systemd_status import (
    RelaySystemdStatus,
    Runner,
    _checked,
    _linger_reason,
    relay_systemd_status,
    relay_unit_document,
    relay_unit_path,
    systemd_unavailable_reason,
)

from pathlib import Path
import subprocess
from typing import Callable, Mapping

from yoke_contracts.machine_config.relay_instance import (
    RelayInstance,
    door_relay_refusal,
    resolve_relay_instance,
)
from yoke_contracts.direct_database_access import USE_HTTPS_ENV
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_core.domain.relay_launchd_status import RelayInstallError
from yoke_core.tools import session_relay_release_install as relay_install
from yoke_core.tools.session_relay_release import RelayReleaseError


def install_relay_systemd(
    *,
    instance: RelayInstance | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner = subprocess.run,
    pid1_path: Path = Path("/proc/1/comm"),
    pin_release: Callable[..., object] = relay_install.pin_relay_release,
) -> RelaySystemdStatus:
    selected = instance or resolve_relay_instance()
    if refusal := door_relay_refusal(selected):
        raise RelayInstallError(refusal, code=USE_HTTPS_ENV)
    reason = systemd_unavailable_reason(
        runner=runner, pid1_path=pid1_path
    ) or _linger_reason(runner)
    if reason:
        raise RelayInstallError(reason, code=reason.split(":", 1)[0])
    try:
        relay_install.converge_relay_launcher(selected, pin_release=pin_release)
    except RelayReleaseError as exc:
        raise RelayInstallError(str(exc), code=exc.code) from exc
    from yoke_core.tools.session_relay_shared_retirement import retire_shared_systemd

    retire_shared_systemd(selected, home=home, runner=runner, pid1_path=pid1_path)
    create_private_directory(selected.state_dir)
    path = relay_unit_path(selected, home=home)
    create_private_directory(path.parent)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(relay_unit_document(selected, environ=environ))
    temporary.chmod(0o600)
    temporary.replace(path)
    _checked(["systemctl", "--user", "daemon-reload"], runner)
    _checked(["systemctl", "--user", "enable", path.name], runner)
    _checked(["systemctl", "--user", "restart", path.name], runner)
    status = relay_systemd_status(
        instance=selected,
        home=home,
        environ=environ,
        runner=runner,
        pid1_path=pid1_path,
    )
    if not (
        status.loaded and status.enabled and status.unit_current and not status.reason
    ):
        raise RelayInstallError(
            "relay_systemd_not_active: the installed user unit is not active and enabled. "
            "Inspect `systemctl --user status` and retry `yoke relay install`.",
            code="relay_systemd_not_active",
        )
    return status


def uninstall_relay_systemd(
    *,
    instance: RelayInstance | None = None,
    home: Path | None = None,
    runner: Runner = subprocess.run,
    pid1_path: Path = Path("/proc/1/comm"),
) -> RelaySystemdStatus:
    selected = instance or resolve_relay_instance()
    reason = systemd_unavailable_reason(runner=runner, pid1_path=pid1_path)
    if reason:
        raise RelayInstallError(reason, code=reason.split(":", 1)[0])
    from yoke_core.tools.session_relay_shared_retirement import retire_shared_systemd

    retire_shared_systemd(selected, home=home, runner=runner, pid1_path=pid1_path)
    path = relay_unit_path(selected, home=home)
    if path.exists():
        _checked(["systemctl", "--user", "disable", "--now", path.name], runner)
        path.unlink()
        _checked(["systemctl", "--user", "daemon-reload"], runner)
    status = relay_systemd_status(
        instance=selected, home=home, runner=runner, pid1_path=pid1_path
    )
    if status.loaded or status.enabled or status.unit_present:
        raise RelayInstallError(
            "relay_systemd_not_stopped: the relay user unit remains active or enabled. "
            "Repair it with `yoke relay install`, then retry `yoke relay uninstall`.",
            code="relay_systemd_not_stopped",
        )
    return status
