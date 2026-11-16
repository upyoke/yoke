"""Keep the OS process-group handle with a relay-owned child."""

from yoke_contracts.platform_process import spawn_group, stop_group


def spawn_relay_process(argv, **kwargs):
    handle = spawn_group(argv, **kwargs)
    process = handle.process
    if process is None:
        raise RuntimeError("relay_spawn_failed: no child process; retry the relay operation")
    process._yoke_group_handle = handle
    return process


def stop_relay_process(process, timeout=2):
    return stop_group(process._yoke_group_handle, timeout)
