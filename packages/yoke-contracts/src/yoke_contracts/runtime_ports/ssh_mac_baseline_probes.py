"""Runtime interface for ssh mac baseline probes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshMacBaselineProbes(Protocol):
    """Operations and values supplied by the executing adapter."""

    reach_user_equivalent_baseline: Callable[..., Any]


def get_ssh_mac_baseline_probes() -> SshMacBaselineProbes:
    return cast(SshMacBaselineProbes, load_port("ssh_mac_baseline_probes", SshMacBaselineProbes))
