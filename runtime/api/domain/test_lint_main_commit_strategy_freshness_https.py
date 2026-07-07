"""Https-transport coverage for the strategy-freshness commit lint.

The 12959 transport fold-in: the freshness reader resolves the
authoritative ``strategy_docs`` rows through the dispatcher (one
``strategy.render.run`` riding the active transport), so the same
protections hold on https-only machines. Before the dispatcher-backed
loader, an https-transport machine could not read the rows at all and
EVERY strategy-view commit failed closed.

Shares the world fixtures of
``test_lint_main_commit_strategy_freshness.py`` and simulates the
relay leg the way ``test_rebuild_board`` does: patch the transport
seam, JSON-wire round trip the envelope into the real in-process
dispatch.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import lint_main_commit as lint
from yoke_core.domain import lint_main_commit_strategy_freshness as freshness
from runtime.api.domain.test_lint_main_commit_strategy_freshness import (  # noqa: F401
    EDITED_MISSION,
    FRESH_MISSION,
    MISSION_REL,
    _payload,
    commit_world,
    tmp_db,
)


@pytest.fixture
def https_transport(monkeypatch: pytest.MonkeyPatch):
    """Route call_dispatcher's transport seam through a simulated https
    relay: JSON-wire round trip into the real in-process dispatch.
    Yields the relay kwargs captured per call so tests can assert the
    bounded round trip."""
    from yoke_cli.transport import https as yoke_transport
    from yoke_core.domain.yoke_function_dispatch import dispatch
    from yoke_contracts.api.function_call import FunctionCallResponse

    connection = yoke_transport.HttpsConnection(
        api_url="https://api.example.test", token="tok",
    )
    calls: list = []

    def fake_relay(request, conn, **kwargs):
        assert conn is connection
        calls.append(dict(kwargs))
        wire_request = json.loads(json.dumps(request.model_dump(mode="json")))
        response = dispatch(wire_request)
        wire_response = json.loads(
            json.dumps(response.model_dump(mode="json"))
        )
        return FunctionCallResponse.model_validate(wire_response)

    monkeypatch.setattr(
        yoke_transport, "resolve_https_connection",
        lambda *a, **k: connection,
    )
    monkeypatch.setattr(yoke_transport, "relay_https", fake_relay)
    return calls


class TestHttpsTransport:
    def test_fresh_view_passes_over_https(
        self, commit_world, https_transport,
    ) -> None:
        commit_world.staged.append(MISSION_REL)
        commit_world.blobs[MISSION_REL] = FRESH_MISSION
        reason = lint.evaluate_payload(_payload('git commit -m "x"'))
        assert reason is None
        # The fetch happened over the (simulated) relay, bounded by the
        # hook-budget ceiling, and the per-evaluation memo deduped the
        # freshness + matches-the-master reads into ONE round trip.
        assert len(https_transport) == 1
        assert https_transport[0].get("timeout_s") == (
            freshness.DISPATCH_TIMEOUT_S
        )

    def test_stale_view_denied_over_https(
        self, commit_world, https_transport,
    ) -> None:
        commit_world.staged.append(MISSION_REL)
        commit_world.blobs[MISSION_REL] = EDITED_MISSION
        reason = lint.evaluate_payload(_payload('git commit -m "x"'))
        assert reason is not None
        assert "stale strategy rendered view" in reason
        assert "edited without write-back" in reason
        assert len(https_transport) == 1

    def test_transport_failure_fails_closed_naming_the_retry(
        self, commit_world, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yoke_cli.transport import https as yoke_transport
        from yoke_core.domain import machine_config
        from yoke_contracts.api.function_call import (
            FunctionCallResponse,
            FunctionError,
        )

        connection = yoke_transport.HttpsConnection(
            api_url="https://api.example.test", token="tok",
        )

        def failing_relay(request, conn, **_kwargs):
            return FunctionCallResponse(
                success=False,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                error=FunctionError(
                    code="https_transport_failed",
                    message=(
                        "could not reach https://api.example.test"
                        "/v1/functions/call: timed out"
                    ),
                ),
            )

        monkeypatch.setattr(
            yoke_transport, "resolve_https_connection",
            lambda *a, **k: connection,
        )
        monkeypatch.setattr(yoke_transport, "relay_https", failing_relay)
        monkeypatch.setattr(
            machine_config, "load_config",
            lambda *a, **k: {
                "connections": {"prod-db-admin": {"transport": "local-postgres"}}
            },
        )

        commit_world.staged.append(MISSION_REL)
        commit_world.blobs[MISSION_REL] = FRESH_MISSION
        reason = lint.evaluate_payload(_payload('git commit -m "x"'))
        # Fail-closed posture survives; the denial names the transport
        # failure, the local-postgres retry env, and the audited override.
        assert reason is not None
        assert "failing closed" in reason
        assert "https_transport_failed" in reason
        assert "YOKE_ENV=prod-db-admin" in reason
        assert freshness.SUPPRESSION_TOKEN in reason
