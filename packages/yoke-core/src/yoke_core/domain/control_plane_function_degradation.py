"""Continue a relayed call the deployed control plane does not yet serve.

A client build is routinely ahead of the plane it relays to — that is the
normal state of a change on its way to release. Most callers can wait for
the deploy. A merge cannot: the deploy that would teach the server the
function is carried by the very branch the merge is trying to land, so a
hard refusal makes the client's own upgrade unreachable.

The way through is that the client already holds the handler. What it
lacks over https is a database, and the machine that runs the merge has
one door into the same universe the plane serves: the direct-Postgres
admin connection paired with it by label. Re-dispatching in-process
through that connection answers the same question against the same rows,
with the client's registry instead of the server's.

It is a degradation and says so out loud. Direct database authority is an
operator-grade path, so it is taken only for a registry-skew answer, only
when that paired connection is configured, and only with the substitution
printed where the operator running the merge will read it.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any, Callable, Iterator, Optional

from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
from yoke_contracts.control_plane_locality import local_authority_exempt
from yoke_contracts.machine_config.schema import (
    ENV_OVERRIDE,
    same_universe_db_admin_env,
)

#: Error codes meaning "this registry does not carry that function" — the
#: typed client/server skew verdict, and the raw server answer it retypes.
REGISTRY_SKEW_CODES = frozenset({"function_version_skew", "function_not_registered"})


def _skewed(response: FunctionCallResponse) -> bool:
    return (
        not response.success
        and response.error is not None
        and response.error.code in REGISTRY_SKEW_CODES
    )


def paired_admin_env() -> str:
    """The direct-Postgres env serving the active connection's universe."""
    try:
        from yoke_cli.config import machine_config

        return same_universe_db_admin_env(
            machine_config.load_config(), machine_config.active_env(),
        )
    except Exception:  # noqa: BLE001 - an unreadable config simply has no pair
        return ""


@contextlib.contextmanager
def _selected_env(env: str) -> Iterator[None]:
    """Pin the active connection to *env* for the duration of the block."""
    previous = os.environ.get(ENV_OVERRIDE)
    os.environ[ENV_OVERRIDE] = env
    try:
        # The client marked this context remote when it resolved an https
        # connection. Inside the block the connection is a local database
        # this machine holds authority over, which is exactly the
        # declaration the marker's exemption exists for.
        with local_authority_exempt():
            yield
    finally:
        if previous is None:
            os.environ.pop(ENV_OVERRIDE, None)
        else:
            os.environ[ENV_OVERRIDE] = previous


def dispatch_through_paired_admin_on_skew(
    *,
    function_id: str,
    target: TargetRef,
    payload: Optional[dict[str, Any]] = None,
    announce: Callable[[str], None],
    dispatch: Optional[Callable[..., FunctionCallResponse]] = None,
) -> FunctionCallResponse:
    """Relay *function_id*, retrying in-process when the server lacks it.

    Returns the relayed response untouched on success, and on any error
    other than registry skew. A skew answer with no paired admin
    connection also comes back untouched, so the caller still surfaces the
    server's own recovery guidance.
    """
    if dispatch is None:
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        dispatch = call_dispatcher

    response = dispatch(function_id=function_id, target=target, payload=payload)
    if not _skewed(response):
        return response
    admin_env = paired_admin_env()
    if not admin_env:
        return response

    announce(
        f"[degraded] the deployed control plane does not serve "
        f"{function_id!r}; resolving it against the same universe through "
        f"the {admin_env!r} direct-Postgres connection"
    )
    with _selected_env(admin_env):
        return dispatch(
            function_id=function_id,
            target=target,
            payload=payload,
            local_only=True,
        )


__all__ = [
    "REGISTRY_SKEW_CODES",
    "dispatch_through_paired_admin_on_skew",
    "paired_admin_env",
]
