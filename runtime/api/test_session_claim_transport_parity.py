"""Transport-parity guard for session/claim mutating function ids.

The bug this suite backstops: a mutating operation that bypasses the
connection-keyed dispatcher and hardcodes the local backend silently
writes the wrong authority when the active connection is https (the class
that broke ``/yoke do`` session establishment). Every ``yoke <subcommand>``
adapter funnels through ``call_dispatcher``, whose relay branch routes to
the server on an active https connection. This test asserts that invariant
holds for EVERY registered session/claim mutating function id — data-driven
off the live registry, so a newly registered id is covered automatically
with zero per-function authoring.

Scope note: this exercises the shared ``call_dispatcher`` transport layer
(what all adapters route through). To widen coverage to each adapter's own
envelope construction, invoke the CLI adapter from ``SUBCOMMAND_REGISTRY``
directly (as ``test_sessions_begin_function.TestAdapterTransportRouting``
does for ``sessions.begin``); a full adapter sweep is impractical because
each adapter has distinct required argparse flags.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_cli.transport.https import HttpsConnection


def _mutating_session_and_claim_function_ids() -> list[str]:
    """Registered session/claim function ids that have side effects."""
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import list_entries

    register_all_handlers()  # idempotent
    return sorted(
        entry.function_id
        for entry in list_entries()
        if entry.side_effects
        and entry.function_id.startswith(("sessions.", "claims."))
    )


_MUTATING_IDS = _mutating_session_and_claim_function_ids()


def test_mutating_id_set_is_populated_and_anchored():
    # Guard against a filter that silently matches nothing, and anchor on
    # the two ids at the heart of the transport-blindness this fixed.
    assert _MUTATING_IDS, "no session/claim mutating function ids collected"
    assert "sessions.begin" in _MUTATING_IDS
    assert "claims.work.acquire" in _MUTATING_IDS


@pytest.mark.parametrize("function_id", _MUTATING_IDS)
def test_mutation_routes_via_https_relay(function_id, monkeypatch):
    import yoke_cli.transport.dispatcher as dispatcher_mod
    from yoke_cli.transport import https as https_mod

    conn = HttpsConnection(
        api_url="https://api.example", token="tok", env="prod",
    )
    monkeypatch.setattr(https_mod, "resolve_https_connection", lambda: conn)
    captured = {}

    def fake_relay(request, connection, **kwargs):
        captured["request"] = request
        captured["connection"] = connection
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version="v1",
            request_id=request.request_id,
            result={},
        )

    def forbidden_local(*args, **kwargs):
        raise AssertionError(
            f"{function_id} dispatched locally instead of relaying on https"
        )

    monkeypatch.setattr(https_mod, "relay_https", fake_relay)
    monkeypatch.setattr(dispatcher_mod, "_call_local", forbidden_local)

    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload={},
        actor=build_actor(session_id="parity-session"),
    )
    assert response.success is True
    assert captured["request"].function == function_id
    assert captured["connection"] is conn
