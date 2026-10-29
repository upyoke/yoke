"""Retire the former shared relay service when its exact owner installs anew."""

from dataclasses import replace
from pathlib import Path
import plistlib
import shlex

from yoke_cli.config import machine_config
from yoke_cli.config.session_relay_instance import (
    RELAY_BASE_LABEL,
    SHARED_RELAY_STATE_DIR_NAME,
)
from yoke_harness.session_launch_containment import SUPERVISION_DIRECTORY_NAME
from yoke_harness.session_relay_termination import read_local_record
from yoke_harness.session_process_custody import custody_state


def _refuse(detail):
    from yoke_core.tools.session_relay_plist import RelayInstallError

    return RelayInstallError(
        "relay_shared_service_retirement_blocked: "
        + detail
        + "; preserve the shared service and its state, resolve its ownership or "
        "close its worker sessions, then retry `yoke relay install`.",
        code="relay_shared_service_retirement_blocked",
    )


def _read(path):
    if path.stat().st_size > 65536:
        raise _refuse("the shared service document exceeds its read bound")
    return path.read_bytes()


def _owned(instance, variables, argv):
    config = variables.get(machine_config.CONFIG_FILE_ENV)
    home = variables.get(machine_config.HOME_ENV)
    if not isinstance(config, str) or not isinstance(home, str) or len(argv) != 5:
        raise _refuse("the shared service document has incomplete ownership")
    if argv[1] != "--env" or argv[3:] != ["relay", "serve"]:
        raise _refuse("the shared service command is not a relay invocation")
    if (
        Path(config).resolve() != instance.config_path
        or Path(home).resolve() != instance.yoke_home
        or argv[2] != instance.environment
    ):
        return False
    from yoke_core.tools.session_relay_release_install import relay_launcher_path

    state = instance.yoke_home / SHARED_RELAY_STATE_DIR_NAME
    expected = relay_launcher_path(
        state, follows_served_release=instance.follows_served_release
    )
    if Path(argv[0]) != expected:
        raise _refuse("the shared service launcher is outside its owned state")
    for record_path in (state / SUPERVISION_DIRECTORY_NAME).glob("*.json"):
        record = read_local_record(record_path)
        if record is None or custody_state(record) != "gone":
            raise _refuse(f"worker custody is live or unknown in {record_path.name}")
    return True


def _shared(instance):
    return replace(
        instance,
        label=RELAY_BASE_LABEL,
        state_dir=instance.yoke_home / SHARED_RELAY_STATE_DIR_NAME,
    )


def retire_shared_launchd(instance, *, home, runner, uid):
    if instance.label == RELAY_BASE_LABEL:
        return
    from yoke_core.tools.session_relay_plist import (
        relay_launchd_paths,
        uninstall_relay_launchd,
    )

    shared = _shared(instance)
    path = relay_launchd_paths(home=home, instance=shared).plist
    if not path.exists():
        return
    try:
        document = plistlib.loads(_read(path))
        if document.get("Label") != RELAY_BASE_LABEL:
            raise _refuse("the shared launchd label differs from its owned path")
        owned = _owned(
            instance,
            document.get("EnvironmentVariables", {}),
            document.get("ProgramArguments", []),
        )
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise _refuse("the shared launchd document cannot be read") from exc
    if owned:
        uninstall_relay_launchd(
            home=home, runner=runner, platform="darwin", uid=uid, instance=shared
        )


def retire_shared_systemd(instance, *, home, runner, pid1_path):
    if instance.label == RELAY_BASE_LABEL:
        return
    from yoke_core.tools.session_relay_systemd import (
        relay_unit_path,
        uninstall_relay_systemd,
    )

    shared = _shared(instance)
    path = relay_unit_path(shared, home=home)
    if not path.exists():
        return
    try:
        text = _read(path).decode()
        variables = {}
        argv = []
        for line in text.splitlines():
            if line.startswith("Environment="):
                (value,) = shlex.split(line.removeprefix("Environment="))
                key, value = value.replace("%%", "%").split("=", 1)
                variables[key] = value
            elif line.startswith("ExecStart="):
                argv = [
                    value.replace("%%", "%").replace("$$", "$")
                    for value in shlex.split(line.removeprefix("ExecStart="))
                ]
        owned = _owned(instance, variables, argv)
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise _refuse("the shared systemd document cannot be read") from exc
    if owned:
        uninstall_relay_systemd(
            instance=shared, home=home, runner=runner, pid1_path=pid1_path
        )
