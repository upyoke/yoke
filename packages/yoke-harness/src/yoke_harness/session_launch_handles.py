"""Where a launched native's process handle lives on this machine.

A launch handle is custody of a process, not relay state. The hook inside the
launched session writes it the moment the native registers, so termination can
still reach a process containment has released; the relay reads it to prove the
native is gone, to signal it, and to prune it once the control plane has
settled the session.

Writer and readers run in different processes that know different things. The
hook knows nothing about which relay instance started the session, and a
relay's own state directory is keyed by the control-plane connection it serves,
so the two ends can only meet on something both already resolve: the machine
cache. Composing the directory from a caller-supplied state directory is what
let them drift apart — a launched native exited with its handle written under
the machine cache while the relay looked under its own state directory, found
nothing, and reported neither the exit nor the usage. The directory therefore
has exactly one resolver here, and no caller recomposes it.
"""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import machine_config


NATIVE_HANDLE_DIRECTORY_NAME = "session-native-handles"


def native_handle_directory() -> Path:
    """The one machine-wide directory every launch handle is written to and read from."""
    directory = machine_config.cache_dir() / NATIVE_HANDLE_DIRECTORY_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory


def native_handle_path(launch_id: str) -> Path:
    """The handle file naming one launch's native process."""
    return native_handle_directory() / f"{launch_id}.json"


__all__ = [
    "NATIVE_HANDLE_DIRECTORY_NAME",
    "native_handle_directory",
    "native_handle_path",
]
