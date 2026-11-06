"""Both daemon clients keep bounded, scrubbed HTTP failure evidence."""

import io
import json
from urllib.error import HTTPError

import pytest

from yoke_core.domain import browser_client as core
from yoke_harness import browser_client as harness
from yoke_contracts.bounded_json_http import BoundedJsonHttpDeadlineError


@pytest.mark.parametrize("client", [core, harness])
def test_http_error_keeps_daemon_reason_and_scrubs_credential(client, monkeypatch):
    token = "private-daemon-token"
    raw = json.dumps(
        {
            "error": "color_scheme_observation_failed: navigation "
            + token
            + "\n"
            + "x" * 2000
        }
    ).encode()
    error = HTTPError(
        "http://127.0.0.1:1/api/exec/page", 400, "Bad Request", {}, io.BytesIO(raw)
    )
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise error

    monkeypatch.setattr(client, "urlopen", fail)
    with pytest.raises(RuntimeError) as caught:
        client.daemon_request(
            "/api/exec/page",
            {},
            state=client.DaemonState(endpoint="http://127.0.0.1:1", token=token),
        )
    message = str(caught.value)
    assert "browser_daemon_http_error" in message
    assert "HTTP 400" in message
    assert "color_scheme_observation_failed" in message
    assert token not in message
    assert "\n" not in message
    assert "inspect the existing page" in message
    assert len(message) < 900
    assert len(calls) == 1


@pytest.mark.parametrize("client", [core, harness])
def test_timeout_teaches_uncertain_action_without_replay(client, monkeypatch):
    def fail(*args, **kwargs):
        raise BoundedJsonHttpDeadlineError("JSON request exceeded its time limit")

    monkeypatch.setattr(client, "request_json", fail)
    with pytest.raises(
        RuntimeError,
        match="browser_daemon_response_timeout.*may have completed.*Do not replay",
    ):
        client.daemon_request(
            "/api/exec/step",
            {},
            state=client.DaemonState(endpoint="http://127.0.0.1:1", token="secret"),
        )
