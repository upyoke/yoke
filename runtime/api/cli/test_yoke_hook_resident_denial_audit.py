"""A resident's deny reaches its caller before the deny's audit is posted.

The caller waits only for what is left of its hook budget; a cold Windows
start can leave it about a second. The audit POST to the control plane is
telemetry and may take longer, so it must never stand between a decided
deny and the harness (YOK-5581).
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.transport.https import HttpsConnection
from yoke_harness import hook_resident, hook_resident_client_wall
from yoke_harness.hooks import denial_relay
from yoke_harness.hooks.deadline import HookDeadline

_DENY = {"status": "ok", "stdout": '{"deny": true}', "stderr": "", "exit_code": 0}


class _Server:
    loaded_revision = "rev"

    def __init__(self, timeline: list[str]) -> None:
        self.timeline = timeline

    def begin_request(self) -> None:
        self.timeline.append("begin")

    def end_request(self) -> None:
        self.timeline.append("end")

    def evaluate(self, _request):
        # What relay_hook_event does on a client-local deny.
        denial_relay.submit_denial_audit(
            HttpsConnection(api_url="https://example.test", token="tok"),
            {"hook": "yoke_core.domain.lint_lane_main_write", "mode": "deny"},
            HookDeadline(budget_ms=1000, started_at=0.0, clock=lambda: 0.0),
        )
        self.timeline.append("evaluated")
        return dict(_DENY), None


class _Peer:
    def settimeout(self, _seconds) -> None:
        return None


def _handle(monkeypatch, timeline: list[str]) -> None:
    request = SimpleNamespace(revision="rev", client_timing_id="")
    monkeypatch.setattr(hook_resident, "receive_request", lambda *_a: request)
    monkeypatch.setattr(hook_resident, "same_revision", lambda *_a: True)
    monkeypatch.setattr(
        hook_resident_client_wall,
        "send_frame",
        lambda _peer, frame: timeline.append(f"reply:{frame['stdout']}"),
    )
    monkeypatch.setattr(
        denial_relay,
        "request_json",
        lambda request, **_k: timeline.append(f"audit:{request.full_url}"),
    )
    handler = object.__new__(hook_resident._ResidentHandler)
    handler.server = _Server(timeline)
    handler.request = _Peer()
    handler.handle()


def test_deny_reply_is_sent_before_the_denial_audit_post(monkeypatch) -> None:
    timeline: list[str] = []
    _handle(monkeypatch, timeline)
    assert timeline == [
        "begin",
        "evaluated",
        'reply:{"deny": true}',
        f"audit:https://example.test{denial_relay.DENIAL_AUDIT_PATH}",
        "end",
    ]


def test_handler_leaves_no_hold_behind(monkeypatch) -> None:
    _handle(monkeypatch, [])
    posted: list[float] = []
    monkeypatch.setattr(
        denial_relay,
        "request_json",
        lambda _request, **k: posted.append(k["timeout_seconds"]),
    )
    denial_relay.submit_denial_audit(
        HttpsConnection(api_url="https://example.test", token="tok"),
        {"hook": "x"},
        HookDeadline(budget_ms=500, started_at=0.0, clock=lambda: 0.0),
    )
    assert posted == [0.5]
