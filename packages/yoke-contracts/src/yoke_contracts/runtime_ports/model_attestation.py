"""Runtime interface for model attestation."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ModelAttestation(Protocol):
    """Hook operations supplied by the executing adapter."""

    attest_served_facts: Any


def get_model_attestation() -> ModelAttestation:
    return cast(ModelAttestation, load_port("model_attestation", ModelAttestation))
