"""Remove saved relay services before deleting their machine home.

Connection retirement may already have removed every alias. The installed
service document still records its owner and instance identity as the cleanup
authority, not a connection that may no longer exist.
"""

from __future__ import annotations

from pathlib import Path
import plistlib

from yoke_contracts.machine_config.paths import CONFIG_FILE_ENV, HOME_ENV
from yoke_contracts.machine_config.relay_instance import (
    RELAY_BASE_LABEL,
    RELAY_LABEL_PREFIX,
    RELAY_STATE_ROOT_NAME,
    SHARED_RELAY_STATE_DIR_NAME,
    RelayInstance,
    relay_instance_label,
)
from yoke_core.domain.launchctl_boundary import launch_agents_dir
from yoke_core.domain.relay_launchd_status import RelayInstallError
from yoke_core.domain.local_relay_launcher_path import local_launcher_candidates
from yoke_core.domain.relay_release_path import relay_launch_executable
from yoke_core.domain.relay_systemd_status import relay_unit_directory
from yoke_core.tools.session_relay_plist import uninstall_relay_launchd
from yoke_core.tools.session_relay_shared_retirement import parse_relay_unit
from yoke_core.tools.session_relay_systemd import uninstall_relay_systemd


def _refusal(path: Path) -> RelayInstallError:
    return RelayInstallError(
        f"uninstall_relay_ownership_unproven: cannot prove the saved relay at {path}. "
        "Restore its installer-written service document and retry `yoke uninstall`; "
        "the machine home and CLI are retained for recovery.",
        code="uninstall_relay_ownership_unproven",
    )


def _instance(path: Path, machine_home: Path, platform: str) -> RelayInstance | None:
    if path.is_symlink():
        raise _refusal(path)
    try:
        if path.stat().st_size > 65536:
            raise ValueError("oversized service document")
        content = path.read_bytes()
        if platform == "linux":
            environment, args = parse_relay_unit(content)
            label = path.stem
        else:
            document = plistlib.loads(content)
            environment = document["EnvironmentVariables"]
            args = document["ProgramArguments"]
            label = document["Label"]
        owner = Path(environment[HOME_ENV]).expanduser().resolve()
        if owner != machine_home:
            return None
        config = Path(environment[CONFIG_FILE_ENV]).expanduser().resolve()
        # This is exactly the installer-written command, not a label-prefix
        # guess about another user's executable or service.
        if len(args) != 5 or args[1] != "--env" or args[3:] != ["relay", "serve"]:
            raise ValueError("unrecognized relay command")
        name = args[2]
        if not isinstance(name, str) or not name:
            raise ValueError("missing environment")
        expected = relay_instance_label(config_path=config, environment=name)
        if label not in (expected, RELAY_BASE_LABEL) or path.stem != label:
            raise ValueError("instance identity mismatch")
        state = (
            machine_home / SHARED_RELAY_STATE_DIR_NAME
            if label == RELAY_BASE_LABEL
            else machine_home
            / RELAY_STATE_ROOT_NAME
            / label.removeprefix(RELAY_LABEL_PREFIX)
        )
        follows_served = Path(args[0]) == relay_launch_executable(state)
        if not follows_served and Path(args[0]) not in local_launcher_candidates():
            raise ValueError("launcher is not installer-owned")
    except (OSError, ValueError, TypeError, KeyError, plistlib.InvalidFileException):
        raise _refusal(path) from None
    return RelayInstance(
        environment=name,
        config_path=config,
        yoke_home=machine_home,
        protected=False,
        label=label,
        state_dir=state,
        follows_served_release=follows_served,
    )


def uninstall_owned_relays(machine_home: Path, *, platform: str) -> list[str]:
    """Unload proven services even when their config or alias has gone.

    Lifecycle removal verifies each native service is gone. Any unreadable
    identity or failed unload fails the uninstall,
    preserving the machine home and executable for a retry.
    """
    owner = machine_home.expanduser().resolve()
    if platform == "linux":
        directory, extension = relay_unit_directory(), "service"
    else:
        directory, extension = launch_agents_dir(yoke_home=owner), "plist"
    removed = []
    paths = list(directory.glob(f"{RELAY_LABEL_PREFIX}*.{extension}"))
    shared = directory / f"{RELAY_BASE_LABEL}.{extension}"
    if shared.exists() or shared.is_symlink():
        paths.append(shared)
    for path in sorted(paths):
        if not path.exists() and not path.is_symlink():
            # A prior instance may have retired its shared job.
            continue
        instance = _instance(path, owner, platform)
        if instance is None:
            continue
        if platform == "linux":
            status = uninstall_relay_systemd(instance=instance)
            remains = status.loaded or status.enabled or status.unit_present
        else:
            status = uninstall_relay_launchd(instance=instance)
            remains = status.loaded or status.plist_present
        if remains:
            raise RelayInstallError(
                f"uninstall_relay_not_stopped: {instance.label} remains installed. "
                "Retry `yoke uninstall` after the service stops; recovery files remain.",
                code="uninstall_relay_not_stopped",
            )
        removed.append(instance.label)
    return removed
