"""Idempotently prepare dedicated claim-free broker acceptance sessions."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from runtime.api.tools.session_control_live_acceptance import (
    DEFAULT_POLL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)
from runtime.api.tools.session_control_live_acceptance_broker_binding import (
    resolve_broker_binding,
)
from runtime.api.tools.session_control_live_acceptance_broker_eligibility import (
    BrokerBinding,
    BrokerBindingDecision,
)
from runtime.api.tools.session_control_live_acceptance_client import CommandClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_launch import (
    wait_for_registered_launch,
)
from runtime.api.tools.session_control_live_acceptance_protocol import (
    initial_delivery_message,
)


BROKER_ROLES = ("target", "peer")


def _create_launch(
    client: CommandClient,
    *,
    project: str,
    surface: str,
    machine_id: str,
    run_id: str,
    role: str,
) -> dict[str, Any]:
    result = client.call(
        [
            "sessions",
            "create",
            "--project",
            project,
            "--surface",
            surface,
            "--machine",
            machine_id,
            "--stdin",
            "--idempotency-key",
            f"fleet-live:{run_id}:{surface}:broker-{role}",
        ],
        stdin=initial_delivery_message(
            surface=surface, phase=f"dedicated broker {role} preparation"
        ),
    )
    launch = result.get("launch")
    if not isinstance(launch, dict):
        raise AcceptanceContractError(
            "broker_preparation_launch_missing", surface=surface
        )
    return launch


def resolve_or_prepare_broker_binding(
    client: CommandClient,
    *,
    project: str,
    surface: str,
    binding: BrokerBinding,
    expected_version: str,
    run_id: str,
    prepare: bool,
    timeout: float | None = None,
    poll: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> BrokerBindingDecision:
    """Resolve an eligible pair, preparing two itemless sessions on request."""
    decision = resolve_broker_binding(
        client,
        project=project,
        surface=surface,
        binding=binding,
        expected_version=expected_version,
    )
    if decision.status == "ready" or not prepare:
        return decision
    launches = [
        _create_launch(
            client,
            project=project,
            surface=surface,
            machine_id=binding.machine_id,
            run_id=run_id,
            role=role,
        )
        for role in BROKER_ROLES
    ]
    registrations = [
        wait_for_registered_launch(
            client,
            launch=launch,
            surface=surface,
            timeout=timeout or DEFAULT_TIMEOUT_SECONDS,
            poll=poll or DEFAULT_POLL_SECONDS,
            sleep=sleep,
            monotonic=monotonic,
        )[0]
        for launch in launches
    ]
    prepared = BrokerBinding(registrations[0], binding.machine_id, registrations[1])
    return resolve_broker_binding(
        client,
        project=project,
        surface=surface,
        binding=prepared,
        expected_version=expected_version,
    )


__all__ = ["BROKER_ROLES", "resolve_or_prepare_broker_binding"]
