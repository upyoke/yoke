"""Convergent systemd user service for the environment-pinned machine relay."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Callable, Mapping

from yoke_cli.config import machine_config
from yoke_cli.config.session_relay_instance import RelayInstance, resolve_relay_instance
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_core.tools.session_relay_executable import relay_executable_search_path
from yoke_core.tools.session_relay_plist import RelayInstallError
from yoke_core.tools import session_relay_release_install as relay_install
from yoke_core.tools.session_relay_release import RelayReleaseError

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class RelaySystemdStatus:
    supported: bool
    unit_present: bool
    unit_current: bool
    loaded: bool
    enabled: bool
    unit_path: Path
    environment: str
    label: str
    state_dir: Path
    follows_served_release: bool
    reason: str = ""


def _run(argv: list[str], runner: Runner) -> subprocess.CompletedProcess[str]:
    try:
        return runner(argv, check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RelayInstallError(
            f"relay_systemd_unavailable: {exc}. Log in to a systemd Linux host "
            "and retry `yoke relay install`.",
            code="relay_systemd_unavailable",
        ) from exc


def systemd_unavailable_reason(
    *, runner: Runner = subprocess.run, pid1_path: Path = Path("/proc/1/comm")
) -> str:
    try:
        pid1 = pid1_path.read_text().strip()
    except OSError:
        pid1 = "unreadable"
    if pid1 != "systemd":
        return (
            f"relay_systemd_not_pid1: relay is not supervised because PID 1 is {pid1!r}. "
            "Use a systemd Linux host; enable systemd in WSL before retrying."
        )
    try:
        result = _run(["systemctl", "--user", "show-environment"], runner)
    except RelayInstallError as exc:
        return str(exc)
    if result.returncode:
        return (
            "relay_systemd_user_manager_unavailable: relay is not supervised; "
            f"{result.stderr.strip()}. Log in through a PAM session with "
            "a systemd user manager, then retry `yoke relay install`."
        )
    return ""


def _linger_reason(runner: Runner) -> str:
    result = _run(
        ["loginctl", "show-user", str(os.getuid()), "--property=Linger", "--value"],
        runner,
    )
    if result.returncode or result.stdout.strip() not in {"yes", "no"}:
        return (
            "relay_linger_unknown: cannot verify logout behavior. "
            "Check `loginctl show-user --property=Linger`, then retry `yoke relay install`."
        )
    if result.stdout.strip() == "yes":
        return (
            "relay_linger_enabled: linger would keep the relay running after logout. "
            "Disable linger for this user with `loginctl disable-linger`, "
            "then retry `yoke relay install`."
        )
    return ""


def relay_unit_path(instance: RelayInstance, *, home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config/systemd/user" / f"{instance.label}.service"


def _quote(value: object, *, command: bool = False) -> str:
    text = str(value)
    if any(char in text for char in "\n\r\0"):
        raise RelayInstallError(
            "relay_unit_value_invalid: paths must not contain line breaks or NUL"
        )
    text = text.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    if command:
        text = text.replace("$", "$$")
    return f'"{text}"'


def relay_unit_document(
    instance: RelayInstance, *, environ: Mapping[str, str] | None = None
) -> str:
    source_env = os.environ if environ is None else environ
    launcher = relay_install.relay_launcher_path(
        instance.state_dir, follows_served_release=instance.follows_served_release
    )
    argv = [launcher, "--env", instance.environment, "relay", "serve"]
    variables = {
        "PATH": relay_executable_search_path(executable=launcher, environ=source_env),
        machine_config.CONFIG_FILE_ENV: str(instance.config_path),
        machine_config.HOME_ENV: str(instance.yoke_home),
    }
    return "\n".join(
        [
            "[Unit]",
            "Description=Yoke machine relay",
            "StartLimitIntervalSec=0",
            "",
            "[Service]",
            "Type=exec",
            "ExecStart=" + " ".join(_quote(arg, command=True) for arg in argv),
            *(
                "Environment=" + _quote(f"{key}={value}")
                for key, value in variables.items()
            ),
            "Restart=on-failure",
            "RestartSec=5",
            "UMask=0077",
            "StandardOutput=append:" + str(instance.stdout_log).replace("%", "%%"),
            "StandardError=append:" + str(instance.stderr_log).replace("%", "%%"),
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def relay_systemd_status(
    *,
    instance: RelayInstance | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner = subprocess.run,
    pid1_path: Path = Path("/proc/1/comm"),
) -> RelaySystemdStatus:
    selected = instance or resolve_relay_instance()
    path = relay_unit_path(selected, home=home)
    reason = systemd_unavailable_reason(runner=runner, pid1_path=pid1_path)
    supported = not reason
    loaded = enabled = False
    if supported:
        try:
            active = _run(["systemctl", "--user", "is-active", path.name], runner)
            enabled_result = _run(
                ["systemctl", "--user", "is-enabled", path.name], runner
            )
            loaded = active.returncode == 0 and active.stdout.strip() == "active"
            enabled = (
                enabled_result.returncode == 0
                and enabled_result.stdout.strip() == "enabled"
            )
            reason = _linger_reason(runner)
        except RelayInstallError as exc:
            reason = str(exc)
    try:
        current = path.read_text() == relay_unit_document(selected, environ=environ)
    except OSError:
        current = False
    return RelaySystemdStatus(
        supported,
        path.is_file(),
        current,
        loaded,
        enabled,
        path,
        selected.environment,
        selected.label,
        selected.state_dir,
        selected.follows_served_release,
        reason,
    )


def _checked(argv: list[str], runner: Runner) -> None:
    result = _run(argv, runner)
    if result.returncode:
        raise RelayInstallError(
            f"relay_systemd_command_failed: {' '.join(argv)}: "
            f"{result.stderr.strip() or result.stdout.strip()}. "
            "Inspect `systemctl --user status` and retry `yoke relay install`.",
            code="relay_systemd_command_failed",
        )


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
    reason = systemd_unavailable_reason(
        runner=runner, pid1_path=pid1_path
    ) or _linger_reason(runner)
    if reason:
        raise RelayInstallError(reason, code=reason.split(":", 1)[0])
    try:
        relay_install.converge_relay_launcher(selected, pin_release=pin_release)
    except RelayReleaseError as exc:
        raise RelayInstallError(str(exc), code=exc.code) from exc
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
    path = relay_unit_path(selected, home=home)
    if path.exists():
        _checked(["systemctl", "--user", "disable", "--now", path.name], runner)
        path.unlink()
        _checked(["systemctl", "--user", "daemon-reload"], runner)
    return relay_systemd_status(
        instance=selected, home=home, runner=runner, pid1_path=pid1_path
    )
