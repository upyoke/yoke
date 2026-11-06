"""Runtime interface for remote file copy."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class RemoteFileCopy(Protocol):
    """Operations and values supplied by the executing adapter."""

    BASH_READER: Any
    HostCopyRefused: type[Any]
    ZSH_READER: Any
    stream_remote_file: Callable[..., Any]


def get_remote_file_copy() -> RemoteFileCopy:
    return cast(RemoteFileCopy, load_port("remote_file_copy", RemoteFileCopy))
