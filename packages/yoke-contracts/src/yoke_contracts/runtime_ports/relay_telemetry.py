"""Runtime interface for relay telemetry."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class RelayTelemetry(Protocol):
    """Operations and values supplied by the executing adapter."""

    TRANSPORT_FAILED_CODE: Any


def get_relay_telemetry() -> RelayTelemetry:
    return cast(RelayTelemetry, load_port("relay_telemetry", RelayTelemetry))
