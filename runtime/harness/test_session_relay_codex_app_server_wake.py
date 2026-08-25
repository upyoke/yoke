"""Codex app-server wake mechanics: status transitions and turn ownership.

Split from ``test_session_relay_codex.py`` (350-line authored cap). Shares
the ``context`` fixture from that module rather than duplicating it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_harness import session_relay_codex as adapter_module
from yoke_harness import session_relay_codex_app_server as app_module
from yoke_harness.session_relay_codex import CodexNativeOutcome

from runtime.harness.test_session_relay_codex import INSTRUCTION, SECRET, context


class FakeAppClient:
    def __init__(self, status: str, *, exact_identity: bool = True) -> None:
        self.status = status
        self.exact_identity = exact_identity
        self.calls: list[tuple[str, dict]] = []
        self.detached: str | None = None
        self.closed = False

    def request(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        identity = "native-1" if self.exact_identity else "different-session"
        thread = {
            "id": "native-1",
            "sessionId": identity,
            "status": {"type": self.status},
            "turns": (
                [{"id": "turn-1", "status": "inProgress"}]
                if self.status == "active"
                else []
            ),
        }
        if method in {"thread/start", "thread/read", "thread/resume"}:
            return {"thread": thread}
        if method == "turn/start":
            return {"turn": {"id": "turn-2"}}
        return {}

    def detach_until_turn_completed(self, turn_id: str) -> None:
        self.detached = turn_id

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    "wake_mode,status,mutation",
    [
        ("waiting", "active", "turn/steer"),
        ("idle_timeout", "idle", "turn/start"),
        ("waiting", "notLoaded", "turn/start"),
    ],
)
def test_app_server_uses_exact_status_and_id_with_fake_transport(
    monkeypatch,
    tmp_path: Path,
    wake_mode: str,
    status: str,
    mutation: str,
) -> None:
    client = FakeAppClient(status)
    monkeypatch.setattr(
        app_module.CodexAppServerTransport, "_client", lambda *_: client
    )
    request = adapter_module._request(
        context(
            tmp_path,
            surface="codex-desktop",
            job_kind="wake",
            target_liveness="active",
            wake_mode=wake_mode,
        )
    )[0]

    outcome = app_module.CodexAppServerTransport(worker=True).wake(request)

    assert outcome.state == "accepted"
    assert outcome.identity_correlated is True
    assert mutation in [method for method, _params in client.calls]
    mutation_params = next(
        params for method, params in client.calls if method == mutation
    )
    assert INSTRUCTION in repr(mutation_params)
    assert SECRET not in repr(mutation_params)


def test_app_server_create_requires_vendor_thread_session_equality(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = FakeAppClient("idle", exact_identity=False)
    monkeypatch.setattr(
        app_module.CodexAppServerTransport, "_client", lambda *_: client
    )
    request = adapter_module._request(context(tmp_path, surface="codex-desktop"))[0]

    outcome = app_module.CodexAppServerTransport(worker=True).create(request)

    assert outcome.state == "outcome_unknown"
    assert "turn/start" not in [method for method, _params in client.calls]
    assert client.closed is True


def test_app_server_delegates_real_turn_ownership_out_of_serve_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = adapter_module._request(context(tmp_path, surface="codex-desktop"))[0]
    calls = []
    expected = CodexNativeOutcome("accepted", "native-1", True)
    monkeypatch.setattr(
        app_module.CodexAppServerTransport,
        "_detached",
        staticmethod(lambda value: calls.append(value) or expected),
    )

    outcome = app_module.CodexAppServerTransport().create(request)

    assert outcome == expected
    assert calls == [request]
