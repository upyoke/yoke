"""Runtime interface for usage attestation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class UsageAttestation(Protocol):
    """Operations and values supplied by the executing adapter."""

    attest_session_usage: Callable[..., Any]


def get_usage_attestation() -> UsageAttestation:
    return cast(UsageAttestation, load_port("usage_attestation", UsageAttestation))
