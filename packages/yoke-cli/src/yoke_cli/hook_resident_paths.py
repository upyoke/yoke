"""Filesystem and transport capability for the hook evaluator resident."""

from __future__ import annotations

import hashlib
import os
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path

from yoke_cli.config import machine_config
from yoke_contracts.machine_config.directories import create_private_directory


_SOCKET_PATH_LIMIT_BYTES = 100


@dataclass(frozen=True)
class ResidentPaths:
    state_dir: Path
    socket: Path
    lock: Path
    log: Path


def resident_paths() -> ResidentPaths:
    state_dir = machine_config.cache_dir() / "hook-evaluator"
    create_private_directory(state_dir)
    try:
        state_dir.chmod(0o700)
    except OSError:
        pass
    candidate = state_dir / "evaluator.sock"
    if len(os.fsencode(candidate)) > _SOCKET_PATH_LIMIT_BYTES:
        digest = hashlib.sha256(os.fsencode(state_dir)).hexdigest()[:16]
        candidate = Path(tempfile.gettempdir()) / (
            f"yoke-hook-{getattr(os, 'getuid', lambda: 0)()}-{digest}.sock"
        )
    return ResidentPaths(
        state_dir=state_dir,
        socket=candidate,
        lock=state_dir / "evaluator.lock",
        log=state_dir / "evaluator.log",
    )


def resident_transport_available() -> bool:
    """Return whether this Python runtime can host the resident transport."""
    return hasattr(socket, "AF_UNIX")


__all__ = ["ResidentPaths", "resident_paths", "resident_transport_available"]
