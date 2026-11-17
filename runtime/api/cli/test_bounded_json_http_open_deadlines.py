"""urllib's connect/send wrapper preserves the JSON transport's deadline type."""

from __future__ import annotations

import http.client
import urllib.request

import pytest

from yoke_contracts import bounded_json_http as transport
from yoke_contracts import pre_resolved_https
from yoke_contracts import response_deadline_read
from yoke_contracts.response_deadline_errors import (
    ResponseHeadersDeadlineError,
    ResponseOpenDeadlineError,
)


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("replay_safe", [False, True])
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (ResponseOpenDeadlineError, transport.BoundedJsonHttpDeadlineError),
        (ResponseHeadersDeadlineError, transport.BoundedJsonHttpDeadlineError),
        (TimeoutError, transport.BoundedJsonHttpDeadlineError),
        (ConnectionRefusedError, transport.BoundedJsonHttpNetworkError),
    ],
)
def test_connect_deadline_survives_urllib_oserror_wrapper(
    monkeypatch, scheme: str, replay_safe: bool, failure: type, expected: type
) -> None:
    # Exercise the real HTTP(S) handler's URLError wrapping without scheduler,
    # DNS, socket or wall-clock races. Both reads and caller-owned POSTs use it.
    monkeypatch.setattr(response_deadline_read, "monotonic", lambda: 1.0)
    monkeypatch.setattr(
        pre_resolved_https,
        "_resolve_target",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 8765))],
    )
    seen = []

    def fail_connect(*_args, **_kwargs):
        seen.append(failure)
        raise failure("private diagnostic")

    monkeypatch.setattr(
        http.client.HTTPConnection, "connect", fail_connect
    )
    request = urllib.request.Request(
        f"{scheme}://127.0.0.1:8765/api/health",
        method="GET" if replay_safe else "POST",
        data=None if replay_safe else b"{}",
    )

    with pytest.raises(expected) as raised:
        transport.request_json(
            request,
            timeout_seconds=30.0,
            replay_safe=replay_safe,
            allow_private_http=True,
        )

    assert seen == [failure]
    assert "private diagnostic" not in str(raised.value)
    if expected is transport.BoundedJsonHttpDeadlineError:
        assert str(raised.value) == "JSON request exceeded its time limit"
    else:
        assert raised.value.reason == "refused"
