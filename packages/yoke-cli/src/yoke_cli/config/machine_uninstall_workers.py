"""Stop Yoke-owned worker processes through the shared harness reaper."""

from __future__ import annotations

from yoke_cli.config import machine_config, session_relay_instance
from yoke_cli.config.machine_uninstall_inventory import UninstallError


def stop(relay_envs: tuple[str, ...]) -> None:
    from yoke_harness import session_launch_handles, session_relay_termination
    from yoke_harness.session_launch_containment import SUPERVISION_DIRECTORY_NAME

    directories = [
        session_launch_handles.native_handle_directory(),
        machine_config.cache_dir() / SUPERVISION_DIRECTORY_NAME,
    ]
    for env in relay_envs:
        instance = session_relay_instance.resolve_relay_instance(environment=env)
        directories.append(instance.state_dir / SUPERVISION_DIRECTORY_NAME)
    failures = []
    for directory in dict.fromkeys(directories):
        for path in directory.glob("*.json"):
            record = session_relay_termination.read_local_record(path)
            if record is None:
                failures.append(f"{path.name}: unreadable worker handle")
                continue
            result = session_relay_termination._terminate_record(path, record)
            if result is None or result[1] not in {
                "terminated",
                "killed",
                "already_exited",
            }:
                failures.append(
                    f"{path.name}: {result[1] if result else 'invalid worker identity'}"
                )
    if failures:
        raise UninstallError(
            "uninstall_workers_not_stopped: "
            + ", ".join(failures)
            + "; close those worker sessions from their harness, then retry uninstall."
        )
