"""Idempotently prepare dedicated claim-free broker acceptance sessions.

A prepared broker holds no work claim — that is the point of it, and the
declared eligibility axes require it. It is also, unguarded, exactly what idle
cleanup ends: the session registers, acknowledges its receipt-only handshake,
finishes its turn, and the harness's own stop hook reaps it seconds later. So
preparation takes a keep-alive hold on each session as soon as it registers,
before the session's first turn can end, and then re-reads the roster and
refuses with its own named code if the pair is gone anyway. Preparation that
reports success on sessions that no longer exist is the failure this module
exists to make impossible.
"""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any
from uuid import uuid4

from runtime.api.tools.session_control_live_acceptance import (
    DEFAULT_POLL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)
from runtime.api.tools.session_control_live_acceptance_broker_binding import (
    resolve_broker_binding,
)
from runtime.api.tools.session_control_live_acceptance_broker_candidates import (
    sessions_absent,
)
from runtime.api.tools.session_control_live_acceptance_broker_eligibility import (
    PREPARED_SESSIONS_ENDED_CODE,
    BrokerBinding,
    BrokerBindingDecision,
    prepared_sessions_ended_recovery,
)
from runtime.api.tools.session_control_live_acceptance_client import CommandClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_launch import (
    wait_for_registered_launch,
)
from runtime.api.tools.session_control_live_acceptance_protocol import (
    broker_preparation_message,
)
from yoke_cli.commands.adapters.session_control_acceptance import PREPARE_BROKER_FLAG
from yoke_contracts.session_control.keepalive import DEFAULT_KEEPALIVE_SECONDS


BROKER_ROLES = ("target", "peer")


def broker_preparation_idempotency_key(
    run_id: str, surface: str, role: str, attempt_id: str
) -> str:
    """Key one preparation attempt, not the unconsumed run it may retry."""
    return f"fleet-live:{run_id}:{surface}:broker-{role}:{attempt_id}"


def _idempotency_conflict(
    *,
    surface: str,
    run_id: str,
    role: str,
    attempt_id: str,
) -> AcceptanceContractError:
    key = broker_preparation_idempotency_key(run_id, surface, role, attempt_id)
    return AcceptanceContractError(
        "idempotency_conflict",
        surface=surface,
        evidence={
            "owning_attempt_id": attempt_id,
            "run_id": run_id,
            "run_consumed": False,
            "recovery": (
                f"Idempotency key {key} already names a launch for preparation "
                f"attempt {attempt_id}. Run {run_id} is unconsumed — this gate "
                "runs before the matrix executes, so the run id was preserved. "
                "This refusal protects a duplicate create inside one attempt. "
                f"Rerun preview with {PREPARE_BROKER_FLAG} to start a new "
                "attempt; do not retry the same create."
            ),
        },
    )


#: How long a prepared broker is held against idle reaping. The default lease
#: window already covers an acceptance run with room to spare, and a hold that
#: outlives its run costs only the rest of that window.
BROKER_KEEPALIVE_SECONDS = DEFAULT_KEEPALIVE_SECONDS


def _create_launch(
    client: CommandClient,
    *,
    project: str,
    surface: str,
    machine_id: str,
    run_id: str,
    role: str,
    attempt_id: str,
) -> dict[str, Any]:
    try:
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
                broker_preparation_idempotency_key(run_id, surface, role, attempt_id),
            ],
            stdin=broker_preparation_message(surface=surface, role=role),
        )
    except AcceptanceContractError as exc:
        if exc.code == "idempotency_conflict":
            raise _idempotency_conflict(
                surface=surface,
                run_id=run_id,
                role=role,
                attempt_id=attempt_id,
            ) from exc
        raise
    launch = result.get("launch")
    if not isinstance(launch, dict):
        raise AcceptanceContractError(
            "broker_preparation_launch_missing", surface=surface
        )
    return launch


def _hold_alive(
    client: CommandClient, *, session_id: str, surface: str, run_id: str
) -> None:
    """Hold one just-registered broker against idle reaping, or refuse loudly.

    The hold is taken the moment registration is proven and before waiting on
    the sibling launch, because the window that killed the unheld pair opens at
    the end of the session's very first turn.
    """
    result = client.call(
        [
            "sessions",
            "keepalive",
            "hold",
            session_id,
            "--reason",
            f"fleet live acceptance broker for run {run_id}",
            "--seconds",
            str(BROKER_KEEPALIVE_SECONDS),
        ]
    )
    if result.get("held") is not True:
        raise AcceptanceContractError(
            "broker_keepalive_hold_refused",
            surface=surface,
            evidence={"session_id": session_id, "result": result},
        )


def _prepared_pair(
    client: CommandClient,
    *,
    project: str,
    surface: str,
    machine_id: str,
    run_id: str,
    timeout: float,
    poll: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> list[str]:
    """Launch, register, and hold alive one dedicated session per broker role."""
    attempt_id = uuid4().hex
    registered: list[str] = []
    for role in BROKER_ROLES:
        launch = _create_launch(
            client,
            project=project,
            surface=surface,
            machine_id=machine_id,
            run_id=run_id,
            role=role,
            attempt_id=attempt_id,
        )
        session_id = wait_for_registered_launch(
            client,
            launch=launch,
            surface=surface,
            timeout=timeout,
            poll=poll,
            sleep=sleep,
            monotonic=monotonic,
        )[0]
        _hold_alive(client, session_id=session_id, surface=surface, run_id=run_id)
        registered.append(session_id)
    return registered


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
    registrations = _prepared_pair(
        client,
        project=project,
        surface=surface,
        machine_id=binding.machine_id,
        run_id=run_id,
        timeout=timeout or DEFAULT_TIMEOUT_SECONDS,
        poll=poll or DEFAULT_POLL_SECONDS,
        sleep=sleep,
        monotonic=monotonic,
    )
    prepared = BrokerBinding(registrations[0], binding.machine_id, registrations[1])
    verified = resolve_broker_binding(
        client,
        project=project,
        surface=surface,
        binding=prepared,
        expected_version=expected_version,
    )
    if verified.status == "ready":
        return verified
    absent = sessions_absent(verified.considered, registrations)
    if not absent:
        return verified
    return BrokerBindingDecision(
        "not_ready",
        prepared,
        failure_code=PREPARED_SESSIONS_ENDED_CODE,
        recovery=prepared_sessions_ended_recovery(absent),
        advertised_version=verified.advertised_version,
        considered=verified.considered,
    )


__all__ = [
    "BROKER_KEEPALIVE_SECONDS",
    "BROKER_ROLES",
    "broker_preparation_idempotency_key",
    "resolve_or_prepare_broker_binding",
]
