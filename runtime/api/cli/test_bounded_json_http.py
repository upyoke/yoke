"""Security contract for shared hosted-client JSON transport."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from yoke_cli.transport import bounded_http_open_policy as open_policy
from yoke_cli.transport import bounded_json_http as transport
from yoke_cli.transport import response_deadline_read
from yoke_cli.transport.response_limits import BUNDLE_JSON_RESPONSE_LIMIT_BYTES


class _Response:
    status = 200

    def __init__(
        self,
        body: bytes,
        *,
        headers: dict[str, str] | None = None,
        final_url: str = "https://api.example/v1/x",
    ) -> None:
        self.body = body
        self.headers = dict(headers or {})
        self.final_url = final_url
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self) -> None:
        self.closed = True

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def geturl(self) -> str:
        return self.final_url


def _request(method: str = "GET", *, url: str = "https://api.example/v1/x"):
    data = b"{}" if method == "POST" else None
    return urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": "Bearer actor-secret"},
    )


def test_default_get_uses_redirect_free_replay_safe_open(monkeypatch) -> None:
    seen = {}

    def open_replay(request, *, opener, deadline):
        seen.update(request=request, opener=opener, deadline=deadline)
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(open_policy, "open_replay_safe", open_replay)
    monkeypatch.setattr(
        open_policy,
        "open_https_caller_owned",
        lambda *_args, **_kwargs: pytest.fail("GET used caller-owned POST open"),
    )

    response = transport.request_json(
        _request(),
        timeout_seconds=2.0,
        replay_safe=True,
    )

    assert response.payload == {"ok": True}
    assert seen["request"].get_method() == "GET"
    assert seen["opener"] is open_policy.open_no_redirect


def test_default_post_stays_caller_owned_and_denies_redirects(monkeypatch) -> None:
    seen = {}

    def open_caller_owned(request, *, deadline, handlers):
        seen.update(request=request, deadline=deadline, handlers=handlers)
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(
        open_policy,
        "open_https_caller_owned",
        open_caller_owned,
    )
    monkeypatch.setattr(
        open_policy,
        "open_replay_safe",
        lambda *_args, **_kwargs: pytest.fail("POST entered replay-safe worker"),
    )

    response = transport.request_json(
        _request("POST"),
        timeout_seconds=2.0,
        replay_safe=False,
    )

    assert response.payload == {"ok": True}
    assert seen["request"].get_method() == "POST"
    assert len(seen["handlers"]) == 1
    assert isinstance(seen["handlers"][0], open_policy.NoRedirect)


def test_error_body_is_bounded_redacted_and_control_safe() -> None:
    body = json.dumps({"error": {"message": "echo actor-secret\n\x1b[31m"}}).encode(
        "utf-8"
    )

    def reject(request, timeout):
        del timeout
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {"Content-Length": str(len(body))},
            io.BytesIO(body),
        )

    with pytest.raises(transport.BoundedJsonHttpStatusError) as raised:
        transport.request_json(
            _request(),
            timeout_seconds=2.0,
            replay_safe=True,
            opener=reject,
        )

    assert raised.value.status == 401
    detail = transport.error_detail(raised.value.payload)
    assert "actor-secret" not in detail
    assert "<redacted>" in detail
    assert "\\x0a" in detail
    assert "\\x1b" in detail


def test_open_and_body_share_one_absolute_deadline(monkeypatch) -> None:
    class Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()

    class SlowBody(_Response):
        fp = object()

        def read(self, _size: int = -1) -> bytes:
            raise AssertionError("network body must use incremental reads")

        def read1(self, _size: int = -1) -> bytes:
            clock.now += 0.7
            return b"{}"

        def settimeout(self, _seconds: float) -> None:
            return None

    def delayed_open(_request, timeout):
        assert timeout == pytest.approx(1.0)
        clock.now += 0.4
        return SlowBody(b"")

    monkeypatch.setattr(response_deadline_read, "monotonic", clock)

    with pytest.raises(transport.BoundedJsonHttpDeadlineError):
        transport.request_json(
            _request("POST"),
            timeout_seconds=1.0,
            replay_safe=False,
            opener=delayed_open,
        )


def test_plain_http_is_numeric_loopback_only() -> None:
    with pytest.raises(
        transport.BoundedJsonHttpConfigurationError,
        match="numeric loopback",
    ):
        transport.request_json(
            _request(url="http://api.example/v1/x"),
            timeout_seconds=1.0,
            replay_safe=True,
            allow_loopback_http=True,
            opener=lambda *_args, **_kwargs: pytest.fail(
                "unsafe endpoint reached the opener"
            ),
        )

    response = transport.request_json(
        _request(url="http://127.0.0.1:8765/v1/x"),
        timeout_seconds=1.0,
        replay_safe=True,
        allow_loopback_http=True,
        opener=lambda *_args, **_kwargs: _Response(
            b'{"ok": true}',
            final_url="http://127.0.0.1:8765/v1/x",
        ),
    )
    assert response.payload == {"ok": True}


def test_injected_opener_redirect_result_is_rejected_before_body_read() -> None:
    response = _Response(
        b'{"echo": "actor-secret"}',
        final_url="https://attacker.example/collect",
    )

    with pytest.raises(
        transport.BoundedJsonHttpBodyError,
        match="final URL did not match",
    ):
        transport.request_json(
            _request(),
            timeout_seconds=1.0,
            replay_safe=True,
            opener=lambda *_args, **_kwargs: response,
        )

    assert response.closed is True


def test_response_header_names_are_case_insensitive() -> None:
    response = transport.request_json(
        _request(),
        timeout_seconds=1.0,
        replay_safe=True,
        opener=lambda *_args, **_kwargs: _Response(
            b"{}",
            headers={"cAcHe-CoNtRoL": "no-store"},
        ),
    )

    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "module_name",
    [
        "yoke_harness.browser_client",
        "yoke_core.domain.browser_client",
    ],
)
def test_browser_daemon_clients_keep_post_caller_owned(
    monkeypatch,
    module_name: str,
) -> None:
    module = __import__(module_name, fromlist=["browser_client"])
    seen = {}

    def fake_request_json(request, **kwargs):
        seen.update(request=request, **kwargs)
        return transport.BoundedJsonHttpResponse(
            payload={"status": "ok"},
            status=200,
            headers={},
        )

    monkeypatch.setattr(module, "request_json", fake_request_json)
    state = module.DaemonState(
        pid=1,
        token="daemon-secret",
        endpoint="http://127.0.0.1:9222",
    )

    assert module.daemon_request("/api/health", state=state) == {"status": "ok"}
    assert seen["request"].get_method() == "POST"
    assert seen["replay_safe"] is False
    assert seen["allow_loopback_http"] is True
    assert seen["sensitive_values"] == ("daemon-secret",)


def test_project_install_bundle_declares_replay_safe_bounded_get(
    monkeypatch,
) -> None:
    from yoke_cli.project_install import transport as install_transport

    seen = {}

    def fake_request_json(request, **kwargs):
        seen.update(request=request, **kwargs)
        return transport.BoundedJsonHttpResponse(
            payload={"bundle_schema": 1},
            status=200,
            headers={},
        )

    monkeypatch.setattr(install_transport, "request_json", fake_request_json)
    payload = install_transport._fetch_bundle_https(
        SimpleNamespace(
            api_url="https://api.example",
            token="actor-secret",
        ),
        41,
    )

    assert payload == {"bundle_schema": 1}
    assert seen["request"].get_method() == "GET"
    assert seen["replay_safe"] is True
    assert seen["response_limit_bytes"] == BUNDLE_JSON_RESPONSE_LIMIT_BYTES


def test_auth_boundary_verifier_keeps_bearer_probe_caller_owned(
    monkeypatch,
) -> None:
    from yoke_core.tools import verify_env_auth_boundary as verifier

    seen = {}

    def fake_request_json(request, **kwargs):
        seen.update(request=request, **kwargs)
        return transport.BoundedJsonHttpResponse(
            payload={"success": True},
            status=200,
            headers={},
        )

    monkeypatch.setattr(verifier, "request_json", fake_request_json)
    status, body = verifier._request(
        "https://api.example/v1/functions/call",
        method="POST",
        token="stage-secret",
        payload={"function": "events.query.run"},
    )

    assert status == 200
    assert json.loads(body) == {"success": True}
    assert seen["request"].get_method() == "POST"
    assert seen["replay_safe"] is False
    assert seen["sensitive_values"] == ("stage-secret",)
