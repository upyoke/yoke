"""Pay a rolled environment's cold start inside the deploy, not after it.

A rolled box answers its health probe long before it can answer real work.
The first heavy relayed function call after a roll pays the entire server
cold start — engine imports, connection pool, caches — and can exceed the
client's relay ceiling, so it fails at the caller while the server is
healthy and warm steady-state latency for the same call is a second or two.
Every roll hands that one failure to whoever calls first.

This module issues that first call from the pipeline itself, with a timeout
generous enough to absorb a cold start, so a run reports success only once
the environment answers real work. The call is a plain read of the deployed
control plane over the same HTTPS relay a client uses, so what it proves is
what a client experiences.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

#: Read that exercises the whole server path — dispatch, engine imports,
#: connection pool, and a real multi-table query plan — while needing no
#: arguments and mutating nothing, so it warms any tenant identically.
DEFAULT_WARM_UP_FUNCTION = "board.data.get"

#: Generously past the client relay ceiling: a cold start that takes longer
#: than this is a broken box, not a slow one.
DEFAULT_WARM_UP_TIMEOUT_S = 180.0

_monotonic = time.monotonic


@dataclass(frozen=True)
class WarmUpOutcome:
    """Result of one warm-up call, including the cold start it paid."""

    ok: bool
    connection_env: str
    function_id: str
    latency_ms: int
    detail: str


def warm_up_environment(
    connection_env: str,
    *,
    function_id: str = DEFAULT_WARM_UP_FUNCTION,
    timeout_s: float = DEFAULT_WARM_UP_TIMEOUT_S,
) -> WarmUpOutcome:
    """Call *function_id* against *connection_env* and time the answer.

    *connection_env* names the client connection that serves the rolled
    environment. A failure carries the real transport or function error so
    the caller can fail its stage with it rather than marking a cold box
    deployed.
    """
    env = str(connection_env or "").strip()
    if not env:
        return WarmUpOutcome(
            ok=False,
            connection_env="",
            function_id=function_id,
            latency_ms=0,
            detail=(
                "no connection_env declared; a warm-up stage names the "
                "client connection that serves the rolled environment"
            ),
        )

    from yoke_cli.transport.dispatcher import build_request
    from yoke_cli.transport.https import (
        TransportError,
        relay_https,
        resolve_https_connection,
    )
    from yoke_contracts.api.function_call import TargetRef

    try:
        connection = resolve_https_connection(explicit_env=env)
    except TransportError as exc:
        return WarmUpOutcome(
            ok=False,
            connection_env=env,
            function_id=function_id,
            latency_ms=0,
            detail=f"connection {env!r} cannot relay: {exc}",
        )
    if connection is None:
        return WarmUpOutcome(
            ok=False,
            connection_env=env,
            function_id=function_id,
            latency_ms=0,
            detail=(
                f"connection {env!r} is not an https relay target; warm-up "
                "calls the deployed environment the way a client does. "
                f"Repair it with `yoke connection set {env} --transport "
                "https --api-url ...`"
            ),
        )

    request = build_request(
        function_id=function_id,
        target=TargetRef(kind="global"),
        intent="deploy warm-up",
    )
    started = _monotonic()
    response = relay_https(request, connection, timeout_s=timeout_s)
    latency_ms = int((_monotonic() - started) * 1000)
    if response.success:
        return WarmUpOutcome(
            ok=True,
            connection_env=env,
            function_id=function_id,
            latency_ms=latency_ms,
            detail=f"{function_id} answered {env} in {latency_ms}ms",
        )
    error = response.error
    reason = (
        f"{error.code}: {error.message}"
        if error is not None
        else "the call failed without a typed error"
    )
    return WarmUpOutcome(
        ok=False,
        connection_env=env,
        function_id=function_id,
        latency_ms=latency_ms,
        detail=(
            f"{function_id} failed against {env} after {latency_ms}ms "
            f"(timeout {timeout_s:g}s) — {reason}"
        ),
    )


__all__ = [
    "DEFAULT_WARM_UP_FUNCTION",
    "DEFAULT_WARM_UP_TIMEOUT_S",
    "WarmUpOutcome",
    "warm_up_environment",
]
