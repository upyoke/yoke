"""Timeout causes survive the resident opener and shared harness relay."""

import json
import urllib.request
from types import SimpleNamespace

import httpx
import pytest

from yoke_harness.hook_resident_http import ResidentHttpOpener
from yoke_harness.hooks import relay
from yoke_cli.transport.https import HttpsConnection
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpDeadlineError,
    BoundedJsonHttpNetworkError,
)
from runtime.api.cli.hook_relay_test_support import local_subset as local_subset  # noqa: F401


def test_resident_preserves_httpx_read_timeout():
    opener = ResidentHttpOpener()
    opener._client.close()

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("forced read timeout")

    opener._client = SimpleNamespace(stream=timeout)
    with pytest.raises(TimeoutError, match="timed out"):
        opener(
            urllib.request.Request("https://example.test/v1/hooks/evaluate"), timeout=1
        )


@pytest.mark.parametrize("executor", ["claude", "codex", "cursor"])
@pytest.mark.parametrize(
    "error,wording",
    [
        (BoundedJsonHttpDeadlineError("deadline"), "timed out"),
        (BoundedJsonHttpNetworkError("read", reason="timed_out"), "timed out"),
        (BoundedJsonHttpNetworkError("connection refused"), "unreachable"),
    ],
)
def test_every_harness_relay_names_transport_cause(
    monkeypatch,
    capsys,
    executor,
    error,
    wording,
    local_subset,
):
    monkeypatch.setattr(relay, "detect_executor", lambda: executor)
    monkeypatch.setattr(relay, "_record_client_anchor", lambda *a, **kw: None)
    monkeypatch.setattr(relay, "_codex_capture", lambda *a: None)
    monkeypatch.setattr(relay, "stamp_hook_input", lambda payload, raw, *a: (raw, None))
    monkeypatch.setattr(relay, "deny_unstamped_relay", lambda payload: None)
    monkeypatch.setattr(relay, "relay_identity_payload", lambda *a, **kw: {})
    monkeypatch.setattr(
        "yoke_harness.hooks.machine_hooks.ensure_machine_hooks_for_executor",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay_degrade.detect_executor", lambda: executor
    )

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(relay, "request_json", fail)
    assert (
        relay.relay_hook_event(
            "PreToolUse",
            HttpsConnection(api_url="https://example.test", token="token"),
            stdin_data=json.dumps({"session_id": "synthetic"}),
        )
        == 0
    )
    output = capsys.readouterr()
    assert f"hook relay {wording}" in output.out + output.err
    if wording == "timed out":
        assert "unreachable" not in output.out + output.err
