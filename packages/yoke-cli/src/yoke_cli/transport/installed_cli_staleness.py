"""Warn when the installed CLI is older than its active connection's release.

Every HTTPS response already carries the server's engine version, so the
comparison costs no request of its own. It warns once per process, on stderr,
and never updates or refuses: the relay for the machine's ``active_env``
installs each release it observes that plane serving, and this warning is what
a machine left behind sees. A command sent to another env with ``--env`` or
``YOKE_ENV`` compares against nothing, because the installed CLI does not
follow that plane.
"""

from __future__ import annotations

import sys
from typing import TextIO

from yoke_cli.config import machine_config
from yoke_contracts.engine_version import (
    compare_engine_versions,
    local_handshake_version,
)
from yoke_contracts.machine_config.schema import configured_active_env

_warned = False


def update_recovery(version: str) -> str:
    """The command that installs *version* by hand."""
    return f"run `yoke update --version {version}`"


def warn_if_behind_active_connection(
    *,
    env: str,
    server_version: str,
    local_version: str | None = None,
    active_env: str | None = None,
    stream: TextIO | None = None,
) -> bool:
    """Print one warning when this CLI predates *env*'s release; True if printed.

    Only *env* equal to the machine's ``active_env`` is compared; the config is
    read only once this CLI is known to be behind.
    """
    global _warned
    if _warned or not env or not server_version:
        return False
    local = local_version if local_version is not None else local_handshake_version()
    if not local or compare_engine_versions(local, server_version) != -1:
        return False
    if active_env is None:
        active_env = configured_active_env(machine_config.load_config())
    if env != active_env:
        return False
    _warned = True
    served = server_version.strip()
    print(
        f"yoke: warning: this CLI ({local}) is older than {served}, the release "
        f"your active connection {env!r} serves. Its relay installs each "
        "release it observes; it has not moved this one yet. To update now, "
        f"{update_recovery(served)}.",
        file=stream or sys.stderr,
    )
    return True


__all__ = ["update_recovery", "warn_if_behind_active_connection"]
