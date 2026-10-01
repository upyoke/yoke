"""The HTTP auth boundary keeps credential work off the event loop.

Token verification opens a database connection and writes token-use and
audit rows. Awaiting that inline on the single event loop makes one slow
credential check the latency floor for every other in-flight request, so
these tests pin both halves of the fix: the offload itself, and the
per-phase request telemetry that makes the next stall diagnosable.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from yoke_core.api import app_factory, http_auth
from yoke_core.api.http_auth import HttpAuthContext
from yoke_core.api.main import app
from yoke_core.domain.api_tokens import (
    TokenExpired,
    TokenMachineRetired,
    TokenNotFound,
    TokenRevoked,
)
from yoke_core.domain import db_backend


CONCURRENT_SLOW_REQUESTS = 5
#: A deadlock bound, not a latency target: ordering proves the offload even
#: when unrelated CI load delays scheduling.
WAIT_TIMEOUT_SECONDS = 10

BEARER_HEADERS = {"authorization": "Bearer test-token"}


def _auth_context() -> HttpAuthContext:
    return HttpAuthContext(token_id=1, actor_id=1, token_name="test-token")


def _client() -> httpx.AsyncClient:
    """Async client over the ASGI app — the only shape that can race requests."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    )


@contextmanager
def _sync_client() -> Iterator[TestClient]:
    """Drive the app without running lifespan, which would open the database."""
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()


async def _race_light_request_against_slow_auth(
    started: threading.Barrier,
    released: threading.Event,
) -> list[int]:
    """Health completes while all credential checks are still blocked."""
    async with _client() as client:

        async def slow() -> int:
            response = await client.get(
                "/v1/functions/registry", headers=BEARER_HEADERS
            )
            return response.status_code

        slow_tasks = [
            asyncio.create_task(slow()) for _ in range(CONCURRENT_SLOW_REQUESTS)
        ]
        try:
            # All checks must enter concurrently before any may finish.
            await asyncio.to_thread(started.wait, WAIT_TIMEOUT_SECONDS)
            response = await asyncio.wait_for(
                client.get("/v1/health"),
                timeout=WAIT_TIMEOUT_SECONDS,
            )
            assert response.status_code == 200
            assert all(not task.done() for task in slow_tasks)
        finally:
            released.set()
            statuses = await asyncio.wait_for(
                asyncio.gather(*slow_tasks),
                timeout=WAIT_TIMEOUT_SECONDS,
            )
    return list(statuses)


def test_slow_credential_check_does_not_stall_unrelated_request(monkeypatch) -> None:
    started = threading.Barrier(CONCURRENT_SLOW_REQUESTS + 1)
    released = threading.Event()
    event_loop_thread = threading.get_ident()

    def slow_authenticate(request: Any) -> HttpAuthContext:
        assert threading.get_ident() != event_loop_thread, "auth blocked the event loop"
        started.wait(WAIT_TIMEOUT_SECONDS)
        assert released.wait(WAIT_TIMEOUT_SECONDS), "health did not finish during auth"
        return _auth_context()

    monkeypatch.setattr(app_factory, "authenticate_request", slow_authenticate)

    statuses = asyncio.run(_race_light_request_against_slow_auth(started, released))

    assert statuses == [200] * CONCURRENT_SLOW_REQUESTS


def test_missing_credential_is_denied_with_bearer_challenge() -> None:
    with _sync_client() as client:
        response = client.get(
            "/v1/functions/registry", headers={"x-request-id": "rid-missing"}
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["x-request-id"] == "rid-missing"
    assert response.json()["error"]["code"] == "authentication_required"


def test_malformed_authorization_header_is_denied() -> None:
    with _sync_client() as client:
        response = client.get(
            "/v1/functions/registry", headers={"authorization": "Basic abc"}
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_malformed"


@pytest.mark.parametrize(
    "raised,status_code,code",
    [
        (ValueError("bad syntax"), 401, "authentication_malformed"),
        (TokenNotFound("unknown"), 401, "authentication_unknown"),
        (TokenRevoked("revoked"), 401, "authentication_revoked"),
        (TokenExpired("expired"), 401, "authentication_expired"),
        (TokenMachineRetired("machine retired"), 401, "machine_retired"),
    ],
)
def test_verification_failures_keep_their_denial_envelope(
    monkeypatch, raised: Exception, status_code: int, code: str
) -> None:
    def raise_on_verify(*args: Any, **kwargs: Any) -> Any:
        raise raised

    monkeypatch.setattr(http_auth, "verify_token", raise_on_verify)

    with _sync_client() as client:
        response = client.get("/v1/functions/registry", headers=BEARER_HEADERS)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_database_failure_reports_verification_unavailable(monkeypatch) -> None:
    error_type = db_backend.database_error_types()[0]

    def raise_on_verify(*args: Any, **kwargs: Any) -> Any:
        raise error_type("connection refused")

    monkeypatch.setattr(http_auth, "verify_token", raise_on_verify)

    with _sync_client() as client:
        response = client.get("/v1/functions/registry", headers=BEARER_HEADERS)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"


def _captured_verify_metadata(monkeypatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def capture(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs.get("diagnostic_metadata") or {})
        raise TokenNotFound("unknown")

    monkeypatch.setattr(http_auth, "verify_token", capture)
    return captured


def test_token_verify_audit_carries_the_minted_request_id(monkeypatch) -> None:
    captured = _captured_verify_metadata(monkeypatch)

    with _sync_client() as client:
        response = client.get("/v1/functions/registry", headers=BEARER_HEADERS)

    minted = response.headers["x-request-id"]
    assert minted
    assert captured["request_id"] == minted


def test_token_verify_audit_keeps_a_caller_supplied_request_id(monkeypatch) -> None:
    captured = _captured_verify_metadata(monkeypatch)

    with _sync_client() as client:
        client.get(
            "/v1/functions/registry",
            headers={**BEARER_HEADERS, "x-request-id": "rid-supplied"},
        )

    assert captured["request_id"] == "rid-supplied"


def _request_context(caplog) -> dict[str, Any]:
    records = [
        r
        for r in caplog.records
        if getattr(r, "event_name", "") == "HttpRequestCompleted"
    ]
    assert records, "no completed-request log record was emitted"
    return getattr(records[-1], "context")


def test_request_log_times_auth_and_admission(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        app_factory, "authenticate_request", lambda request: _auth_context()
    )

    with caplog.at_level(logging.INFO, logger="yoke.api.http"):
        with _sync_client() as client:
            response = client.get("/v1/functions/registry", headers=BEARER_HEADERS)

    assert response.status_code == 200
    context = _request_context(caplog)
    assert context["auth_duration_ms"] >= 0
    assert context["admission_duration_ms"] >= 0


def test_request_log_times_dispatcher_overhead(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        app_factory, "authenticate_request", lambda request: _auth_context()
    )

    with caplog.at_level(logging.INFO, logger="yoke.api.http"):
        with _sync_client() as client:
            response = client.post(
                "/v1/functions/call",
                headers=BEARER_HEADERS,
                json={"function": "unregistered.probe", "payload": {}},
            )

    # Refused on the envelope, before any handler runs: the overhead is
    # then the whole dispatcher cost, which is exactly what needs a number.
    assert response.status_code == 422
    assert "dispatch_overhead_duration_ms" in _request_context(caplog)
