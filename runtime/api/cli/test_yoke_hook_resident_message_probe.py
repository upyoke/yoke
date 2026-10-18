"""Which resident round trips count as a message probe.

The resident runs a session's read-only tool events locally for a short
window after a message probe, so only a round trip that actually leased the
session's inbox may open that window. A tool's PreToolUse on a surface that
cannot inject there leases nothing; letting it open the window would skip the
lease on the PostToolUse that follows it moments later.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from unittest.mock import Mock

import httpx
import pytest

from yoke_contracts.hook_evaluator_protocol import (
    HOOK_OBSERVATION_BATCH_CAPABILITY,
    HookEvaluatorRequest,
)
from yoke_contracts.hook_resident_routing import is_read_only_tool_event
from yoke_core.api.routes.hooks import HookEvaluateResponse
from yoke_core.hooks import session_message_delivery as delivery
from yoke_harness.hook_resident import _ResidentServer
from yoke_harness.hook_resident_http import ResidentHttpOpener
from runtime.harness.session_message_delivery_test_helpers import (
    FakePort,
    hook_context,
)


_EVALUATE_URL = "https://control-plane.test/v1/hooks/evaluate"


class _ControlPlane:
    """Answers ``/v1/hooks/evaluate`` with the real message-delivery hook."""

    def __init__(self, surface: str, *, reports_probe: bool = True) -> None:
        self.family = surface.split("-", 1)[0]
        self.surface = surface
        self.reports_probe = reports_probe
        self.evaluated: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        event_name = body["event_name"]
        self.evaluated.append(event_name)
        decision = delivery.evaluate(
            hook_context(
                event_name,
                family=self.family,
                surface=self.surface,
                payload=json.loads(body["stdin"]),
            )
        )
        response = HookEvaluateResponse(
            stdout="",
            exit_code=0,
            wait_ms=0,
            degraded=[],
            outcome="completed",
            message_probe=delivery.message_probe_ran([decision]),
        ).model_dump(mode="json")
        response["capabilities"] = [HOOK_OBSERVATION_BATCH_CAPABILITY]
        if not self.reports_probe:
            response.pop("message_probe")
        return httpx.Response(200, json=response)


def _relay_once(event_name: str, stdin: str, *, http_opener, **_kwargs) -> int:
    """Stand in for the hook chain's relay: one evaluate request per event."""
    request = urllib.request.Request(
        _EVALUATE_URL,
        data=json.dumps({"event_name": event_name, "stdin": stdin}).encode(),
        method="POST",
        headers={"Authorization": "Bearer test"},
    )
    with http_opener(request, timeout=5):
        return 0


def _resident(control_plane: _ControlPlane) -> _ResidentServer:
    server = object.__new__(_ResidentServer)
    server.probe_lock = threading.Lock()
    server.last_message_probes = {}
    server.started_at = time.monotonic()
    server.observations = Mock(diagnostic=Mock(return_value=""))
    server.http_opener = ResidentHttpOpener()
    server.http_opener._client = httpx.Client(
        transport=httpx.MockTransport(control_plane)
    )
    server.evaluate_inprocess = _relay_once
    # The first answer advertises the batch endpoint, as a live server does;
    # no surface injects on Stop, so it leases nothing.
    _relay_once("Stop", "{}", http_opener=server.http_opener)
    control_plane.evaluated.clear()
    return server


def _tool_event(
    server: _ResidentServer, event_name: str, tmp_path, tool_name: str = "Read"
) -> None:
    stdin = json.dumps({"tool_name": tool_name, "session_id": "session-top"})
    response, _target = server.evaluate(
        HookEvaluatorRequest(
            revision="unknown",
            event_name=event_name,
            stdin=stdin,
            environment={},
            cwd=str(tmp_path),
            pid=1,
            ppid=1,
            dry_run=False,
        )
    )
    assert response["status"] == "ok"


@pytest.fixture
def port(monkeypatch: pytest.MonkeyPatch) -> FakePort:
    fake = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: fake)
    return fake


def test_cursor_post_tool_use_leases_right_after_its_pre_tool_use(
    port: FakePort, tmp_path
) -> None:
    control_plane = _ControlPlane("cursor-cli")
    server = _resident(control_plane)

    _tool_event(server, "PreToolUse", tmp_path)
    _tool_event(server, "PostToolUse", tmp_path)

    assert control_plane.evaluated == ["PreToolUse", "PostToolUse"]
    assert port.leased == [("session-top", "PostToolUse", 10)]
    # The lease that ran opens the window for the session's next read event.
    assert server.should_evaluate_locally("session-top")


def test_an_injecting_pre_tool_use_lets_its_post_tool_use_run_locally(
    port: FakePort, tmp_path
) -> None:
    control_plane = _ControlPlane("claude-cli")
    server = _resident(control_plane)

    _tool_event(server, "PreToolUse", tmp_path)
    _tool_event(server, "PostToolUse", tmp_path)

    assert control_plane.evaluated == ["PreToolUse"]
    assert port.leased == [("session-top", "PreToolUse", 10)]


def test_a_failed_lease_is_not_a_probe(port: FakePort, tmp_path) -> None:
    port.lease_error = RuntimeError("control plane unreachable")
    control_plane = _ControlPlane("claude-cli")
    server = _resident(control_plane)

    _tool_event(server, "PreToolUse", tmp_path)

    assert not server.should_evaluate_locally("session-top")


def test_a_server_without_the_probe_field_never_opens_the_window(
    port: FakePort, tmp_path
) -> None:
    control_plane = _ControlPlane("claude-cli", reports_probe=False)
    server = _resident(control_plane)

    _tool_event(server, "PreToolUse", tmp_path)
    _tool_event(server, "PostToolUse", tmp_path)

    assert control_plane.evaluated == ["PreToolUse", "PostToolUse"]
    assert not server.should_evaluate_locally("session-top")


@pytest.mark.parametrize("tool_name", ["Shell", "StrReplace"])
def test_cursor_native_names_of_guarded_tools_are_never_read_only(
    tool_name: str,
) -> None:
    """The resident reads the raw payload, before Cursor's parser renames
    ``Shell`` to ``Bash``; the guarded chain must still be found."""
    payload = json.dumps({"tool_name": tool_name, "session_id": "s1"})
    for event_name in ("PreToolUse", "PostToolUse"):
        assert not is_read_only_tool_event(event_name, payload)


def test_a_cursor_shell_post_tool_use_inside_the_window_still_leases(
    port: FakePort, tmp_path
) -> None:
    control_plane = _ControlPlane("cursor-cli")
    server = _resident(control_plane)

    _tool_event(server, "PostToolUse", tmp_path)
    assert server.should_evaluate_locally("session-top")
    _tool_event(server, "PostToolUse", tmp_path, tool_name="Shell")

    assert control_plane.evaluated == ["PostToolUse", "PostToolUse"]
    assert port.leased == [("session-top", "PostToolUse", 10)] * 2
